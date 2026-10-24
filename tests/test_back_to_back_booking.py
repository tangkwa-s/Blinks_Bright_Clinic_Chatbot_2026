"""Adding a second treatment "ต่อเลย" must be answered with a time, not a handoff.

A customer who had booked and paid for one treatment asked to add another straight
after. The assistant tried the time they were already booked for, ``book_appointment``
answered "That time isn't available — call check_availability first", and nothing in
that sentence said the clash was the customer's OWN appointment. It could neither
explain it nor work out what to offer, so it said the team would check and get back.

Underneath it was worse than a bad message: a booking only reserved the MINUTE it
started, so a 50-minute treatment could be booked into the middle of a 40-minute one —
same branch, same chair, sometimes the same person.
"""
from datetime import timedelta

from app import models
from app.ai.tools import execute_tool
from app.services import booking as bk
from app.services.booking import SLOT_MINUTES, available_slots, create_booking


# Booking on the website is members-only (tools.booking_requires_signup), and these
# tests are about the booking itself, so their web customers hold a portal account.
MEMBER = "portal-member"


def _setup(db, clinic, first_min=40, second_min=50):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    first = models.Service(clinic_id=clinic.id, name="Skin Booster", category="facial",
                           base_price=9500, duration_min=first_min, active=True)
    second = models.Service(clinic_id=clinic.id, name="Acne Clear Program", category="facial",
                            base_price=3500, duration_min=second_min, active=True)
    cust = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="มิ้นท์", phone="0955555555",
                           channel="web", branch_id=branch.id)
    db.add_all([first, second, cust])
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    return branch, first, second, cust, conv


def _answered_payment(db, conv):
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id, sender="ai",
                          text="ต้องการชำระมัดจำหรือชำระเต็มจำนวนคะ"))
    db.commit()
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender="customer", text="มัดจำค่ะ"))
    db.commit()


def _book_args(svc, slot):
    return {"treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
            "time": slot.strftime("%H:%M"), "payment_type": "deposit",
            "payment_said": "มัดจำค่ะ"}


# --------------------------------------------------------------------------
# a treatment occupies its whole duration
# --------------------------------------------------------------------------
def test_a_long_treatment_blocks_the_slots_it_actually_runs_through(db, clinic):
    branch, first, _second, cust, _conv = _setup(db, clinic, first_min=90)
    day = bk._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    create_booking(db, customer=cust, service=first, branch_id=branch.id, slot_at=slot)
    db.commit()

    free = available_slots(db, branch.id, day)
    for n in range(3):                       # 90 minutes = three 30-minute slots
        assert slot + timedelta(minutes=n * SLOT_MINUTES) not in free
    assert slot + timedelta(minutes=90) in free, "the slot it finishes on is free again"


def test_another_customer_cannot_book_into_the_middle_of_it(db, clinic):
    """The reported shape: 40 minutes from 10:00, someone else takes 10:30."""
    branch, first, second, cust, _conv = _setup(db, clinic)
    day = bk._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    create_booking(db, customer=cust, service=first, branch_id=branch.id, slot_at=slot)
    db.commit()

    other = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="คนอื่น", channel="web")
    db.add(other)
    db.commit()
    mid = slot + timedelta(minutes=SLOT_MINUTES)
    assert mid not in available_slots(db, branch.id, day, service_id=second.id)


def test_a_treatment_that_cannot_finish_before_closing_is_not_offered(db, clinic):
    branch, _first, second, _cust, _conv = _setup(db, clinic, second_min=50)
    day = bk._now_local() + timedelta(days=3)
    free = available_slots(db, branch.id, day, service_id=second.id)
    close = bk._day_window(branch, day)[1]
    for s in free:
        assert s.hour * 60 + s.minute + 50 <= close


# --------------------------------------------------------------------------
# "ต่อเลย" — the customer's own appointment is a queue, not a clash
# --------------------------------------------------------------------------
def test_their_own_appointment_gets_a_time_not_a_refusal(db, clinic):
    branch, first, second, cust, conv = _setup(db, clinic)
    day = bk._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    create_booking(db, customer=cust, service=first, branch_id=branch.id, slot_at=slot)
    db.commit()
    _answered_payment(db, conv)

    res = execute_tool(db, conv, cust, "book_appointment", _book_args(second, slot))
    assert "own_booking_clash" in res
    assert first.name in res["own_booking_clash"]
    ends = (slot + timedelta(minutes=40)).strftime("%H:%M")
    assert res["first_treatment_ends"] == ends
    assert ends in res["say_it_like"] and second.name in res["say_it_like"]
    assert res["nearest_slots"], "a time they can actually take"
    assert "never hand this to a human" in res["note"]
    assert db.query(models.Booking).filter_by(service_id=second.id).count() == 0


def test_the_time_offered_is_after_the_first_treatment_ends(db, clinic):
    """Not merely the next 30-minute slot: 10:00 + 40 minutes finishes at 10:40, so
    10:30 is still mid-treatment and 11:00 is the first thing that works."""
    branch, first, second, cust, conv = _setup(db, clinic)
    day = bk._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    create_booking(db, customer=cust, service=first, branch_id=branch.id, slot_at=slot)
    db.commit()
    _answered_payment(db, conv)

    res = execute_tool(db, conv, cust, "book_appointment", _book_args(second, slot))
    offered = [s.split(" ")[1] for s in res["nearest_slots"]]
    assert (slot + timedelta(minutes=60)).strftime("%H:%M") in offered
    assert (slot + timedelta(minutes=SLOT_MINUTES)).strftime("%H:%M") not in offered


def test_the_offered_time_can_then_be_booked(db, clinic):
    branch, first, second, cust, conv = _setup(db, clinic)
    day = bk._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    create_booking(db, customer=cust, service=first, branch_id=branch.id, slot_at=slot)
    db.commit()
    _answered_payment(db, conv)

    offered = execute_tool(db, conv, cust, "book_appointment",
                           _book_args(second, slot))["nearest_slots"][0]
    when = bk.datetime.strptime(offered, "%Y-%m-%d %H:%M")
    res = execute_tool(db, conv, cust, "book_appointment", _book_args(second, when))
    assert res.get("booked") is True


def test_a_different_day_is_just_a_normal_booking(db, clinic):
    """Nothing to queue behind, so no queue message."""
    branch, first, second, cust, conv = _setup(db, clinic)
    day = bk._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    create_booking(db, customer=cust, service=first, branch_id=branch.id, slot_at=slot)
    db.commit()
    _answered_payment(db, conv)

    other_day = available_slots(db, branch.id, day + timedelta(days=1))[0]
    res = execute_tool(db, conv, cust, "book_appointment", _book_args(second, other_day))
    assert "own_booking_clash" not in res
    assert res.get("booked") is True


def test_someone_elses_booking_is_still_just_unavailable(db, clinic):
    """The friendly queue message is only for THEIR own appointment — another
    customer's booking must not be described to them at all."""
    branch, first, second, cust, conv = _setup(db, clinic)
    day = bk._now_local() + timedelta(days=3)
    slot = available_slots(db, branch.id, day)[0]
    other = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="คนอื่น", channel="web")
    db.add(other)
    db.commit()
    create_booking(db, customer=other, service=first, branch_id=branch.id, slot_at=slot)
    db.commit()
    _answered_payment(db, conv)

    res = execute_tool(db, conv, cust, "book_appointment", _book_args(second, slot))
    assert "own_booking_clash" not in res
    assert res.get("booked") is not True
    assert db.query(models.Booking).filter_by(service_id=second.id).count() == 0
