"""GET /api/analytics — the "funnel drop-off" widget must never show a stage
retaining MORE than 100% of the previous one. Customer.pipeline_stage is a
single current position (not cumulative), so the naive
"count at stage B / count at stage A" ratio compares two unrelated
snapshot populations and can read e.g. 400% when more customers currently sit
at a later stage than are stuck at an earlier one. The funnel must roll counts
forward cumulatively (how many reached AT LEAST each stage) before dividing —
same fix already applied to app/routers/dashboard.py's lead funnel."""
from app import models


def _customer(db, cid, stage, name):
    c = models.Customer(clinic_id=cid, name=name, channel="web",
                        channel_user_id=f"cu-{name}", pipeline_stage=stage)
    db.add(c)
    db.commit()
    return c


def test_funnel_drop_off_never_exceeds_100_percent(auth_client, db):
    clinic = auth_client.test_clinic
    # Reproduces the reported bug's exact shape: more customers currently sit
    # at a LATER stage than are stuck at an earlier one.
    _customer(db, clinic.id, "new_lead", "Lead1")
    for i in range(4):
        _customer(db, clinic.id, "interested", f"Interested{i}")
    for i in range(16):
        _customer(db, clinic.id, "booked", f"Booked{i}")
    _customer(db, clinic.id, "paid", "Paid1")

    r = auth_client.get("/api/analytics")
    assert r.status_code == 200, r.text
    body = r.json()

    for step in body["drop_off"]:
        assert 0 <= step["kept_pct"] <= 100, step

    by_pair = {(s["from"], s["to"]): s["kept_pct"] for s in body["drop_off"]}
    # Cumulative: new_lead=1+4+16+1=22, interested=4+16+1=21, booked=16+1=17, paid=1
    assert by_pair[("new_lead", "interested")] == round(21 / 22 * 100, 1)
    assert by_pair[("interested", "booked")] == round(17 / 21 * 100, 1)
    assert by_pair[("booked", "paid")] == round(1 / 17 * 100, 1)

    assert body["funnel"] == {"new_lead": 22, "interested": 21, "booked": 17, "paid": 1}


def test_funnel_folds_followup_into_paid(auth_client, db):
    clinic = auth_client.test_clinic
    _customer(db, clinic.id, "paid", "PaidCust")
    _customer(db, clinic.id, "followup", "FollowupCust")

    r = auth_client.get("/api/analytics")
    assert r.status_code == 200, r.text
    assert r.json()["funnel"]["paid"] == 2
