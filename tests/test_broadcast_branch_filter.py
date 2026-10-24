"""Broadcast campaigns can now target a specific subset of branches (the
Treatments-style checkbox multi-select in the campaign modal). A customer with
no branch_id is of UNKNOWN branch and stays excluded once a campaign narrows
to specific branches — the opposite convention from Service.branch_id, where
"no restriction" means "every branch"."""
from app import models


def _customer(db, cid, branch_id, name="Cust"):
    c = models.Customer(clinic_id=cid, name=name, channel="web",
                        channel_user_id=f"cu-{name}", branch_id=branch_id,
                        pipeline_stage="new_lead", temperature="warm")
    db.add(c)
    db.commit()
    return c


def _second_branch(db, clinic, name="Second Branch"):
    b = models.Branch(clinic_id=clinic.id, name=name)
    db.add(b)
    db.commit()
    return b


def test_preview_audience_filters_by_branch_ids(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)

    cust_b1 = _customer(db, clinic.id, b1.id, name="Ann")
    cust_b2 = _customer(db, clinic.id, b2.id, name="Bea")
    cust_none = _customer(db, clinic.id, None, name="Cara")

    r_b1 = auth_client.get(f"/api/campaigns/preview?branch_ids={b1.id}").json()
    names_b1 = {c["name"] for c in r_b1["customers"]}
    assert names_b1 == {"Ann"}

    r_all = auth_client.get("/api/campaigns/preview").json()
    names_all = {c["name"] for c in r_all["customers"]}
    assert names_all == {"Ann", "Bea", "Cara"}

    assert cust_b1 and cust_b2 and cust_none  # sanity: all three exist


def test_preview_audience_multiple_branch_ids(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic, "B2")
    b3 = _second_branch(db, clinic, "B3")
    _customer(db, clinic.id, b1.id, name="Ann")
    _customer(db, clinic.id, b2.id, name="Bea")
    _customer(db, clinic.id, b3.id, name="Cara")

    r = auth_client.get(f"/api/campaigns/preview?branch_ids={b1.id}&branch_ids={b2.id}").json()
    names = {c["name"] for c in r["customers"]}
    assert names == {"Ann", "Bea"}


def test_create_campaign_saves_branch_ids_and_send_respects_it(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)
    _customer(db, clinic.id, b1.id, name="Ann")
    _customer(db, clinic.id, b2.id, name="Bea")

    r = auth_client.post("/api/campaigns", json={
        "name": "Branch Only Promo", "channel": "all", "message": "hi",
        "audience": {"branch_ids": [b1.id]},
    })
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert r.json()["audience"]["branch_ids"] == [b1.id]

    aud = auth_client.get(f"/api/campaigns/{cid}/audience").json()
    assert {c["name"] for c in aud["customers"]} == {"Ann"}

    sent = auth_client.post(f"/api/campaigns/{cid}/send").json()
    assert sent["delivered"]["audience"] == 1
