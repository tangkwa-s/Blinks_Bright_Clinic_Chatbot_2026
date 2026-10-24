"""Two customers, one slot: the first writer wins. The suite's first concurrency test.

Booking was a check-then-write with nothing in between: ``available_slots`` said yes, and
some lines later a row was inserted. Nothing held the gap — no lock, no unique constraint,
and no constraint could express the rule anyway (a booking occupies its treatment's whole
duration, and the doctor conflict spans branches). The gap is real, not theoretical: AI
bookings are written from BackgroundTask threads on their own sessions while the admin
routes run on Starlette's 40-thread pool.

``claim_slot`` closes it by re-running the availability check and the write together under
one per-clinic lock. These tests cover both what it guarantees and what it deliberately
does not.
"""
import threading
from datetime import timedelta

from app import models
from app.ai import tools as tools_mod
from app.ai.tools import execute_tool
from app.database import SessionLocal
from app.services import booking as bk
from app.services.booking import (HOLD_MINUTES, SLOT_TAKEN, available_slots,
                                  claim_slot, create_booking)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
# Booking on the website is members-only (tools.booking_requires_signup), and these
# tests are about the booking itself, so their web customers hold a portal account.
MEMBER = "portal-member"


def _setup(db, clinic, *, duration=40, n_customers=1):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Skin Booster", category="facial",
                         base_price=9500, duration_min=duration, active=True)
    db.add(svc)
    db.commit()
    customers = []
    for i in range(n_customers):
        c = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name=f"ลูกค้า {i}", phone=f"09500000{i:02d}",
                            channel="web", branch_id=branch.id)
        db.add(c)
        customers.append(c)
    db.commit()
    return branch, svc, customers


def _free_slot(db, branch, days_ahead=3):
    return available_slots(db, branch.id, bk._now_local() + timedelta(days=days_ahead))[0]


def _commit_a_rival(clinic_id, branch_id, svc_id, cust_id, slot):
    """Take the slot from a SEPARATE session, exactly as another request would."""
    other = SessionLocal()
    try:
        create_booking(other, customer=other.get(models.Customer, cust_id),
                       service=other.get(models.Service, svc_id), branch_id=branch_id,
                       slot_at=slot, created_by="admin")
        other.commit()
    finally:
        other.close()


# --------------------------------------------------------------------------
# the gate: a rival that commits between the pre-check and the write
# --------------------------------------------------------------------------
def test_a_rival_committed_after_the_pre_check_is_still_caught(db, clinic, monkeypatch):
    """The deterministic one. The friendly pre-check has already said yes; the rival
    commits before claim_slot's own re-check runs. Delete that re-check and this fails
    with two bookings on one slot."""
    branch, svc, (mine, theirs) = _setup(db, clinic, n_customers=2)
    slot = _free_slot(db, branch)
    assert slot in available_slots(db, branch.id, slot, service_id=svc.id)  # pre-check

    real, state = bk.day_availability, {"n": 0}

    def racing(*a, **kw):
        state["n"] += 1
        if state["n"] == 1:
            _commit_a_rival(clinic.id, branch.id, svc.id, theirs.id, slot)
        return real(*a, **kw)

    monkeypatch.setattr(bk, "day_availability", racing)

    booked, reason = claim_slot(
        db, clinic_id=clinic.id, branch_id=branch.id, slot_at=slot, service_id=svc.id,
        write=lambda: create_booking(db, customer=mine, service=svc, branch_id=branch.id,
                                     slot_at=slot, created_by="ai",
                                     hold_minutes=HOLD_MINUTES))
    assert booked is None and reason == SLOT_TAKEN
    db.expire_all()
    rows = db.query(models.Booking).filter_by(slot_at=slot).all()
    assert len(rows) == 1 and rows[0].customer_id == theirs.id


