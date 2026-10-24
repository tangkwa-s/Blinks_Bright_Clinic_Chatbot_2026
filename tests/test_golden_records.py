"""Regression tests for the golden-record / customer dedup feature.

Covers ``app/routers/customers.py`` (GET /api/customers/duplicates,
POST /api/customers/merge) plus the ``handle_inbound`` identity-redirect that
keeps a merged-away channel landing on the surviving golden record.
"""
from datetime import datetime, timedelta

from app import models
from app.services.inbox import handle_inbound


def _branch_and_service(db, cid):
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    service = db.query(models.Service).filter_by(clinic_id=cid).first()
    assert branch is not None and service is not None
    return branch, service


def _make_pair(db, cid):
    """Two customers in the SAME clinic that share a phone number written in two
    different formats, arriving on different channels. The LINE record (the
    duplicate) carries a Conversation + Booking + Payment that should follow it
    onto the golden record after a merge. Returns (primary, dup, conv, bk, pay)."""
    branch, service = _branch_and_service(db, cid)
    primary = models.Customer(
        clinic_id=cid, name="Jane Doe", phone="081-234-5678",
        channel="web", channel_user_id="web-jane", branch_id=branch.id,
        pipeline_stage="interested", temperature="warm",
        lead_score=30, ltv=1000.0,
    )
    dup = models.Customer(
        clinic_id=cid, name="LINE User", phone="0812345678",
        channel="line", channel_user_id="Uline999", branch_id=branch.id,
        pipeline_stage="booked", temperature="hot",
        lead_score=80, ltv=500.0,
    )
    db.add_all([primary, dup])
    db.flush()

    conv = models.Conversation(
        clinic_id=cid, customer_id=dup.id, channel="line",
        branch_id=branch.id, status="new_lead", sales_stage="greeting",
    )
    db.add(conv)
    db.flush()

    bk = models.Booking(
        clinic_id=cid, customer_id=dup.id, branch_id=branch.id,
        service_id=service.id, conversation_id=conv.id,
        slot_at=datetime.utcnow() + timedelta(days=1),
        price=service.base_price, deposit_required=200.0,
        status="pending", created_by="ai",
    )
    db.add(bk)
    db.flush()

    pay = models.Payment(
        clinic_id=cid, customer_id=dup.id, booking_id=bk.id,
        type="deposit", amount=200.0, status="pending",
    )
    db.add(pay)
    db.commit()
    return primary, dup, conv, bk, pay


def test_duplicates_detects_same_phone_in_different_formats(db, auth_client):
    cid = auth_client.test_clinic.id
    primary, dup, *_ = _make_pair(db, cid)
    pid, did = primary.id, dup.id

    r = auth_client.get("/api/customers/duplicates")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] >= 1

    # The two records (phone written as 081-234-5678 vs 0812345678) must land in
    # the same merge-suggestion group.
    group = next(
        (g for g in data["groups"]
         if {pid, did} <= {c["id"] for c in g["customers"]}),
        None,
    )
    assert group is not None, "duplicates not grouped together"
    assert "phone" in group["match"]
    assert len(group["customers"]) == 2
    # both channel identities are represented in the group
    channels = {c["channel"] for c in group["customers"]}
    assert channels == {"web", "line"}


