"""Regression tests for doctor-aware availability, reschedule validation and
course/bundle series — app/services/booking.py + app/routers/bookings.py."""
from datetime import datetime, timedelta

from app import models
from app.services import booking
from app.services.booking import _add_months, available_slots, create_booking


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _branch(db, clinic):
    return db.query(models.Branch).filter_by(clinic_id=clinic.id).first()


def _mk_branch(db, clinic, name="Second Branch"):
    b = models.Branch(clinic_id=clinic.id, name=name, open_hour=10, close_hour=20)
    db.add(b)
    db.commit()
    return b


def _mk_doctor(db, clinic, name="Dr. Test"):
    m = models.StaffMember(clinic_id=clinic.id, name=name, role="doctor", active=True)
    db.add(m)
    db.commit()
    return m


def _mk_customer(db, clinic, name="Test Customer"):
    c = models.Customer(clinic_id=clinic.id, name=name, channel="web")
    db.add(c)
    db.commit()
    return c


def _mk_service(db, clinic, base_price=5000):
    s = models.Service(clinic_id=clinic.id, name="Test Laser",
                       category="laser", base_price=base_price, active=True)
    db.add(s)
    db.commit()
    return s


# --------------------------------------------------------------------------
# _add_months — calendar-aware with day clamping
# --------------------------------------------------------------------------
def test_add_months_clamps_month_end():
    jan31 = datetime(2026, 1, 31, 14, 0)
    assert _add_months(jan31, 1) == datetime(2026, 2, 28, 14, 0)   # 2026 not a leap year
    assert _add_months(jan31, 2) == datetime(2026, 3, 31, 14, 0)
    assert _add_months(datetime(2026, 11, 15, 10, 0), 3) == datetime(2027, 2, 15, 10, 0)


# --------------------------------------------------------------------------
# available_slots — doctor dimension + exclude_booking_id
# --------------------------------------------------------------------------
def test_doctor_busy_at_other_branch_blocks_slot(db, clinic):
    branch_a, branch_b = _branch(db, clinic), _mk_branch(db, clinic)
    doc, other = _mk_doctor(db, clinic), _mk_doctor(db, clinic, "Dr. Other")
    cust, svc = _mk_customer(db, clinic), _mk_service(db, clinic)

    day = booking._now_local() + timedelta(days=3)
    target = available_slots(db, branch_a.id, day)[0]
    create_booking(db, customer=cust, service=svc, branch_id=branch_a.id,
                   slot_at=target, doctor_id=doc.id)
    db.commit()

    # branch B itself is free at that time...
    assert target in available_slots(db, branch_b.id, day)
    # ...and stays free for another doctor...
    assert target in available_slots(db, branch_b.id, day, doctor_id=other.id)
    # ...but the busy doctor cannot be double-booked across branches.
    assert target not in available_slots(db, branch_b.id, day, doctor_id=doc.id)


def test_exclude_booking_id_frees_own_slot(db, clinic):
    branch = _branch(db, clinic)
    cust, svc = _mk_customer(db, clinic), _mk_service(db, clinic)

    day = booking._now_local() + timedelta(days=3)
    target = available_slots(db, branch.id, day)[0]
    bk = create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                        slot_at=target)
    db.commit()

    assert target not in available_slots(db, branch.id, day)
    # excluded, a reschedule can keep/reuse its own slot on the same day
    assert target in available_slots(db, branch.id, day, exclude_booking_id=bk.id)


# --------------------------------------------------------------------------
# POST /bookings — slot + doctor validation, course series
# --------------------------------------------------------------------------
def _post_payload(db, clinic, **extra):
    branch = _branch(db, clinic)
    cust, svc = _mk_customer(db, clinic), _mk_service(db, clinic)
    day = booking._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    return {"customer_id": cust.id, "service_id": svc.id, "branch_id": branch.id,
            "slot_at": slot.isoformat(), **extra}


def test_post_bookings_rejects_taken_and_past_slots(db, clinic, auth_client):
    payload = _post_payload(db, clinic)
    r = auth_client.post("/api/bookings", json=payload)
    assert r.status_code == 200, r.text

    # same slot again → branch capacity conflict
    r2 = auth_client.post("/api/bookings", json=payload)
    assert r2.status_code == 409

    # a past slot is never bookable
    past = (booking._now_local() - timedelta(days=1)).replace(hour=12, minute=0,
                                                              second=0, microsecond=0)
    r3 = auth_client.post("/api/bookings", json={**payload, "slot_at": past.isoformat()})
    assert r3.status_code == 409


def test_post_bookings_rejects_doctor_double_booking(db, clinic, auth_client):
    branch_b = _mk_branch(db, clinic)
    doc = _mk_doctor(db, clinic)
    payload = _post_payload(db, clinic, doctor_id=doc.id)
    r = auth_client.post("/api/bookings", json=payload)
    assert r.status_code == 200, r.text

    # same doctor, same time, another branch → 409; no doctor → the slot is fine
    other = {**payload, "branch_id": branch_b.id}
    assert auth_client.post("/api/bookings", json=other).status_code == 409
    other.pop("doctor_id")
    assert auth_client.post("/api/bookings", json=other).status_code == 200