def test_the_winner_is_the_one_that_wrote_first(db, clinic, monkeypatch):
    """FIFO in the only sense that matters: whoever committed first keeps the slot, and
    the loser's booking is never written at all — nothing to unwind."""
    branch, svc, (mine, theirs) = _setup(db, clinic, n_customers=2)
    slot = _free_slot(db, branch)
    _commit_a_rival(clinic.id, branch.id, svc.id, theirs.id, slot)

    booked, _reason = claim_slot(
        db, clinic_id=clinic.id, branch_id=branch.id, slot_at=slot, service_id=svc.id,
        write=lambda: create_booking(db, customer=mine, service=svc, branch_id=branch.id,
                                     slot_at=slot, created_by="ai"))
    assert booked is None
    assert db.query(models.Booking).filter_by(customer_id=mine.id).count() == 0


def test_a_caller_with_pending_writes_does_not_hold_the_database_hostage(db, clinic):
    """Why claim_slot commits on entry, pinned so it cannot be 'simplified' away.

    A SELECT-only session holds nothing here (pysqlite only opens a transaction before
    DML, so reads always see the latest committed row). A session with UNCOMMITTED DML is
    different: it holds a write lock on the whole SQLite file, and any other connection
    that tries to commit during the claim gets `database is locked` instead of losing the
    race fairly. Remove the entry commit and the rival below fails with an OperationalError
    after the five-second busy timeout rather than committing.
    """
    branch, svc, (mine, theirs) = _setup(db, clinic, n_customers=2)
    slot, elsewhere = _free_slot(db, branch, 3), _free_slot(db, branch, 4)
    db.add(models.Activity(clinic_id=clinic.id, customer_id=mine.id, type="system",
                           summary="written before the claim"))
    db.flush()          # this is what opens the write transaction
    seen = {}

    def write():
        try:
            _commit_a_rival(clinic.id, branch.id, svc.id, theirs.id, elsewhere)
            seen["rival"] = "committed"
        except Exception as exc:
            seen["rival"] = type(exc).__name__
        return create_booking(db, customer=mine, service=svc, branch_id=branch.id,
                              slot_at=slot, created_by="ai")

    booked, _reason = claim_slot(db, clinic_id=clinic.id, branch_id=branch.id,
                                 slot_at=slot, service_id=svc.id, write=write)
    assert booked is not None
    assert seen["rival"] == "committed", (
        "another connection could not commit while the claim ran — the caller's "
        "uncommitted work was still holding SQLite's write lock")
    # and the caller's own pending row went in with it
    assert db.query(models.Activity).filter_by(summary="written before the claim").count() == 1


# --------------------------------------------------------------------------
# the smoke test: real threads
# --------------------------------------------------------------------------
def test_concurrent_claims_take_one_slot_between_them(db, clinic):
    """Four threads, four sessions, released together. Unlike the gate above this can
    pass by luck on a regression — it is here because the real failure arrives on
    threads, and a mechanism that deadlocks or throws under them is no use."""
    branch, svc, customers = _setup(db, clinic, n_customers=4)
    slot = _free_slot(db, branch)
    ids = [c.id for c in customers]
    barrier, results, lock = threading.Barrier(len(ids)), [], threading.Lock()

    def attempt(cust_id):
        session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            booked, reason = claim_slot(
                session, clinic_id=clinic.id, branch_id=branch.id, slot_at=slot,
                service_id=svc.id,
                write=lambda: create_booking(
                    session, customer=session.get(models.Customer, cust_id),
                    service=session.get(models.Service, svc.id), branch_id=branch.id,
                    slot_at=slot, created_by="ai", hold_minutes=HOLD_MINUTES))
            with lock:
                results.append(reason if booked is None else "won")
        finally:
            session.close()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "claim_slot deadlocked"
    assert results.count("won") == 1, results
    db.expire_all()
    assert db.query(models.Booking).filter_by(slot_at=slot).count() == 1


