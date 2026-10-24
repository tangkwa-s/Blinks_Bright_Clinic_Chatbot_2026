"""Money must never buy back a slot somebody else has taken, and must never vanish.

A hold gives the customer HOLD_MINUTES (10) to pay. Payment can still land after that —
Stripe's checkout floor is ~31 minutes, so the link always outlives the hold; a slow
bank app, a link opened late, a webhook retried. ``mark_paid`` used to flip any pending
booking straight to confirmed, which after a lapse would silently double-book whoever had
taken the released slot in the meantime. The decision now keys off the HOLD DEADLINE, not
the status, because the sweep may not have run yet: the row can still read 'pending' at a
moment when day_availability has already given the slot away.
"""
import threading
from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest

from app import models
from app.database import SessionLocal
from app.services import booking as bk
from app.services import billing as sp
from app.services.booking import (EXPIRED, HOLD_MINUTES, SLOT_TAKEN, available_slots,
                                  claim_slot, create_booking, sweep_expired_holds)


@pytest.fixture
def clock(monkeypatch):
    """See tests/test_booking_hold.py — the same four modules hold their own reference."""
    from app.ai import tools as T
    from app.routers import bookings as R
    from app.services import automations as A

    cell = {"now": bk._now_local()}
    for mod in (bk, T, R, A):
        monkeypatch.setattr(mod, "_now_local", lambda: cell["now"])
    return SimpleNamespace(
        now=lambda: cell["now"],
        advance=lambda minutes: cell.update(now=cell["now"] + timedelta(minutes=minutes)))


def _held(db, clinic, clock, *, days_ahead=3):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Skin Booster", category="facial",
                         base_price=9500, duration_min=40, active=True)
    cust = models.Customer(clinic_id=clinic.id, name="มิ้นท์", phone="0955555555",
                           channel="web", branch_id=branch.id)
    db.add_all([svc, cust])
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=days_ahead))[0]
    b = create_booking(db, customer=cust, service=svc, branch_id=branch.id, slot_at=slot,
                       conversation_id=conv.id, created_by="ai",
                       hold_minutes=HOLD_MINUTES)
    db.commit()
    return SimpleNamespace(branch=branch, svc=svc, cust=cust, conv=conv, slot=slot, b=b)


def _take_the_slot(db, clinic, s):
    other = models.Customer(clinic_id=clinic.id, name="ฟ้า", channel="web")
    db.add(other)
    db.commit()
    taken = create_booking(db, customer=other, service=s.svc, branch_id=s.branch.id,
                           slot_at=s.slot, created_by="admin")
    db.commit()
    return taken


def _summaries(db, clinic, booking_id):
    return [a.summary for a in db.query(models.Activity)
            .filter_by(clinic_id=clinic.id, ref_type="booking", ref_id=booking_id).all()]


def _texts(db, conv):
    return [m.text for m in db.query(models.Message)
            .filter_by(conversation_id=conv.id).order_by(models.Message.id).all()]


# --------------------------------------------------------------------------
# confirm_paid_booking, through mark_paid
# --------------------------------------------------------------------------
def test_payment_before_the_deadline_confirms_and_clears_the_hold(db, clinic, clock):
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(HOLD_MINUTES - 5)
    assert sp.mark_paid(db, payment) is True
    db.refresh(s.b)
    assert s.b.status == "confirmed" and s.b.hold_expires_at is None


def test_payment_after_expiry_reinstates_a_still_free_slot(db, clinic, clock):
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(HOLD_MINUTES + 5)
    sweep_expired_holds(db, clinic.id)
    sp.mark_paid(db, payment)
    db.refresh(s.b)
    assert s.b.status == "confirmed" and s.b.hold_expires_at is None
    assert any("Reinstated after payment" in x for x in _summaries(db, clinic, s.b.id))
    assert any("ยืนยันคิวเดิมให้เรียบร้อยแล้ว" in t for t in _texts(db, s.conv)), (
        "they were already told the slot went — a plain 'confirmed' would contradict it")


def test_payment_after_expiry_does_not_steal_a_slot_someone_else_took(db, clinic, clock):
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(HOLD_MINUTES + 5)
    sweep_expired_holds(db, clinic.id)
    taken = _take_the_slot(db, clinic, s)

    sp.mark_paid(db, payment)
    db.refresh(s.b)
    db.refresh(taken)
    assert s.b.status == EXPIRED, "money does not buy back a taken slot"
    assert taken.status == "pending", "the other customer's booking is untouched"
    assert any("PAID AFTER HOLD EXPIRED" in x for x in _summaries(db, clinic, s.b.id))
    db.refresh(s.conv)
    assert s.conv.escalation_reason, "a person has to handle this one"


def test_the_customer_is_told_the_truth_when_the_slot_is_gone(db, clinic, clock):
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(HOLD_MINUTES + 5)
    sweep_expired_holds(db, clinic.id)
    _take_the_slot(db, clinic, s)
    sp.mark_paid(db, payment)
    texts = _texts(db, s.conv)
    assert any("เงินของคุณยังอยู่กับทางคลินิก" in t for t in texts)
    assert any("ทีมงานจะติดต่อกลับ" in t for t in texts)
    assert not any("การจองของคุณได้รับการยืนยันแล้ว" in t for t in texts), (
        "never tell someone an appointment they no longer have is confirmed")


def test_a_slot_that_has_simply_gone_past_is_not_reinstated(db, clinic, clock):
    """Same answer for the customer: they paid for an appointment that already happened."""
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(60 * 24 * 4)          # past the slot itself
    sp.mark_paid(db, payment)
    db.refresh(s.b)
    assert s.b.status == EXPIRED


