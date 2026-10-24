"""Regression tests for the automatic no-show transition and series relabelling
— app/services/booking.py::sweep_no_shows + app/routers/bookings.py."""
from datetime import timedelta

from app import models
from app.services import booking
from app.services.booking import (NO_SHOW_GRACE_HOURS, available_slots,
                                  sweep_no_shows, _now_local)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _mk_booking(db, clinic, *, status="pending", hours_ago=NO_SHOW_GRACE_HOURS + 1):
    """A booking whose slot was ``hours_ago`` hours in the past (via the ORM —
    the POST route rightly rejects past slots)."""
    cust = models.Customer(clinic_id=clinic.id, name="Test Customer", channel="web")
    svc = models.Service(clinic_id=clinic.id, name="Test Laser",
                         category="laser", base_price=5000, active=True)
    db.add_all([cust, svc])
    db.flush()
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b = models.Booking(
        clinic_id=clinic.id, customer_id=cust.id, branch_id=branch.id,
        service_id=svc.id, slot_at=_now_local() - timedelta(hours=hours_ago),
        status=status, price=5000, deposit_required=1000, created_by="admin")
    db.add(b)
    db.commit()
    return b


def _activities(db, clinic, booking_id):
    return (db.query(models.Activity)
            .filter_by(clinic_id=clinic.id, ref_type="booking", ref_id=booking_id)
            .all())


# --------------------------------------------------------------------------
# sweep_no_shows — the helper itself
# --------------------------------------------------------------------------
def test_past_pending_becomes_no_show_with_activity(db, clinic):
    b = _mk_booking(db, clinic, status="pending", hours_ago=3)
    assert sweep_no_shows(db, clinic.id) == 1
    db.refresh(b)
    assert b.status == "no_show"
    acts = _activities(db, clinic, b.id)
    assert any("No-show" in a.summary for a in acts)


def test_grace_period_respected(db, clinic):
    """A pending booking past its slot but inside the grace window is untouched."""
    b = _mk_booking(db, clinic, status="pending", hours_ago=1)
    assert sweep_no_shows(db, clinic.id) == 0
    db.refresh(b)
    assert b.status == "pending"


def test_future_pending_untouched(db, clinic):
    b = _mk_booking(db, clinic, status="pending", hours_ago=-24)  # tomorrow
    assert sweep_no_shows(db, clinic.id) == 0
    db.refresh(b)
    assert b.status == "pending"


def test_non_pending_statuses_untouched(db, clinic):
    """Past confirmed bookings are staff's to close out manually — and
    completed/cancelled are terminal."""
    rows = {s: _mk_booking(db, clinic, status=s, hours_ago=48)
            for s in ("confirmed", "completed", "cancelled")}
    assert sweep_no_shows(db, clinic.id) == 0
    for s, b in rows.items():
        db.refresh(b)
        assert b.status == s


def test_sweep_is_clinic_scoped(db, clinic, make_clinic):
    other = make_clinic("Clinic B", slug="clinic-b")
    mine = _mk_booking(db, clinic, hours_ago=5)
    theirs = _mk_booking(db, other, hours_ago=5)
    assert sweep_no_shows(db, clinic.id) == 1
    db.refresh(mine)
    db.refresh(theirs)
    assert mine.status == "no_show"
    assert theirs.status == "pending"  # the other tenant is never touched


def test_sweep_idempotent(db, clinic):
    _mk_booking(db, clinic, hours_ago=3)
    assert sweep_no_shows(db, clinic.id) == 1
    assert sweep_no_shows(db, clinic.id) == 0  # second run: nothing left to flip


# --------------------------------------------------------------------------
# GET /api/bookings — lazy sweep keeps the list truthful
# --------------------------------------------------------------------------
def test_list_bookings_triggers_sweep(db, clinic, auth_client):
    b = _mk_booking(db, clinic, status="pending", hours_ago=3)
    r = auth_client.get("/api/bookings?status=pending")
    assert r.status_code == 200
    assert all(row["id"] != b.id for row in r.json())  # no longer pending
    db.expire_all()
    assert db.get(models.Booking, b.id).status == "no_show"
    r = auth_client.get("/api/bookings?status=no_show")
    assert [row["id"] for row in r.json()] == [b.id]


def test_run_automations_reports_no_shows(db, clinic):
    _mk_booking(db, clinic, hours_ago=4)
    from app.services.automations import run_automations
    result = run_automations(clinic_id=clinic.id)
    assert result["no_shows"] == 1
    db.expire_all()
    assert (db.query(models.Booking).filter_by(clinic_id=clinic.id).one()
            .status == "no_show")


# --------------------------------------------------------------------------
# POST /bookings — series labels re-normalised when a session is skipped
# --------------------------------------------------------------------------
def test_series_relabelled_after_skipped_session(db, clinic, auth_client, monkeypatch):
    from app.routers import bookings as bookings_router

    real = bookings_router._series_slot
    calls = {"n": 0}

    def fake(db_, branch_id, target, doctor_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None, True  # first follow-on: nothing free within 14 days → skipped
        return real(db_, branch_id, target, doctor_id)

    monkeypatch.setattr(bookings_router, "_series_slot", fake)

    cust = models.Customer(clinic_id=clinic.id, name="Series Customer", channel="web")
    svc = models.Service(clinic_id=clinic.id, name="Test Laser",
                         category="laser", base_price=5000, active=True)
    db.add_all([cust, svc])
    db.commit()
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    day = booking._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]

    r = auth_client.post("/api/bookings", json={
        "customer_id": cust.id, "service_id": svc.id, "branch_id": branch.id,
        "slot_at": slot.isoformat(), "bundle_sessions": 3, "bundle_interval_months": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["series_count"] == 2
    # labels reflect the CREATED count, not the requested 3
    assert body["notes"] == "ครั้งที่ 1/2"
    rows = (db.query(models.Booking).filter_by(clinic_id=clinic.id)
            .order_by(models.Booking.slot_at).all())
    assert [b.notes for b in rows] == ["ครั้งที่ 1/2", "ครั้งที่ 2/2"]
