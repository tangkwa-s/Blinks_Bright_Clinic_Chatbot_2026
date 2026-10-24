"""An unpaid AI booking holds its slot for HOLD_MINUTES (default 10), then gives it back.

Before this, a booking was written ``pending`` and blocked its slot from that instant
until two hours AFTER the appointment time — the only thing that ever released it was the
no-show sweep. So one abandoned checkout took a Saturday 14:00 off the menu for three
weeks, nobody could book it, and the customer who walked away was never told anything.

The release belongs to the READER (day_availability drops a lapsed hold at query time),
not to any job — a customer asking 31 seconds after a hold ran out has to see that slot.
The sweep exists to make every other reader agree, and to say it out loud; the 60-second
scheduler job (sweep_all_expired_holds) is what makes the saying-it prompt.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import models
from app.ai.tools import execute_tool
from app.security import make_calendar_token
from app.services import booking as bk
from app.services.booking import (EXPIRED, HOLD_MINUTES, HOLD_REMINDER_MINUTES,
                                  HOLD_REMINDER_SWEEP_BUFFER_SECONDS, available_slots,
                                  create_booking, sweep_expired_holds,
                                  sweep_hold_reminders, sweep_no_shows)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
# Booking on the website is members-only (tools.booking_requires_signup), and these
# tests are about the booking itself, so their web customers hold a portal account.
MEMBER = "portal-member"


@pytest.fixture
def clock(monkeypatch):
    """Freeze the clinic clock in every module that READS it, and let a test move it.

    FOUR modules import ``_now_local`` by name, so each keeps its own reference:
    app.services.booking (functions defined there resolve it from module globals),
    app.ai.tools, app.routers.bookings and app.services.automations. Patching only some
    of them is how a test passes while the app disagrees with itself. One mutable cell
    shared by all four lambdas means ``advance`` moves them together.

    Anchored to the real clinic clock rather than a fixed date, so "three days from now"
    still lands inside the seeded branch's real opening hours.
    """
    from app.ai import tools as T
    from app.routers import bookings as R
    from app.services import automations as A

    cell = {"now": bk._now_local()}
    for mod in (bk, T, R, A):
        monkeypatch.setattr(mod, "_now_local", lambda: cell["now"])
    return SimpleNamespace(
        now=lambda: cell["now"],
        advance=lambda minutes: cell.update(now=cell["now"] + timedelta(minutes=minutes)))


def _setup(db, clinic, *, price=9500, duration=40):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Skin Booster", category="facial",
                         base_price=price, duration_min=duration, active=True)
    cust = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="มิ้นท์", phone="0955555555",
                           channel="web", branch_id=branch.id)
    db.add_all([svc, cust])
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    return branch, svc, cust, conv


def _answered_payment(db, conv):
    """The two transcript messages book_appointment requires before it will book."""
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id, sender="ai",
                          text="ต้องการชำระมัดจำหรือชำระเต็มจำนวนคะ"))
    db.commit()
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender="customer", text="มัดจำค่ะ"))
    db.commit()


def _held_booking(db, clinic, clock, *, days_ahead=3, price=9500, hold_minutes=HOLD_MINUTES):
    """A booking held the way the AI holds one, at a real free slot."""
    branch, svc, cust, conv = _setup(db, clinic, price=price)
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=days_ahead))[0]
    b = create_booking(db, customer=cust, service=svc, branch_id=branch.id, slot_at=slot,
                       conversation_id=conv.id, created_by="ai",
                       hold_minutes=hold_minutes)
    db.commit()
    return SimpleNamespace(branch=branch, svc=svc, cust=cust, conv=conv, slot=slot, b=b)


def _activities(db, clinic, booking_id):
    return (db.query(models.Activity)
            .filter_by(clinic_id=clinic.id, ref_type="booking", ref_id=booking_id).all())


# --------------------------------------------------------------------------
# who gets a hold
# --------------------------------------------------------------------------
def test_the_default_hold_is_ten_minutes():
    """10 นาทีคือนโยบาย: จองแล้วต้องชำระภายใน 10 นาที ไม่งั้นระบบปล่อยคิว. Pinned on the
    DEFAULT, not the live value, so a deliberate .env HOLD_MINUTES override on one
    install does not fail the suite while a silent code change still does."""
    from app.config import Settings, settings

    assert Settings.model_fields["hold_minutes"].default == 10
    assert HOLD_MINUTES == max(1, settings.hold_minutes)


def test_an_ai_booking_is_held_not_confirmed(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    assert s.b.status == "pending"
    assert s.b.hold_expires_at == clock.now() + timedelta(minutes=HOLD_MINUTES)


def test_an_admin_booking_is_never_held(db, clinic, clock, auth_client):
    branch, svc, cust, _conv = _setup(db, clinic)
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=3))[0]
    r = auth_client.post("/api/bookings", json={
        "customer_id": cust.id, "service_id": svc.id, "branch_id": branch.id,
        "slot_at": slot.isoformat(), "status": "confirmed"})
    assert r.status_code == 200
    assert r.json()["hold_expires_at"] is None
    clock.advance(60 * 24 * 365)
    assert sweep_expired_holds(db, clinic.id) == 0, "a staff booking is a real reservation"


def test_a_treatment_with_nothing_to_pay_is_not_held(db, clinic, clock):
    """A hold is a deadline for a payment. With no payment there is nothing to wait
    for, and the slot would be released for no reason at all."""
    s = _held_booking(db, clinic, clock, price=0)
    assert s.b.hold_expires_at is None


# --------------------------------------------------------------------------
# the reader releases the slot — not the sweep
# --------------------------------------------------------------------------
def test_the_slot_is_blocked_while_the_hold_is_live(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES - 1)
    assert s.slot not in available_slots(db, s.branch.id, s.slot)


def test_the_slot_comes_back_the_instant_the_hold_lapses_before_any_sweep(db, clinic, clock):
    """The load-bearing one: availability must not be a function of when a background
    job last ran. Nothing is swept here — the row still says 'pending'."""
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES)
    assert s.slot in available_slots(db, s.branch.id, s.slot)
    db.refresh(s.b)
    assert s.b.status == "pending", "released by the reader, with no sweep run"


def test_another_customer_can_take_the_released_slot(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    other = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="ฟ้า", channel="web",
                            branch_id=s.branch.id)
    db.add(other)
    db.commit()
    second = create_booking(db, customer=other, service=s.svc, branch_id=s.branch.id,
                            slot_at=s.slot, created_by="admin")
    db.commit()
    assert second.id != s.b.id
    assert s.slot not in available_slots(db, s.branch.id, s.slot), "now genuinely taken"


def test_a_booking_with_no_hold_never_stops_blocking(db, clinic, clock):
    """NULL is every row written before this column existed, and every staff booking."""
    branch, svc, cust, _conv = _setup(db, clinic)
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=3))[0]
    create_booking(db, customer=cust, service=svc, branch_id=branch.id, slot_at=slot,
                   created_by="admin")
    db.commit()
    clock.advance(60 * 24 * 30)
    assert slot not in available_slots(db, branch.id, slot)


# --------------------------------------------------------------------------
# sweep_expired_holds
# --------------------------------------------------------------------------
def test_sweep_marks_a_lapsed_hold_expired_with_an_activity(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    assert sweep_expired_holds(db, clinic.id) == 1
    db.refresh(s.b)
    assert s.b.status == EXPIRED
    assert any("Hold expired" in a.summary for a in _activities(db, clinic, s.b.id))


def test_sweep_leaves_a_live_hold_alone(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES - 1)
    assert sweep_expired_holds(db, clinic.id) == 0
    db.refresh(s.b)
    assert s.b.status == "pending"


def test_a_lapsed_hold_hours_past_its_slot_is_expired_not_a_no_show(db, clinic, clock):
    """Run in run_automations order. 'No-show' says the customer failed to turn up;
    they never had an appointment to turn up to."""
    branch, svc, cust, conv = _setup(db, clinic)
    past = clock.now() - timedelta(hours=5)
    b = models.Booking(clinic_id=clinic.id, customer_id=cust.id, branch_id=branch.id,
                       service_id=svc.id, conversation_id=conv.id, slot_at=past,
                       status="pending", price=9500, deposit_required=1900,
                       hold_expires_at=past - timedelta(hours=4), created_by="ai")
    db.add(b)
    db.commit()
    assert sweep_expired_holds(db, clinic.id) == 1
    assert sweep_no_shows(db, clinic.id) == 0, "already out of the pending pool"
    db.refresh(b)
    assert b.status == EXPIRED


def test_sweep_repairs_a_paid_booking_instead_of_expiring_it(db, clinic, clock):
    """If the payment cascade half-ran, never release a slot somebody has paid for."""
    s = _held_booking(db, clinic, clock)
    db.add(models.Payment(clinic_id=clinic.id, customer_id=s.cust.id, booking_id=s.b.id,
                          type="deposit", amount=1900, status="paid"))
    db.commit()
    clock.advance(HOLD_MINUTES + 1)
    assert sweep_expired_holds(db, clinic.id) == 0
    db.refresh(s.b)
    assert s.b.status == "confirmed" and s.b.hold_expires_at is None


def test_sweep_is_clinic_scoped(db, clinic, make_clinic, clock):
    other = make_clinic("Clinic B", slug="clinic-b")
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    assert sweep_expired_holds(db, other.id) == 0
    db.refresh(s.b)
    assert s.b.status == "pending"


def test_sweep_is_idempotent(db, clinic, clock):
    _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    assert sweep_expired_holds(db, clinic.id) == 1
    assert sweep_expired_holds(db, clinic.id) == 0


def test_overlapping_sweeps_cannot_double_notify(db, clinic, clock):
    """The 60-second job, the bookings-list sweep and generate_ai_reply's sweep can fire
    in the same second, each in its own session — and each may have SELECTed the row as
    pending before the others committed. The pending→expired flip is a compare-and-set,
    so only the caller that actually flips the row tells the customer; the loser finds
    nothing to flip and must stay silent, never sending หมดเวลาถือคิว twice."""
    from app.database import SessionLocal

    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    late = SessionLocal()
    try:
        stale = late.get(models.Booking, s.b.id)
        assert stale.status == "pending", "the losing sweep's world-view before the race"
        assert sweep_expired_holds(db, clinic.id) == 1           # first sweep wins
        assert bk._expire_if_still_pending(late, stale.id) == 0  # loser flips nothing
        late.rollback()
    finally:
        late.close()
    msgs = db.query(models.Message).filter_by(conversation_id=s.conv.id).all()
    assert len(msgs) == 1, "exactly one lapse notice ever reaches the customer"


def test_sweep_cancels_the_bookings_scheduled_reminders(db, clinic, clock):
    """A reminder for a booking that no longer holds anything would tell the customer
    "พรุ่งนี้คุณมีนัด…" for an appointment they lost."""
    s = _held_booking(db, clinic, clock)
    rem = models.Reminder(clinic_id=clinic.id, customer_id=s.cust.id,
                          type="pre_appointment", channel="web", title="นัดพรุ่งนี้",
                          due_at=s.slot - timedelta(hours=24), status="scheduled",
                          booking_id=s.b.id)
    db.add(rem)
    db.commit()
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)
    db.refresh(rem)
    assert rem.status == "cancelled"


def test_an_expired_booking_gets_no_new_reminders(db, clinic, clock):
    from app.services.automations import generate_reminders

    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)
    generate_reminders(db, clinic)
    assert db.query(models.Reminder).filter_by(booking_id=s.b.id).count() == 0


def test_list_bookings_triggers_the_hold_sweep(db, clinic, clock, auth_client):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    r = auth_client.get("/api/bookings?status=pending")
    assert r.status_code == 200
    assert all(row["id"] != s.b.id for row in r.json())
    db.expire_all()
    assert db.get(models.Booking, s.b.id).status == EXPIRED


def test_run_automations_reports_expired_holds(db, clinic, clock):
    from app.services.automations import run_automations

    _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    assert run_automations(clinic_id=clinic.id)["expired_holds"] == 1


def test_the_minute_job_sweeps_every_clinic(db, clinic, make_clinic, clock):
    """sweep_all_expired_holds is what the 60-second scheduler job runs, so the
    10-minute promise does not wait for the 30-minute automations pass or for
    someone to open the bookings page. It must cover every active clinic."""
    from app.services.automations import sweep_all_expired_holds

    other = make_clinic("Clinic B", slug="clinic-b")
    a = _held_booking(db, clinic, clock)
    b = _held_booking(db, other, clock)
    clock.advance(HOLD_MINUTES + 1)
    assert sweep_all_expired_holds() == 2
    db.expire_all()
    assert db.get(models.Booking, a.b.id).status == EXPIRED
    assert db.get(models.Booking, b.b.id).status == EXPIRED


def test_an_expired_booking_is_not_in_the_calendar_feed(db, clinic, clock, client):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)
    body = client.get(f"/api/calendar/{make_calendar_token(clinic.id)}.ics").text
    assert f"UID:booking-{s.b.id}@" not in body


# --------------------------------------------------------------------------
# what the customer is told
# --------------------------------------------------------------------------
def test_the_customer_is_told_the_hold_lapsed(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)
    msgs = (db.query(models.Message).filter_by(conversation_id=s.conv.id)
            .order_by(models.Message.id).all())
    assert len(msgs) == 1
    assert msgs[0].sender == "ai", (
        "not 'system': chat.py drops system messages from the model's history, so the "
        "assistant would not know it had just told this customer their slot was gone")
    assert msgs[0].text == (
        f"คิว {s.svc.name} วันที่ {s.slot:%d/%m} เวลา {s.slot:%H:%M} น. "
        f"หมดเวลาถือคิวแล้วค่ะ เนื่องจากยังไม่ได้รับการชำระเงินภายใน {HOLD_MINUTES} นาที "
        "ระบบจึงปล่อยเวลานี้ให้ลูกค้าท่านอื่นแล้วนะคะ "
        f"หากยังต้องการทำ {s.svc.name} พิมพ์บอกได้เลยค่ะ เดี๋ยวจองใหม่ให้ทันทีค่ะ")


def test_the_lapsed_hold_notice_states_this_bookings_own_custom_number(db, clinic, clock):
    """The number stated must always match the number actually enforced for THIS
    booking (a 20-minute service override here), never the .env default — this is
    the regression the whole configurable-hold feature is protecting."""
    s = _held_booking(db, clinic, clock, hold_minutes=20)
    assert s.b.hold_minutes == 20
    clock.advance(21)
    sweep_expired_holds(db, clinic.id)
    msgs = (db.query(models.Message).filter_by(conversation_id=s.conv.id)
            .order_by(models.Message.id).all())
    assert "20 นาที" in msgs[0].text
    assert f"{HOLD_MINUTES} นาที" not in msgs[0].text


def test_book_appointment_states_the_deadline(db, clinic, clock):
    branch, svc, cust, conv = _setup(db, clinic)
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=3))[0]
    _answered_payment(db, conv)
    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "payment_type": "deposit",
        "payment_said": "มัดจำค่ะ"})
    assert res.get("booked") is True
    until = (clock.now() + timedelta(minutes=HOLD_MINUTES)).strftime("%H:%M")
    assert res["hold_minutes"] == HOLD_MINUTES and res["hold_until"] == until
    # The raw ISO deadline — drives the pay-card's live countdown in the frontend, so it
    # has to be the exact booking row's own deadline, not re-derived from "now" + minutes
    # (a re-derived value would drift a few seconds from what actually got persisted).
    booking = db.query(models.Booking).filter_by(id=res["booking_id"]).one()
    assert res["hold_expires_at"] == booking.hold_expires_at.isoformat()
    # No QR is set up in this test, so this is the hand-off branch of the sentence.
    assert res["hold_say_it_like"] == (
        f"ตอนนี้ระบบถือคิวนี้ไว้ให้ {HOLD_MINUTES} นาที ถึงเวลา {until} น. ค่ะ "
        "หากเลยเวลานี้แล้วยังไม่ได้ชำระ ระบบจะปล่อยคิวนี้ให้ลูกค้าท่านอื่นค่ะ")
    assert "Slot reserved" not in res["note"], "the old wording promised no deadline"
    assert f"HELD until {until}" in res["note"]


def test_book_appointment_uses_the_clinics_hold_override(db, clinic, clock):
    clinic.hold_minutes = 15
    db.commit()
    branch, svc, cust, conv = _setup(db, clinic)
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=3))[0]
    _answered_payment(db, conv)
    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "payment_type": "deposit",
        "payment_said": "มัดจำค่ะ"})
    assert res.get("booked") is True
    until = (clock.now() + timedelta(minutes=15)).strftime("%H:%M")
    assert res["hold_minutes"] == 15 and res["hold_until"] == until
    assert "15 นาที" in res["hold_say_it_like"]
    booking = db.query(models.Booking).filter_by(id=res["booking_id"]).one()
    assert booking.hold_minutes == 15


def test_book_appointment_service_override_wins_over_the_clinics(db, clinic, clock):
    """A realistic scenario: a surgical procedure needs its own, longer hold,
    even though the clinic has set a shorter one for everything else.

    Deliberately a treatment name NOT in the starter seed catalog ("Skin Booster",
    which _setup() also uses, already exists there with the same price/duration) —
    _find_service matches the FIRST row by that name, so a second same-named row
    created here would be silently shadowed and never actually resolved."""
    clinic.hold_minutes = 15
    db.commit()
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Custom Surgical Procedure",
                         category="surgical", base_price=50000, duration_min=90,
                         hold_minutes=25, active=True)
    cust = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="มิ้นท์", phone="0955555555",
                           channel="web", branch_id=branch.id)
    db.add_all([svc, cust])
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=3))[0]
    _answered_payment(db, conv)
    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "payment_type": "deposit",
        "payment_said": "มัดจำค่ะ"})
    assert res.get("booked") is True
    assert res["hold_minutes"] == 25
    booking = db.query(models.Booking).filter_by(id=res["booking_id"]).one()
    assert booking.hold_minutes == 25


def test_create_payment_link_returns_hold_expires_at_while_still_live(db, clinic, clock, qr_file):
    """The pay-card's countdown needs the raw deadline from create_payment_link too, not
    just from book_appointment — this is the tool a customer re-triggers by asking to pay
    again, and the card it produces needs the same live countdown as the first one."""
    s = _held_booking(db, clinic, clock)
    res = execute_tool(db, s.conv, s.cust, "create_payment_link", {"type": "deposit"})
    assert "error" not in res
    assert res["hold_expires_at"] == s.b.hold_expires_at.isoformat()


def test_create_payment_link_after_expiry_does_not_claim_there_is_no_booking(
        db, clinic, clock):
    """"No pending booking — book an appointment first" is a flat contradiction to
    someone who booked forty minutes ago and is now clicking pay."""
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)
    res = execute_tool(db, s.conv, s.cust, "create_payment_link", {"type": "deposit"})
    assert "error" not in res
    assert res["slot_still_free"] is True
    assert res["say_it_like"] == (
        f"คิว {s.svc.name} วันที่ {s.slot:%d/%m} เวลา {s.slot:%H:%M} น. หมดเวลาถือคิวแล้วค่ะ "
        f"เพราะยังไม่ได้ชำระภายใน {HOLD_MINUTES} นาที ตอนนี้เวลานั้นยังว่างอยู่ "
        "ให้จองใหม่ให้เลยไหมคะ")
    assert "do NOT send the payment QR" in res["note"]


def test_create_payment_link_after_expiry_when_the_slot_is_gone(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)
    other = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="ฟ้า", channel="web")
    db.add(other)
    db.commit()
    create_booking(db, customer=other, service=s.svc, branch_id=s.branch.id,
                   slot_at=s.slot, created_by="admin")
    db.commit()
    res = execute_tool(db, s.conv, s.cust, "create_payment_link", {"type": "deposit"})
    assert res["slot_still_free"] is False
    assert "มีลูกค้าท่านอื่นจองไปแล้วค่ะ" in res["say_it_like"]


def test_the_booking_hint_states_how_long_is_left(db, clinic, clock):
    """The minutes change every turn, so they cannot be something the model remembers."""
    from app.ai.chat import _booking_hint

    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES - 4)
    hint = _booking_hint(db, s.conv, s.cust)
    until = (s.b.hold_expires_at).strftime("%H:%M")
    assert f"HELD until {until}" in hint
    assert "4 minutes" in hint
    assert "Never call it confirmed" in hint


def test_the_booking_hint_says_a_lapsed_hold_is_gone(db, clinic, clock):
    from app.ai.chat import _booking_hint

    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)
    hint = _booking_hint(db, s.conv, s.cust)
    assert "the hold LAPSED" in hint and "never describe it as still booked" in hint


# --------------------------------------------------------------------------
# hold-reminder sweep — the LINE/Messenger customer's only warning, since no live
# countdown can run inside a chat bubble there (only the web/admin pay-card ticks).
#
# Catches a booking on the way IN to "about HOLD_REMINDER_MINUTES left" — while
# remaining is still >= HOLD_REMINDER_MINUTES, within HOLD_REMINDER_SWEEP_BUFFER_SECONDS
# of crossing that mark — not after it has already dropped below. An earlier version
# caught it only after dropping below, which a slow poll tick was seen turning into a
# message claiming "about 2 minutes" with genuinely only ~1:30 left by the time it sent.
# --------------------------------------------------------------------------
def test_hold_reminder_fires_at_the_window_start(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES - HOLD_REMINDER_MINUTES)  # remaining == HOLD_REMINDER_MINUTES exactly

    n = sweep_hold_reminders(db, clinic.id, now=clock.now())

    assert n == 1
    db.expire_all()
    assert s.b.hold_reminder_sent_at is not None
    msgs = (db.query(models.Message).filter_by(conversation_id=s.conv.id)
           .order_by(models.Message.id).all())
    assert len(msgs) == 1 and msgs[0].sender == "ai"
    assert f"{HOLD_REMINDER_MINUTES} นาที" in msgs[0].text
    assert "ยกเลิก" not in msgs[0].text and "หมดเวลาถือคิวแล้ว" not in msgs[0].text, (
        "a reminder is not an expiry notice — the hold is still live")


def test_hold_reminder_fires_anywhere_in_the_buffer(db, clinic, clock):
    """Not just the exact instant remaining crosses HOLD_REMINDER_MINUTES — any tick
    that lands within the buffer after that must still catch it once."""
    s = _held_booking(db, clinic, clock)
    buffer_min = HOLD_REMINDER_SWEEP_BUFFER_SECONDS / 60
    clock.advance(HOLD_MINUTES - HOLD_REMINDER_MINUTES - buffer_min / 2)  # mid-buffer

    n = sweep_hold_reminders(db, clinic.id, now=clock.now())

    assert n == 1
    db.expire_all()
    msg = (db.query(models.Message).filter_by(conversation_id=s.conv.id)
          .order_by(models.Message.id.desc()).first())
    assert f"{HOLD_REMINDER_MINUTES} นาที" in msg.text, (
        "genuinely 2:00-2:30 left rounds to the same '2 minutes' the customer was told, "
        "which is the point — a poll tick landing anywhere in the buffer must still "
        "produce an accurate message, not just the exact leading edge")


def test_hold_reminder_does_not_fire_past_the_buffer(db, clinic, clock):
    """A tick that (somehow) lands after the buffer has closed must not fire — that
    booking should already have been caught earlier in the window; firing this late
    would be the exact bug this window shape exists to prevent."""
    s = _held_booking(db, clinic, clock)
    buffer_min = HOLD_REMINDER_SWEEP_BUFFER_SECONDS / 60
    clock.advance(HOLD_MINUTES - HOLD_REMINDER_MINUTES - buffer_min - 0.01)

    n = sweep_hold_reminders(db, clinic.id, now=clock.now())

    assert n == 0
    db.expire_all()
    assert s.b.hold_reminder_sent_at is None


def test_hold_reminder_does_not_fire_twice(db, clinic, clock):
    s = _held_booking(db, clinic, clock)
    buffer_min = HOLD_REMINDER_SWEEP_BUFFER_SECONDS / 60
    clock.advance(HOLD_MINUTES - HOLD_REMINDER_MINUTES - buffer_min / 4)  # early in the buffer

    first = sweep_hold_reminders(db, clinic.id, now=clock.now())
    clock.advance(buffer_min / 4)   # a later tick, still inside the buffer
    second = sweep_hold_reminders(db, clinic.id, now=clock.now())

    assert (first, second) == (1, 0)
    assert (db.query(models.Message).filter_by(conversation_id=s.conv.id).count()) == 1


def test_hold_reminder_does_not_fire_too_early(db, clinic, clock):
    s = _held_booking(db, clinic, clock)   # full HOLD_MINUTES still ahead
    n = sweep_hold_reminders(db, clinic.id, now=clock.now())
    assert n == 0
    db.expire_all()
    assert s.b.hold_reminder_sent_at is None


def test_hold_reminder_does_not_fire_after_expiry(db, clinic, clock):
    """A lapsed hold is the expiry sweep's territory, not a redundant reminder."""
    s = _held_booking(db, clinic, clock)
    clock.advance(HOLD_MINUTES + 1)
    sweep_expired_holds(db, clinic.id)

    n = sweep_hold_reminders(db, clinic.id, now=clock.now())

    assert n == 0
    db.expire_all()
    assert s.b.hold_reminder_sent_at is None


def test_hold_reminder_skips_a_booking_with_no_hold(db, clinic, clock):
    """An admin booking (no hold, blocks until cancelled) has no deadline to warn
    about — hold_expires_at is NULL, not a distant future date."""
    branch, svc, cust, conv = _setup(db, clinic)
    slot = available_slots(db, branch.id, clock.now() + timedelta(days=3))[0]
    create_booking(db, customer=cust, service=svc, branch_id=branch.id, slot_at=slot,
                   conversation_id=conv.id, created_by="admin")   # hold_minutes=0 default
    db.commit()

    n = sweep_hold_reminders(db, clinic.id, now=clock.now())
    assert n == 0
