"""Correcting your own details is not a claim on someone else's booking.

Reported: mid-booking the customer typed "บอกเบอร์ผิดค่ะ 0833333333 ชื่อเดจิค่ะ". The
unverifiable-identity HARD RULE fired — it is written for a returning customer on a NEW
account claiming a booking the clinic cannot see is theirs, but its trigger reads as
"the customer typed a name and a phone number". The assistant stopped selling, handed
off to a human, and would not issue the payment link.

Nothing in the transcript separates the two cases; the DB does. `_identity_hint` states
which one it is, so the model does not have to judge.
"""
from datetime import timedelta

from app import models
from app.ai.chat import _identity_hint
from app.services import booking as bk


def _setup(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    cust = models.Customer(clinic_id=clinic.id, name="เมจิ", phone="0833333333",
                           channel="web", branch_id=branch.id)
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    return branch, cust, conv


def _book(db, clinic, branch, cust, conv, status="pending"):
    svc = db.query(models.Service).filter_by(clinic_id=clinic.id).first()
    slot = bk.available_slots(db, branch.id, bk._now_local() + timedelta(days=2))[0]
    b = models.Booking(clinic_id=clinic.id, customer_id=cust.id, branch_id=branch.id,
                       service_id=svc.id, conversation_id=conv.id, slot_at=slot,
                       status=status, price=10000, deposit_required=2000)
    db.add(b)
    db.commit()
    return b


def test_own_booking_switches_the_rule_off(db, clinic):
    """The reported case: their own booking, made in this chat."""
    branch, cust, conv = _setup(db, clinic)
    _book(db, clinic, branch, cust, conv)

    hint = _identity_hint(db, conv, cust)
    assert "does NOT apply" in hint
    assert "made in this very chat" in hint
    assert "carry straight on" in hint and "payment" in hint
    assert "Do not hand off" in hint
    # the model's actual reason for escalating was that it believed the BOOKING held
    # its own copy of the name/phone that only a human could edit
    assert "holds\nno separate copy" in hint or "no separate copy" in hint
    assert "never call request_human_help" in hint


def test_no_booking_keeps_the_rule_armed(db, clinic):
    """A fresh account claiming an appointment the clinic cannot see is the case the
    rule was written for — it must still fire."""
    _branch, cust, conv = _setup(db, clinic)

    hint = _identity_hint(db, conv, cust)
    assert "NO booking on file" in hint
    assert "apply the unverifiable-identity HARD RULE" in hint


def test_a_bare_name_or_phone_is_never_treated_as_a_claim(db, clinic):
    """Even with no booking, simply stating or fixing contact details is normal."""
    _branch, cust, conv = _setup(db, clinic)

    hint = _identity_hint(db, conv, cust)
    assert "is NOT such a claim on its own" in hint


def test_a_booking_from_an_earlier_conversation_still_counts(db, clinic):
    """Same customer record, different chat — still their own booking."""
    branch, cust, conv = _setup(db, clinic)
    other = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="line")
    db.add(other)
    db.commit()
    _book(db, clinic, branch, cust, other)

    hint = _identity_hint(db, conv, cust)
    assert "does NOT apply" in hint
    assert "made in this very chat" not in hint       # accurate about where it came from


def test_a_cancelled_booking_does_not_arm_the_carve_out(db, clinic):
    """Only live bookings count; a cancelled one is not an appointment to protect."""
    branch, cust, conv = _setup(db, clinic)
    other = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="line")
    db.add(other)
    db.commit()
    _book(db, clinic, branch, cust, other, status="cancelled")

    assert "NO booking on file" in _identity_hint(db, conv, cust)


def test_another_customers_booking_is_invisible(db, clinic):
    """The whole point: someone else's appointment must not switch the rule off."""
    branch, cust, conv = _setup(db, clinic)
    stranger = models.Customer(clinic_id=clinic.id, name="คนอื่น", phone="0899999999",
                               channel="web")
    db.add(stranger)
    db.flush()
    other_conv = models.Conversation(clinic_id=clinic.id, customer_id=stranger.id,
                                     channel="web")
    db.add(other_conv)
    db.commit()
    _book(db, clinic, branch, stranger, other_conv)

    assert "NO booking on file" in _identity_hint(db, conv, cust)


def test_no_customer_yields_nothing(db, clinic):
    _branch, _cust, conv = _setup(db, clinic)
    assert _identity_hint(db, conv, None) == ""
