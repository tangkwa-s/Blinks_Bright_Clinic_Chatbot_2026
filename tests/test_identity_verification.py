"""Regression tests for the new-account identity check.

A returning customer often reaches the clinic from a different account (a new LINE
login, a fresh web session) and asks about a booking they already made. Nothing in
the transcript proves they are that customer — anyone can type someone else's name
and phone number — so the AI must not confirm, deny or describe a booking that is
not on the account it is talking to, and the conversation is flagged for a human to
verify identity before the records are merged.

The prompt carries the "do not confirm it" half (see ``_HARD_RULES``, exercised by
``evals/cases.py::unverified_booking_claim_escalates``). This file pins the
deterministic half: the escalation fires off the captured phone number, never off
the AI's reading of the conversation, so an impersonator cannot phrase past it.
"""
from app import models
from app.ai.sales import analyze, unverified_identity_match
from app.services.inbox import handle_inbound, phone_key


def _customer(db, clinic, name, phone, uid, **kw):
    c = models.Customer(clinic_id=clinic.id, name=name, phone=phone, channel="web",
                        channel_user_id=uid, pipeline_stage="new_lead",
                        temperature="warm", lead_score=20, **kw)
    db.add(c)
    db.commit()
    return c


def _say(db, clinic, conv, text):
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text=text))
    db.commit()


# --------------------------------------------------------------------------
# phone_key — one definition of "same phone" for the dedup finder and this check
# --------------------------------------------------------------------------
def test_phone_key_matches_the_formats_a_customer_actually_types():
    same = {phone_key("0811111111"), phone_key("081-111-1111"),
            phone_key("+66811111111"), phone_key("66811111111")}
    assert len(same) == 1 and same.pop()
    assert phone_key("0811111111") != phone_key("0822222222")
    assert phone_key("") == "" and phone_key("1234") == ""   # too short to identify


# --------------------------------------------------------------------------
# unverified_identity_match
# --------------------------------------------------------------------------
def test_match_found_across_accounts_with_the_same_phone(db, clinic):
    old = _customer(db, clinic, "Toy", "081-111-1111", "web-old")
    fresh = _customer(db, clinic, "Toy", "+66811111111", "web-new")
    assert unverified_identity_match(db, fresh).id == old.id


def test_no_match_for_a_different_phone_or_no_phone(db, clinic):
    _customer(db, clinic, "Toy", "0811111111", "web-old")
    assert unverified_identity_match(db, _customer(db, clinic, "A", "0822222222", "w2")) is None
    assert unverified_identity_match(db, _customer(db, clinic, "B", "", "w3")) is None


def test_a_record_already_merged_away_is_not_a_match(db, clinic):
    """Once merged, the old identity is a redirect stub — re-flagging it would nag
    the admin about work they already did."""
    old = _customer(db, clinic, "Toy", "0811111111", "web-old")
    fresh = _customer(db, clinic, "Toy", "0811111111", "web-new")
    old.merged_into_id = fresh.id
    db.commit()
    assert unverified_identity_match(db, fresh) is None


def test_match_does_not_leak_across_clinics(db, clinic, make_clinic):
    other = make_clinic("Clinic B", slug="clinic-b")
    _customer(db, other, "Toy", "0811111111", "web-old")
    fresh = _customer(db, clinic, "Toy", "0811111111", "web-new")
    assert unverified_identity_match(db, fresh) is None


# --------------------------------------------------------------------------
# analyze — the escalation the admin sees
# --------------------------------------------------------------------------
def test_new_account_giving_a_known_phone_is_escalated(db, clinic):
    """The exact reported case: a customer messages from a new account claiming an
    existing booking. Giving the phone must raise a flag for a human, and must NOT
    silently link the accounts."""
    old = _customer(db, clinic, "Toy", "0811111111", "web-old", ltv=4800.0)
    conv = handle_inbound(db, clinic_id=clinic.id, channel="web",
                          channel_user_id="web-new", name="Toy",
                          text="พอดีจองคิวไปที่สาขา south แล้ว ขอเช็คหน่อยครับ")
    _say(db, clinic, conv, "ชื่อ Toy เบอร์ 0811111111")

    analyze(db, conv)     # OpenAI is disabled in tests: the phone is regex-captured

    db.expire_all()
    fresh = db.get(models.Customer, conv.customer_id)
    assert fresh.phone == "0811111111"
    assert fresh.id != old.id
    assert "Same phone" in (db.get(models.Conversation, conv.id).escalation_reason or "")
    assert str(old.id) in db.get(models.Conversation, conv.id).escalation_reason
    # flagged for review, NOT auto-merged and NOT cut off from the AI
    assert fresh.merged_into_id is None and old.merged_into_id is None
    assert db.get(models.Conversation, conv.id).ai_enabled is True


def test_first_customer_with_a_phone_is_not_escalated(db, clinic):
    """No twin, no flag — an ordinary new lead giving their number stays quiet."""
    conv = handle_inbound(db, clinic_id=clinic.id, channel="web",
                          channel_user_id="web-solo", name="Nan",
                          text="สนใจ HIFU ค่ะ")
    _say(db, clinic, conv, "เบอร์ 0899999999 ค่ะ")

    analyze(db, conv)

    db.expire_all()
    assert db.get(models.Customer, conv.customer_id).phone == "0899999999"
    assert not (db.get(models.Conversation, conv.id).escalation_reason or "")