def test_reinstating_puts_the_cancelled_reminders_back(db, clinic, clock):
    """The sweep cancelled them, and _has_booking_reminder counts cancelled rows — so
    without this a reinstated appointment would never remind anybody."""
    s = _held(db, clinic, clock)
    rem = models.Reminder(clinic_id=clinic.id, customer_id=s.cust.id,
                          type="pre_appointment", channel="web", title="นัดพรุ่งนี้",
                          due_at=s.slot - timedelta(hours=24), status="scheduled",
                          booking_id=s.b.id)
    db.add(rem)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(HOLD_MINUTES + 5)
    sweep_expired_holds(db, clinic.id)
    db.refresh(rem)
    assert rem.status == "cancelled"
    sp.mark_paid(db, payment)
    db.refresh(rem)
    assert rem.status == "scheduled"


def test_a_cancelled_booking_is_never_resurrected_by_a_payment(db, clinic, clock):
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    s.b.status = "cancelled"
    db.commit()
    sp.mark_paid(db, payment)
    db.refresh(s.b)
    assert s.b.status == "cancelled"


# --------------------------------------------------------------------------
# a late payment races a brand new booking for the SAME slot
# --------------------------------------------------------------------------
# Once a hold has lapsed its slot is open to anyone, so a late payment (this file) and a
# new booking (test_slot_race.py) can both try to take it — the exact TOCTOU claim_slot
# already closes for two NEW bookings, now open on this second path into the same slot.
#
# The already-committed-rival case (deterministic, no concurrency needed) is covered
# above by test_payment_after_expiry_does_not_steal_a_slot_someone_else_took: the rival
# books and commits, THEN mark_paid runs, and confirm_paid_booking's plain SELECT sees
# it (a read-only query in this app's sqlite setup always sees the latest committed row —
# proven in claim_lock's own docstring, no lock needed to prove that half). What is NOT
# covered anywhere else is genuine concurrency — the two decisions actually overlapping —
# which only a real second thread can exercise (a nested same-thread session cannot: it
# would block synchronously on the SAME connection's held write lock and just time out,
# proving nothing).
def test_mark_paid_and_a_new_booking_cannot_both_win_the_same_slot(db, clinic, clock):
    """The actual guarantee, on real threads: a late payment (mark_paid, on a lapsed
    hold) and a brand new booking (claim_slot) released at the same instant for the same
    slot. Exactly one may end up occupying it — never both 'confirmed'/'pending' at once.
    Without the lock in confirm_paid_booking this is racy; with it, deterministic."""
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(HOLD_MINUTES + 5)
    sweep_expired_holds(db, clinic.id)
    payment_id, svc_id, branch_id, slot = payment.id, s.svc.id, s.branch.id, s.slot

    barrier, outcomes = threading.Barrier(2), {}

    def pay():
        session = SessionLocal()
        try:
            p = session.get(models.Payment, payment_id)
            barrier.wait(timeout=10)
            outcomes["pay"] = sp.mark_paid(session, p)
        finally:
            session.close()

    def rival_book():
        session = SessionLocal()
        try:
            svc = session.get(models.Service, svc_id)
            cust = models.Customer(clinic_id=clinic.id, name="ฟ้า", channel="web")
            session.add(cust)
            session.commit()
            barrier.wait(timeout=10)
            booked, reason = claim_slot(
                session, clinic_id=clinic.id, branch_id=branch_id, slot_at=slot,
                service_id=svc_id,
                write=lambda: create_booking(session, customer=cust, service=svc,
                                             branch_id=branch_id, slot_at=slot,
                                             created_by="admin"))
            outcomes["rival"] = "won" if booked is not None else reason
        finally:
            session.close()

    threads = [threading.Thread(target=pay), threading.Thread(target=rival_book)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "confirm_paid_booking's lock deadlocked"

    db.expire_all()
    live = (db.query(models.Booking).filter_by(branch_id=branch_id, slot_at=slot)
            .filter(models.Booking.status.in_(["pending", "confirmed"])).all())
    assert len(live) == 1, f"exactly one booking may hold this slot; outcomes={outcomes}"


def test_mark_paid_holds_the_lock_bare_not_via_claim_slots_commit_path(
        db, clinic, clock, monkeypatch):
    """Pins the actual contract, directly rather than by counting commits (which also
    picks up notify_payment_paid's own later, unrelated commit and is not what's really
    at stake): mark_paid must call ``claim_lock(clinic_id)`` with NO ``db`` argument.
    Passing ``db`` would make claim_lock commit on entry (claim_slot's own shape) —
    splitting the payment compare-and-set from the rest of the cascade into two
    transactions, so a crash between them could leave a payment durably marked paid with
    nothing else applied, and no way to retry it (the compare-and-set only ever runs the
    cascade once per payment).
    """
    s = _held(db, clinic, clock)
    payment = sp.create_payment(db, booking=s.b, ptype="deposit")
    clock.advance(HOLD_MINUTES + 5)
    sweep_expired_holds(db, clinic.id)
    _take_the_slot(db, clinic, s)   # forces the locked 'slot_gone' branch

    import app.services.booking as bk_mod
    real_claim_lock, seen = bk_mod.claim_lock, []

    def spying_claim_lock(clinic_id, db=None):
        seen.append(db)
        return real_claim_lock(clinic_id, db)

    # mark_paid does `from app.services.booking import claim_lock` INSIDE the function
    # body, re-executed every call, so patching the module attribute is picked up here.
    monkeypatch.setattr(bk_mod, "claim_lock", spying_claim_lock)
    sp.mark_paid(db, payment)
    assert seen == [None], f"claim_lock must be entered bare (no db); got {seen}"
