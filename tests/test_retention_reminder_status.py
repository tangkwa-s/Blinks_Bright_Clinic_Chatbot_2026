"""Locks in the ``Reminder.status`` vocabulary the retention page's status
filter depends on. An unsent reminder is stored (and queried by
``process_due``) with status ``scheduled`` — never ``pending`` — so the
frontend's "รอส่ง" (pending) filter option must send/compare against
``scheduled``, not the string ``pending``. This regression test guards the
``GET /api/retention/reminders?status=`` contract the frontend relies on.
"""
from datetime import timedelta

from app import models
from app.services.booking import _now_local


def _make_customer(db, clinic, name="Fah", uid="status-u1"):
    c = models.Customer(clinic_id=clinic.id, name=name, channel="web",
                        channel_user_id=uid, pipeline_stage="new_lead",
                        temperature="warm", lead_score=20)
    db.add(c)
    db.commit()
    return c


def _make_reminder(db, clinic, cust, status):
    r = models.Reminder(
        clinic_id=clinic.id, customer_id=cust.id, type="winback",
        channel="web", title="We miss you", body="กลับมาดูแลผิวกันไหมคะ",
        due_at=_now_local() + timedelta(days=1), status=status)
    db.add(r)
    db.commit()
    return r


def test_unsent_reminder_is_stored_as_scheduled_not_pending(db, clinic):
    """The value the frontend's filter must use for the "pending" bucket."""
    cust = _make_customer(db, clinic)
    r = _make_reminder(db, clinic, cust, status="scheduled")

    db.refresh(r)
    assert r.status == "scheduled"


def test_reminders_endpoint_filters_by_scheduled_status(auth_client, db, clinic):
    cust = _make_customer(db, clinic)
    _make_reminder(db, clinic, cust, status="scheduled")
    _make_reminder(db, clinic, cust, status="sent")
    _make_reminder(db, clinic, cust, status="failed")

    r = auth_client.get("/api/retention/reminders?status=scheduled")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "scheduled"

    # "pending" is not a value ever written to the DB — filtering by it must
    # yield nothing, which is exactly the bug this test guards against the
    # frontend reintroducing.
    r2 = auth_client.get("/api/retention/reminders?status=pending")
    assert r2.json() == []

    r3 = auth_client.get("/api/retention/reminders?status=sent")
    assert len(r3.json()) == 1
    assert r3.json()[0]["status"] == "sent"