# --------------------------------------------------------------------------
# through the real call sites
# --------------------------------------------------------------------------
def test_a_lost_race_books_nothing_and_charges_nothing(db, clinic, monkeypatch):
    """The customer has just answered "มัดจำค่ะ" and is expecting a link. If the slot went,
    they must be told plainly — and no payment may exist for a booking that was never made."""
    branch, svc, (mine, theirs) = _setup(db, clinic, n_customers=2)
    slot = _free_slot(db, branch)
    conv = models.Conversation(clinic_id=clinic.id, customer_id=mine.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                          text="ต้องการชำระมัดจำหรือชำระเต็มจำนวนคะ"))
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="customer",
                          text="มัดจำค่ะ"))
    db.commit()

    real, state = bk.day_availability, {"n": 0}

    def racing(*a, **kw):
        state["n"] += 1
        if state["n"] == 2:      # after the friendly pre-check, before the claim's re-check
            _commit_a_rival(clinic.id, branch.id, svc.id, theirs.id, slot)
        return real(*a, **kw)

    # book_appointment's own pre-check calls day_availability by name (tools.py imports
    # it directly, like _now_local elsewhere in this suite), so it needs its own patch —
    # claim_slot's internal re-check resolves through booking.py's module globals and is
    # covered by the bk patch alone.
    monkeypatch.setattr(bk, "day_availability", racing)
    monkeypatch.setattr(tools_mod, "day_availability", racing)
    res = execute_tool(db, conv, mine, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "payment_type": "deposit",
        "payment_said": "มัดจำค่ะ"})

    assert res.get("slot_taken") is True and "booked" not in res
    assert "ยังไม่มีการเรียกเก็บเงิน" in res["say_it_like"], (
        "a failure right after agreeing to pay reads as a problem with their money")
    assert "Do NOT call create_payment_link" in res["note"]
    db.expire_all()
    assert db.query(models.Booking).filter_by(customer_id=mine.id).count() == 0
    assert db.query(models.Payment).filter_by(customer_id=mine.id).count() == 0


def test_the_series_loop_does_not_deadlock(db, clinic, auth_client):
    """The course loop holds the claim lock across every session. With a plain Lock
    instead of an RLock this hangs pytest rather than failing it."""
    branch, svc, (cust,) = _setup(db, clinic)
    slot = _free_slot(db, branch)
    r = auth_client.post("/api/bookings", json={
        "customer_id": cust.id, "service_id": svc.id, "branch_id": branch.id,
        "slot_at": slot.isoformat(), "bundle_sessions": 3,
        "bundle_interval_months": 1, "status": "confirmed"})
    assert r.status_code == 200
    assert r.json()["series_count"] == 3
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 3


def test_a_reschedule_cannot_land_on_a_slot_taken_mid_flight(db, clinic, auth_client,
                                                             monkeypatch):
    branch, svc, (mine, theirs) = _setup(db, clinic, n_customers=2)
    first = _free_slot(db, branch, days_ahead=3)
    target = _free_slot(db, branch, days_ahead=4)
    booking = create_booking(db, customer=mine, service=svc, branch_id=branch.id,
                             slot_at=first, created_by="admin")
    db.commit()

    real, state = bk.day_availability, {"n": 0}

    def racing(*a, **kw):
        state["n"] += 1
        if state["n"] == 1:
            _commit_a_rival(clinic.id, branch.id, svc.id, theirs.id, target)
        return real(*a, **kw)

    monkeypatch.setattr(bk, "day_availability", racing)
    r = auth_client.patch(f"/api/bookings/{booking.id}",
                          json={"slot_at": target.isoformat()})
    assert r.status_code == 409
    db.expire_all()
    assert db.get(models.Booking, booking.id).slot_at == first, "it did not move"


def test_a_long_treatment_cannot_be_rescheduled_into_a_short_gap(db, clinic, auth_client):
    """The reschedule check never passed service_id, so it only ever asked whether 30
    minutes were free — a 90-minute treatment could be moved to the last slot of the day
    and run an hour past closing."""
    branch, svc, (cust,) = _setup(db, clinic, duration=90)
    day = bk._now_local() + timedelta(days=3)
    slots = available_slots(db, branch.id, day)
    booking = create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                             slot_at=slots[0], created_by="admin")
    db.commit()
    r = auth_client.patch(f"/api/bookings/{booking.id}",
                          json={"slot_at": slots[-1].isoformat()})
    assert r.status_code == 409
    db.expire_all()
    assert db.get(models.Booking, booking.id).slot_at == slots[0]