def test_post_bookings_unknown_doctor_404(db, clinic, auth_client):
    payload = _post_payload(db, clinic, doctor_id=99999)
    assert auth_client.post("/api/bookings", json=payload).status_code == 404


def test_post_bookings_bundle_series(db, clinic, auth_client):
    payload = _post_payload(db, clinic, bundle_sessions=3, bundle_interval_months=2)
    r = auth_client.post("/api/bookings", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["series_count"] == 3
    assert r.json()["notes"] == "ครั้งที่ 1/3"

    first = datetime.fromisoformat(payload["slot_at"])
    rows = (db.query(models.Booking).filter_by(clinic_id=clinic.id)
            .order_by(models.Booking.slot_at).all())
    assert len(rows) == 3
    for i, b in enumerate(rows):
        assert b.slot_at == _add_months(first, i * 2)
        assert b.notes == f"ครั้งที่ {i + 1}/3"
        assert b.status == "pending"


def test_post_bookings_bundle_sessions_clamped(db, clinic, auth_client):
    payload = _post_payload(db, clinic, bundle_sessions=99)
    r = auth_client.post("/api/bookings", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["series_count"] == 12  # clamped to the 12-session cap


# --------------------------------------------------------------------------
# PATCH /bookings/{bid} — reschedule validation
# --------------------------------------------------------------------------
def test_patch_reschedule_validates_slot(db, clinic, auth_client):
    payload = _post_payload(db, clinic)
    bid = auth_client.post("/api/bookings", json=payload).json()["id"]

    # malformed ISO is a hard 400, not silently ignored
    r = auth_client.patch(f"/api/bookings/{bid}", json={"slot_at": "not-a-date"})
    assert r.status_code == 400

    # a past slot is rejected
    past = (booking._now_local() - timedelta(days=1)).replace(hour=12, minute=0,
                                                              second=0, microsecond=0)
    r = auth_client.patch(f"/api/bookings/{bid}", json={"slot_at": past.isoformat()})
    assert r.status_code == 409

    # a slot taken by ANOTHER booking is rejected
    branch = _branch(db, clinic)
    day = booking._now_local() + timedelta(days=4)
    taken = available_slots(db, branch.id, day)[0]
    other = _post_payload(db, clinic)
    other["slot_at"] = taken.isoformat()
    assert auth_client.post("/api/bookings", json=other).status_code == 200
    r = auth_client.patch(f"/api/bookings/{bid}", json={"slot_at": taken.isoformat()})
    assert r.status_code == 409

    # a genuinely free slot works and the move is persisted
    free = available_slots(db, branch.id, day)[0]
    r = auth_client.patch(f"/api/bookings/{bid}", json={"slot_at": free.isoformat()})
    assert r.status_code == 200
    assert r.json()["slot_at"] == free.isoformat()


def test_patch_same_day_move_allowed(db, clinic, auth_client):
    """A booking can move within its own day — its own slot never blocks it."""
    payload = _post_payload(db, clinic)
    r = auth_client.post("/api/bookings", json=payload)
    bid = r.json()["id"]
    branch = _branch(db, clinic)
    day = datetime.fromisoformat(payload["slot_at"])
    new_slot = available_slots(db, branch.id, day)[0]
    r = auth_client.patch(f"/api/bookings/{bid}", json={"slot_at": new_slot.isoformat()})
    assert r.status_code == 200
    assert r.json()["slot_at"] == new_slot.isoformat()


def test_patch_doctor_change_conflict(db, clinic, auth_client):
    branch_b = _mk_branch(db, clinic)
    doc = _mk_doctor(db, clinic)
    p1 = _post_payload(db, clinic, doctor_id=doc.id)
    assert auth_client.post("/api/bookings", json=p1).status_code == 200

    # booking 2 at ANOTHER branch, same time, no doctor — fine
    p2 = _post_payload(db, clinic)
    p2["branch_id"] = branch_b.id
    p2["slot_at"] = p1["slot_at"]
    r = auth_client.post("/api/bookings", json=p2)
    assert r.status_code == 200, r.text
    bid2 = r.json()["id"]

    # assigning the busy doctor (slot unchanged) → 409 doctor conflict
    r = auth_client.patch(f"/api/bookings/{bid2}", json={"doctor_id": doc.id})
    assert r.status_code == 409

    # a doctor who is free at that time is fine
    other = _mk_doctor(db, clinic, "Dr. Free")
    r = auth_client.patch(f"/api/bookings/{bid2}", json={"doctor_id": other.id})
    assert r.status_code == 200
    assert r.json()["doctor_id"] == other.id
