"""Regression tests for app/services/booking.py — branch/promo pricing,
deposit math, and slot availability (past + taken slots excluded)."""
from datetime import timedelta

from app import models
from app.services import booking
from app.services.booking import resolved_price, create_booking


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _branch(db, clinic):
    return db.query(models.Branch).filter_by(clinic_id=clinic.id).first()


def _mk_service(db, clinic, base_price):
    s = models.Service(clinic_id=clinic.id, name="Test Laser",
                        category="laser", base_price=base_price, active=True)
    db.add(s)
    db.commit()
    return s


def _set_branch_price(db, clinic, service, branch, price):
    sp = models.ServicePrice(clinic_id=clinic.id, service_id=service.id,
                             branch_id=branch.id, price=price)
    db.add(sp)
    db.commit()
    return sp


def _mk_promo(db, clinic, service, promo_price, *, valid_from_days, valid_to_days,
              branch=None, active=True):
    now = booking._now_local()
    p = models.Promotion(
        clinic_id=clinic.id, title="Promo", service_id=service.id,
        branch_id=branch.id if branch else None,
        promo_price=promo_price, active=active,
        valid_from=now + timedelta(days=valid_from_days),
        valid_to=now + timedelta(days=valid_to_days),
    )
    db.add(p)
    db.commit()
    return p


def _mk_customer(db, clinic):
    c = models.Customer(clinic_id=clinic.id, name="Test Customer", channel="web")
    db.add(c)
    db.commit()
    return c


# --------------------------------------------------------------------------
# resolved_price
# --------------------------------------------------------------------------
def test_resolved_price_uses_branch_price_not_base(db, clinic):
    branch = _branch(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)

    # With no per-branch price, it falls back to the catalog base.
    assert resolved_price(db, clinic.id, svc, branch.id) == 10000.0

    # A branch-specific ServicePrice overrides the base entirely.
    _set_branch_price(db, clinic, svc, branch, price=8000)
    assert resolved_price(db, clinic.id, svc, branch.id) == 8000.0


def test_resolved_price_active_promo_wins(db, clinic):
    branch = _branch(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8000)

    # Active, in-date promotion cheaper than the branch price wins.
    _mk_promo(db, clinic, svc, promo_price=6000,
              valid_from_days=-5, valid_to_days=+5)
    assert resolved_price(db, clinic.id, svc, branch.id) == 6000.0


def test_resolved_price_ignores_more_expensive_promo(db, clinic):
    branch = _branch(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8000)

    # A promo priced ABOVE the branch price never raises the price.
    _mk_promo(db, clinic, svc, promo_price=9000,
              valid_from_days=-5, valid_to_days=+5)
    assert resolved_price(db, clinic.id, svc, branch.id) == 8000.0


def test_resolved_price_ignores_expired_promo(db, clinic):
    branch = _branch(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8000)

    promo = _mk_promo(db, clinic, svc, promo_price=6000,
                      valid_from_days=-5, valid_to_days=+5)
    assert resolved_price(db, clinic.id, svc, branch.id) == 6000.0

    # Push valid_to into the past → the promo is ignored, branch price returns.
    promo.valid_to = booking._now_local() - timedelta(days=1)
    db.commit()
    assert resolved_price(db, clinic.id, svc, branch.id) == 8000.0


def test_resolved_price_ignores_inactive_promo(db, clinic):
    branch = _branch(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8000)

    _mk_promo(db, clinic, svc, promo_price=6000,
              valid_from_days=-5, valid_to_days=+5, active=False)
    assert resolved_price(db, clinic.id, svc, branch.id) == 8000.0


# --------------------------------------------------------------------------
# create_booking — deposit follows the resolved (branch/promo) price
# --------------------------------------------------------------------------
def test_create_booking_deposit_follows_branch_price(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8800)

    resolved = resolved_price(db, clinic.id, svc, branch.id)
    assert resolved == 8800.0  # branch price, not base 10000

    slot = booking._now_local() + timedelta(days=2)
    bk = create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                        slot_at=slot)
    db.commit()

    assert bk.price == resolved
    # deposit = 20% rounded to the nearest 100 (8800*0.2 = 1760 -> 1800)
    assert bk.deposit_required == round(resolved * 0.2 / 100) * 100
    assert bk.deposit_required == 1800.0


def test_create_booking_deposit_follows_promo_price(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8000)
    _mk_promo(db, clinic, svc, promo_price=6000,
              valid_from_days=-5, valid_to_days=+5)

    resolved = resolved_price(db, clinic.id, svc, branch.id)
    assert resolved == 6000.0  # promo price, not base/branch

    slot = booking._now_local() + timedelta(days=2)
    bk = create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                        slot_at=slot)
    db.commit()

    assert bk.price == 6000.0
    # 6000*0.2 = 1200 -> 1200
    assert bk.deposit_required == round(6000 * 0.2 / 100) * 100 == 1200.0


# --------------------------------------------------------------------------
# available_slots — exclude past times + already-booked slots
# --------------------------------------------------------------------------
def test_available_slots_excludes_past_days(db, clinic):
    branch = _branch(db, clinic)
    # An entirely-past day offers nothing.
    yesterday = booking._now_local() - timedelta(days=1)
    assert booking.available_slots(db, branch.id, yesterday) == []


def test_available_slots_excludes_past_times_today(db, clinic):
    branch = _branch(db, clinic)
    now = booking._now_local()
    todays = booking.available_slots(db, branch.id, booking._now_local())
    # Every offered slot is strictly in the future.
    assert all(s > now for s in todays)


def test_available_slots_future_day_is_populated(db, clinic):
    branch = _branch(db, clinic)
    day = booking._now_local() + timedelta(days=3)
    slots = booking.available_slots(db, branch.id, day)
    # Derived from the branch's window for THAT weekday, not hard-coded: the seeded
    # branch shuts an hour earlier at weekends, so "20 slots" quietly became wrong on
    # whatever date the suite happened to run three days before a Saturday.
    open_min, close_min = booking._day_window(branch, day)
    assert len(slots) == (close_min - open_min) // booking.SLOT_MINUTES
    assert all(s > booking._now_local() for s in slots)


def test_available_slots_excludes_booked_slot(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=5000)
    _set_branch_price(db, clinic, svc, branch, price=5000)

    day = booking._now_local() + timedelta(days=3)
    before = booking.available_slots(db, branch.id, day)
    assert before, "future day should have open slots"

    target = before[0]
    create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                   slot_at=target)
    db.commit()

    after = booking.available_slots(db, branch.id, day)
    assert target not in after
    # A booking occupies its treatment's whole DURATION, not just the minute it starts:
    # a 60-minute treatment takes two 30-minute slots off the board. Blocking only the
    # start let a second treatment be booked into the middle of the first.
    blocked = -(-svc.duration_min // booking.SLOT_MINUTES)
    assert len(after) == len(before) - blocked
    assert target + timedelta(minutes=booking.SLOT_MINUTES) not in after


def test_available_slots_confirmed_booking_also_blocks(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=5000)

    day = booking._now_local() + timedelta(days=4)
    before = booking.available_slots(db, branch.id, day)
    target = before[1]

    bk = models.Booking(clinic_id=clinic.id, customer_id=cust.id,
                        branch_id=branch.id, service_id=svc.id,
                        slot_at=target, status="confirmed")
    db.add(bk)
    db.commit()

    after = booking.available_slots(db, branch.id, day)
    assert target not in after
    assert len(after) == len(before) - -(-svc.duration_min // booking.SLOT_MINUTES)