def test_merge_moves_links_and_consolidates_profile(db, auth_client):
    cid = auth_client.test_clinic.id
    primary, dup, conv, bk, pay = _make_pair(db, cid)
    pid, did = primary.id, dup.id
    conv_id, bk_id, pay_id = conv.id, bk.id, pay.id

    r = auth_client.post(
        "/api/customers/merge",
        json={"primary_id": pid, "duplicate_ids": [did]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["primary_id"] == pid
    assert body["merged"] == [did]

    db.expire_all()
    # every linked record now points at the surviving golden record
    assert db.get(models.Conversation, conv_id).customer_id == pid
    assert db.get(models.Booking, bk_id).customer_id == pid
    assert db.get(models.Payment, pay_id).customer_id == pid

    # the duplicate is tombstoned onto the primary
    merged = db.get(models.Customer, did)
    assert merged.merged_into_id == pid

    # profile consolidation: LTV summed, lead_score = max, best pipeline/temp won
    golden = db.get(models.Customer, pid)
    assert golden.ltv == 1500.0          # 1000 + 500
    assert golden.lead_score == 80       # max(30, 80)
    assert golden.pipeline_stage == "booked"  # higher rank than "interested"
    assert golden.temperature == "hot"        # hotter than "warm"
    assert golden.name == "Jane Doe"          # real name kept over placeholder

    # the merged duplicate disappears from the customer list; primary remains
    rows = auth_client.get("/api/customers").json()
    ids = {row["id"] for row in rows}
    assert pid in ids
    assert did not in ids


def test_merge_leaves_records_the_user_did_not_pick_alone(db, auth_client):
    """Sharing a phone does not prove it is the same person (a shop line, a family
    phone), so the merge modal lets the user tick a subset. Merging must touch only
    the ids sent — everything else in the group stays a live, separate customer."""
    cid = auth_client.test_clinic.id
    primary, dup, *_ = _make_pair(db, cid)
    branch, _svc = _branch_and_service(db, cid)
    other = models.Customer(
        clinic_id=cid, name="Somchai (different person)", phone="0812345678",
        channel="web", channel_user_id="web-somchai", branch_id=branch.id,
        pipeline_stage="new_lead", temperature="cold", lead_score=10, ltv=4800.0,
    )
    db.add(other)
    db.commit()
    pid, did, oid = primary.id, dup.id, other.id

    r = auth_client.post("/api/customers/merge",
                         json={"primary_id": pid, "duplicate_ids": [did]})
    assert r.status_code == 200, r.text
    assert r.json()["merged"] == [did]

    db.expire_all()
    untouched = db.get(models.Customer, oid)
    assert untouched.merged_into_id is None
    assert untouched.ltv == 4800.0                  # its LTV was NOT folded into the golden
    assert db.get(models.Customer, pid).ltv == 1500.0

    ids = {row["id"] for row in auth_client.get("/api/customers").json()}
    assert oid in ids and pid in ids and did not in ids
    # ...and it is still offered as a possible duplicate of the surviving golden record
    groups = auth_client.get("/api/customers/duplicates").json()["groups"]
    assert any({c["id"] for c in g["customers"]} == {pid, oid} for g in groups)


def test_handle_inbound_routes_merged_identity_to_golden(db, auth_client):
    cid = auth_client.test_clinic.id
    primary, dup, *_ = _make_pair(db, cid)
    pid, did = primary.id, dup.id
    dup_channel, dup_uid = dup.channel, dup.channel_user_id

    r = auth_client.post(
        "/api/customers/merge",
        json={"primary_id": pid, "duplicate_ids": [did]},
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    # a new message arriving on the merged-away LINE identity must route to the
    # golden record, not the tombstoned duplicate.
    conv = handle_inbound(
        db, clinic_id=cid, channel=dup_channel, channel_user_id=dup_uid,
        name="LINE User", text="hi again",
    )
    assert conv.customer_id == pid

    # the message was persisted on the golden record's conversation
    last = (db.query(models.Message)
            .filter_by(conversation_id=conv.id)
            .order_by(models.Message.id.desc()).first())
    assert last is not None and last.text == "hi again"


def test_merging_a_former_golden_record_repoints_its_stubs_so_no_chain_forms(db, auth_client):
    """A -> B (first merge), then B -> C (second). A must end up pointing at C directly:
    _resolve_golden walks chains, but every other reader only tests merged_into_id IS
    NULL, and purging the middle row would strand the outer stubs. A three-link chain
    (A -> B -> C) is the case covered here."""
    cid = auth_client.test_clinic.id
    a, b, c = (models.Customer(clinic_id=cid, name=n, phone="0899990000", channel="web",
                               channel_user_id=f"u-{n}") for n in ("A", "B", "C"))
    db.add_all([a, b, c])
    db.commit()
    r = auth_client.post("/api/customers/merge", json={"primary_id": b.id, "duplicate_ids": [a.id]})
    assert r.status_code == 200, r.text
    r = auth_client.post("/api/customers/merge", json={"primary_id": c.id, "duplicate_ids": [b.id]})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(models.Customer, b.id).merged_into_id == c.id
    assert db.get(models.Customer, a.id).merged_into_id == c.id, "flattened, not A -> B -> C"
    assert db.get(models.Customer, c.id).merged_into_id is None
