"""Broadcast campaigns can now be edited (PATCH) and deleted (DELETE) — but
only while still draft/scheduled. A "sent" campaign is the actual delivery
record, so both routes refuse it (edit via "reuse" — a new campaign —
instead)."""
from app import models


def _make_campaign(db, clinic, **kw):
    defaults = dict(clinic_id=clinic.id, name="Draft Promo", audience={},
                    channel="all", message="hi", status="draft")
    defaults.update(kw)
    camp = models.Campaign(**defaults)
    db.add(camp)
    db.commit()
    return camp


def test_patch_updates_draft_campaign(auth_client, db):
    clinic = auth_client.test_clinic
    camp = _make_campaign(db, clinic)

    r = auth_client.patch(f"/api/campaigns/{camp.id}", json={
        "name": "Renamed Promo", "channel": "line", "message": "new text",
        "scheduled_at": "", "audience": {"stage": "interested"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed Promo"
    assert body["channel"] == "line"
    assert body["message"] == "new text"
    assert body["audience"]["stage"] == "interested"

    db.expire_all()
    row = db.get(models.Campaign, camp.id)
    assert row.name == "Renamed Promo"
    assert row.status == "draft"


def test_patch_sets_scheduled_status_from_future_datetime(auth_client, db):
    clinic = auth_client.test_clinic
    camp = _make_campaign(db, clinic)

    r = auth_client.patch(f"/api/campaigns/{camp.id}", json={
        "name": camp.name, "channel": "all", "message": "hi",
        "scheduled_at": "2099-01-01T10:00", "audience": {},
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "scheduled"


def test_patch_refuses_sent_campaign(auth_client, db):
    clinic = auth_client.test_clinic
    camp = _make_campaign(db, clinic, status="sent")

    r = auth_client.patch(f"/api/campaigns/{camp.id}", json={
        "name": "Should not apply", "channel": "all", "message": "hi", "audience": {},
    })
    assert r.status_code == 400, r.text
    db.expire_all()
    assert db.get(models.Campaign, camp.id).name == "Draft Promo"


def test_delete_removes_draft_campaign_and_its_activity_log(auth_client, db):
    clinic = auth_client.test_clinic
    camp = _make_campaign(db, clinic)
    camp_id = camp.id
    cust = models.Customer(clinic_id=clinic.id, name="Log Cust", channel="web")
    db.add(cust)
    db.flush()
    db.add(models.Activity(clinic_id=clinic.id, customer_id=cust.id, type="campaign",
                           summary="Log Cust · web · delivered",
                           ref_type="campaign", ref_id=camp_id))
    db.commit()

    r = auth_client.delete(f"/api/campaigns/{camp_id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    db.expire_all()
    assert db.get(models.Campaign, camp_id) is None
    assert (db.query(models.Activity)
            .filter_by(ref_type="campaign", ref_id=camp_id).count() == 0)


def test_delete_refuses_sent_campaign(auth_client, db):
    clinic = auth_client.test_clinic
    camp = _make_campaign(db, clinic, status="sent")

    r = auth_client.delete(f"/api/campaigns/{camp.id}")
    assert r.status_code == 400, r.text
    db.expire_all()
    assert db.get(models.Campaign, camp.id) is not None
