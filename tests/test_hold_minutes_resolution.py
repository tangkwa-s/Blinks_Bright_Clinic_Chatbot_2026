"""Regression tests for app/services/booking.py::resolved_hold_minutes.

A realistic example: a simple treatment can reasonably hold its slot for the
system default, but a surgical procedure with a more involved payment step might need
longer. Resolution order is service override -> clinic override -> the .env HOLD_MINUTES
default, mirroring deposit_for's existing "0 = unset, fall through" sentinel convention
(see tests/test_deposit.py).
"""
from datetime import timedelta

from app import models
from app.services import booking as bk
from app.services.booking import HOLD_MINUTES, MAX_HOLD_MINUTES, resolved_hold_minutes


def _service(clinic_id, hold_minutes=0):
    svc = models.Service(clinic_id=clinic_id, name="Surgery", category="Surgical",
                         base_price=50000.0, hold_minutes=hold_minutes, active=True)
    return svc


def test_no_override_anywhere_uses_the_global_default(db, clinic):
    svc = _service(clinic.id, hold_minutes=0)
    db.add(svc)
    db.commit()
    assert resolved_hold_minutes(db, clinic.id, svc) == HOLD_MINUTES


def test_clinic_override_wins_when_the_service_has_none(db, clinic):
    clinic.hold_minutes = 15
    db.commit()
    svc = _service(clinic.id, hold_minutes=0)
    db.add(svc)
    db.commit()
    assert resolved_hold_minutes(db, clinic.id, svc) == 15


def test_service_override_wins_over_the_clinic_setting(db, clinic):
    """A realistic scenario: general treatments use the clinic's number, but
    THIS surgical procedure needs its own, longer one."""
    clinic.hold_minutes = 15
    db.commit()
    svc = _service(clinic.id, hold_minutes=20)
    db.add(svc)
    db.commit()
    assert resolved_hold_minutes(db, clinic.id, svc) == 20


def test_service_override_wins_even_with_no_clinic_override(db, clinic):
    svc = _service(clinic.id, hold_minutes=20)
    db.add(svc)
    db.commit()
    assert resolved_hold_minutes(db, clinic.id, svc) == 20


def test_a_clinic_with_no_id_falls_back_to_the_global_default(db, clinic):
    """Defensive: resolved_hold_minutes must not crash if clinic_id is falsy."""
    svc = _service(clinic.id, hold_minutes=0)
    db.add(svc)
    db.commit()
    assert resolved_hold_minutes(db, None, svc) == HOLD_MINUTES


def test_create_booking_stores_the_resolved_number(db, clinic):
    """End-to-end: a booking made with a custom hold_minutes carries that SAME
    number on its own row (the audit copy _hold_expired_result and
    notify_hold_expired read later), and hold_expires_at matches it."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _service(clinic.id, hold_minutes=20)
    db.add(svc)
    db.commit()
    cust = models.Customer(clinic_id=clinic.id, name="คุณทดสอบ", channel="web",
                           branch_id=branch.id)
    db.add(cust)
    db.commit()

    resolved = resolved_hold_minutes(db, clinic.id, svc)
    before = bk._now_local()
    booking = bk.create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                                slot_at=before + timedelta(days=1),
                                created_by="ai", hold_minutes=resolved)
    db.commit()

    assert resolved == 20
    assert booking.hold_minutes == 20
    # hold_expires_at is NOW + hold_minutes (the payment deadline), not tied to slot_at
    # (when the appointment itself happens) — give a wide tolerance since this test
    # doesn't freeze the clock.
    assert booking.hold_expires_at is not None
    delta = (booking.hold_expires_at - before).total_seconds() / 60
    assert 19 <= delta <= 21


def test_a_hold_minutes_above_zero_but_price_zero_stores_no_hold(db, clinic):
    """Mirrors create_booking's own existing rule: a free treatment is never held,
    so the audit column must stay 0 (matching hold_expires_at staying None), not the
    resolved number that was passed in but never actually used."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Free Consult", category="Consult",
                         base_price=0.0, hold_minutes=20, active=True)
    db.add(svc)
    db.commit()
    cust = models.Customer(clinic_id=clinic.id, name="คุณทดสอบ", channel="web",
                           branch_id=branch.id)
    db.add(cust)
    db.commit()

    resolved = resolved_hold_minutes(db, clinic.id, svc)
    booking = bk.create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                                slot_at=bk._now_local(), created_by="ai",
                                hold_minutes=resolved)
    db.commit()

    assert booking.hold_expires_at is None
    assert booking.hold_minutes == 0


def test_max_hold_minutes_is_a_sane_ceiling():
    """Sanity check on the constant itself — generous relative to a
    typical ceiling (15-20 min for surgical cases), well under a full day."""
    assert 0 < MAX_HOLD_MINUTES < 24 * 60
