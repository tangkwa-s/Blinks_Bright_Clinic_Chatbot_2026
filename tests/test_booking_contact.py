"""Regression tests for the booking flow's contact step and checklist hint.

The AI booking playbook now collects five things before it may summarise or book:
branch, treatment, date/time, the customer's NAME and their PHONE. Two mechanisms
back that prompt rule up so it cannot silently drift:

  - ``tools.book_appointment`` refuses to create a booking while the name is still a
    channel placeholder or no phone is on file, and persists whatever the AI passes
    as ``customer_name`` / ``phone`` (instead of waiting for ``sales.analyze``).
  - ``chat._booking_hint`` states which checklist items the system already knows
    (branch on the conversation, name/phone on the customer), so the AI stops
    re-asking questions the customer has already answered.
"""
from datetime import timedelta

from app import models
from app.ai import guard
from app.ai.chat import _booking_hint, _contact_grounding
from app.ai.tools import execute_tool
from app.services import booking


# Booking on the website is members-only (tools.booking_requires_signup), and these
# tests are about the booking itself, so their web customers hold a portal account.
MEMBER = "portal-member"


def _mk_service(db, clinic, name="Signature Facial", base_price=2500.0):
    s = models.Service(clinic_id=clinic.id, name=name, category="facial",
                       base_price=base_price, active=True)
    db.add(s)
    db.commit()
    return s


def _mk_customer(db, clinic, name="Web Visitor", phone="", branch_id=None):
    c = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name=name, phone=phone, channel="web",
                        branch_id=branch_id)
    db.add(c)
    db.commit()
    return c


def _mk_conversation(db, clinic, customer, branch=None):
    conv = models.Conversation(clinic_id=clinic.id, customer_id=customer.id,
                               channel="web", branch_id=branch.id if branch else None)
    db.add(conv)
    db.commit()
    return conv


def _answered_payment(db, conv, answer="มัดจำค่ะ"):
    """Put the deposit-or-full question to the customer and have them answer it.

    book_appointment now reads that exchange off the transcript, because a required
    ``payment_type`` argument is something the model can satisfy by simply filling it
    in — which it did, booking and sending a payment link to a customer who had only
    sent their phone number.
    """
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id, sender="ai",
                          text="สรุปคิวนะคะ ราคา 2,500 บาท มัดจำ 500 บาท "
                               "ต้องการชำระมัดจำหรือชำระเต็มจำนวนคะ"))
    db.commit()
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender="customer", text=answer))
    db.commit()


def _open_slot(db, branch):
    """A genuinely bookable slot a few days out."""
    day = booking._now_local() + timedelta(days=3)
    slots = booking.available_slots(db, branch.id, day)
    assert slots, "expected the seeded branch to have open slots"
    return slots[0]


def _book_args(svc, slot, **kw):
    """Booking args. ``payment_type`` is omitted unless a test passes one — the tool
    refuses to book without the customer's deposit-or-full answer."""
    args = {"treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
            "time": slot.strftime("%H:%M")}
    args.update(kw)
    return args


# --------------------------------------------------------------------------
# book_appointment — name + phone are required
# --------------------------------------------------------------------------
def test_booking_blocked_without_name_and_phone(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, branch_id=branch.id)   # placeholder name, no phone
    conv = _mk_conversation(db, clinic, cust, branch=branch)

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch)))
    assert res.get("need_contact") == ["name", "phone number"]
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 0


def test_booking_blocked_when_only_phone_missing(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, name="มะลิ ใจดี", branch_id=branch.id)
    conv = _mk_conversation(db, clinic, cust, branch=branch)

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch)))
    assert res.get("need_contact") == ["phone number"]
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 0


def test_booking_saves_the_name_and_phone_the_ai_collected(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, branch_id=branch.id)
    conv = _mk_conversation(db, clinic, cust, branch=branch)
    _answered_payment(db, conv, "มัดจำค่ะ")

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit",
                                  customer_name="มะลิ ใจดี", phone="081-234-5678"))
    assert res.get("booked") is True
    db.refresh(cust)
    assert cust.name == "มะลิ ใจดี"
    assert cust.phone == "0812345678"          # normalised by sales._extract_phone
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 1


def test_contact_already_on_file_needs_no_arguments(db, clinic):
    """A returning customer never has to repeat details the CRM already holds."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, name="Anna Lee", phone="0891112222",
                        branch_id=branch.id)
    conv = _mk_conversation(db, clinic, cust, branch=branch)
    _answered_payment(db, conv, "ขอชำระเต็มจำนวนค่ะ")

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="full"))
    assert res.get("booked") is True
    db.refresh(cust)
    assert cust.name == "Anna Lee"             # a real name is never overwritten
    assert cust.phone == "0891112222"


# --------------------------------------------------------------------------
# book_appointment — the deposit-or-full checkpoint
# --------------------------------------------------------------------------
def test_booking_blocked_until_the_customer_picks_deposit_or_full(db, clinic):
    """The summary turn must end with the question, not with a booking + payment link."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, name="Anna Lee", phone="0891112222",
                        branch_id=branch.id)
    conv = _mk_conversation(db, clinic, cust, branch=branch)

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch)))
    assert res.get("need_payment_choice") is True
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 0
    assert db.query(models.Payment).filter_by(clinic_id=clinic.id).count() == 0


def test_availability_flags_the_customers_own_booking(db, clinic):
    """A slot the customer already booked must never be reported back as unavailable."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, name="Anna Lee", phone="0891112222",
                        branch_id=branch.id)
    conv = _mk_conversation(db, clinic, cust, branch=branch)
    slot = _open_slot(db, branch)
    booking.create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                           slot_at=slot, conversation_id=conv.id, created_by="ai")

    res = execute_tool(db, conv, cust, "check_availability",
                       {"date": slot.strftime("%Y-%m-%d")})
    assert slot.strftime("%Y-%m-%d %H:%M") not in res["available_slots"]
    assert any(slot.strftime("%Y-%m-%d %H:%M") in row
               for row in res.get("customers_own_bookings", []))
    assert "own_booking_note" in res


def test_unparseable_phone_is_not_saved(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, name="Anna Lee", branch_id=branch.id)
    conv = _mk_conversation(db, clinic, cust, branch=branch)

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), phone="ไม่บอก"))
    assert res.get("need_contact") == ["phone number"]
    db.refresh(cust)
    assert not cust.phone


# --------------------------------------------------------------------------
# _booking_hint — what the system tells the AI it already knows
# --------------------------------------------------------------------------
def test_hint_lists_every_branch_while_none_is_chosen(db, clinic):
    db.add(models.Branch(clinic_id=clinic.id, name="Central Branch"))
    db.commit()
    cust = _mk_customer(db, clinic)
    conv = _mk_conversation(db, clinic, cust)          # no branch yet

    hint = _booking_hint(db, conv, cust)
    assert "NOT chosen yet" in hint
    for b in db.query(models.Branch).filter_by(clinic_id=clinic.id).all():
        assert b.name in hint


def test_hint_reports_known_branch_name_and_phone(db, clinic):
    """A branch counts as KNOWN only when the customer's own words contain it —
    conversation.branch_id can be written from the model's tool-call argument, so
    without this check a hallucinated branch came back labelled authoritative and
    the assistant confirmed a branch the customer never picked."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    cust = _mk_customer(db, clinic, name="Anna Lee", phone="0891112222")
    conv = _mk_conversation(db, clinic, cust, branch=branch)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text=f"ขอสาขา {branch.name} ค่ะ"))
    db.commit()

    hint = _booking_hint(db, conv, cust)
    assert f"KNOWN = {branch.name}" in hint
    assert "KNOWN = Anna Lee" in hint
    assert "KNOWN = 0891112222" in hint
    assert "NOT chosen yet" not in hint and "NOT on file" not in hint


def test_hint_branch_set_without_customer_saying_it_demands_confirmation(db, clinic):
    """Branch on the conversation but absent from the customer's messages (e.g. the
    model guessed it into a tool call) → the hint must NOT claim KNOWN; it must tell
    the assistant to state the branch once so the customer can correct it."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    cust = _mk_customer(db, clinic, name="Anna Lee", phone="0891112222")
    conv = _mk_conversation(db, clinic, cust, branch=branch)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="สนใจโบท็อกซ์ค่ะ"))
    db.commit()

    hint = _booking_hint(db, conv, cust)
    assert f"KNOWN = {branch.name}" not in hint
    assert "not clearly named it" in hint and "state it once" in hint


def test_hint_suggests_usual_branch_without_assuming(db, clinic):
    """Returning customer: home branch is a SUGGESTION to confirm, never pre-locked.
    New conversations no longer inherit customer.branch_id (that pre-lock made the
    AI assert last visit's branch — sometimes the wrong one for this visit)."""
    branches = db.query(models.Branch).filter_by(clinic_id=clinic.id).all()
    if len(branches) < 2:
        b2 = models.Branch(clinic_id=clinic.id, name="Second Branch", address="x")
        db.add(b2)
        db.commit()
    home = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    cust = _mk_customer(db, clinic, name="Anna Lee", phone="0891112222")
    cust.branch_id = home.id            # home branch from an earlier visit
    conv = _mk_conversation(db, clinic, cust)   # NEW chat — no branch
    db.commit()

    hint = _booking_hint(db, conv, cust)
    assert "NOT chosen yet" in hint
    assert f"USUAL branch from past visits is {home.name}" in hint
    assert "never assume" in hint


# --------------------------------------------------------------------------
# A branch is only ever the one the CUSTOMER named
# --------------------------------------------------------------------------
def _say(db, clinic, conv, text):
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text=text))
    db.commit()


def test_branch_the_model_invented_is_ignored(db, clinic):
    """The AI picking a branch on the customer's behalf must not stick — otherwise it
    defeats the need_branch guard and books them somewhere they never asked for."""
    second = models.Branch(clinic_id=clinic.id, name="Thonglor Clinic")
    db.add(second)
    db.commit()
    first = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    cust = _mk_customer(db, clinic)
    conv = _mk_conversation(db, clinic, cust)
    _say(db, clinic, conv, "สวัสดีค่ะ สนใจ HIFU")          # never names a branch

    res = execute_tool(db, conv, cust, "list_treatments", {"branch": first.name})
    db.refresh(conv)
    db.refresh(cust)
    assert conv.branch_id is None and cust.branch_id is None
    assert "branch_note" in res                              # still asked to ask
    assert first.name in res["branch_note"]                  # and told which one was dropped

    # ...and the hard guard still fires for booking-side tools
    assert execute_tool(db, conv, cust, "check_availability",
                        {"branch": first.name}).get("need_branch") is True


def test_branch_the_customer_named_is_adopted(db, clinic):
    """English branch name typed by the customer — matched on the name's own words."""
    db.add(models.Branch(clinic_id=clinic.id, name="Thonglor Clinic"))
    db.commit()
    thonglor = db.query(models.Branch).filter_by(clinic_id=clinic.id,
                                                 name="Thonglor Clinic").first()
    cust = _mk_customer(db, clinic)
    conv = _mk_conversation(db, clinic, cust)
    _say(db, clinic, conv, "ขอสาขา Thonglor ค่ะ")

    execute_tool(db, conv, cust, "list_treatments", {"branch": "Thonglor Clinic"})
    db.refresh(conv)
    assert conv.branch_id == thonglor.id


def test_thai_answer_is_adopted_via_branch_said(db, clinic):
    """The customer answers in Thai for an English-named branch: the model corroborates
    by quoting their exact words."""
    db.add(models.Branch(clinic_id=clinic.id, name="Thonglor Clinic"))
    db.commit()
    thonglor = db.query(models.Branch).filter_by(clinic_id=clinic.id,
                                                 name="Thonglor Clinic").first()
    cust = _mk_customer(db, clinic)
    conv = _mk_conversation(db, clinic, cust)
    _say(db, clinic, conv, "สาขาทองหล่อครับ")

    execute_tool(db, conv, cust, "list_treatments",
                 {"branch": "Thonglor Clinic", "branch_said": "ทองหล่อ"})
    db.refresh(conv)
    assert conv.branch_id == thonglor.id


def test_branch_said_must_really_come_from_the_customer(db, clinic):
    """A quote the customer never typed is not evidence."""
    db.add(models.Branch(clinic_id=clinic.id, name="Thonglor Clinic"))
    db.commit()
    cust = _mk_customer(db, clinic)
    conv = _mk_conversation(db, clinic, cust)
    _say(db, clinic, conv, "สนใจ HIFU ค่ะ")

    execute_tool(db, conv, cust, "list_treatments",
                 {"branch": "Thonglor Clinic", "branch_said": "ทองหล่อ"})
    db.refresh(conv)
    assert conv.branch_id is None


def test_single_branch_clinic_needs_no_corroboration(db, clinic):
    """With one branch there is nothing to choose, so the check must not get in the way."""
    only = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    cust = _mk_customer(db, clinic)
    conv = _mk_conversation(db, clinic, cust)
    _say(db, clinic, conv, "สนใจทำทรีตเมนต์ค่ะ")

    execute_tool(db, conv, cust, "list_treatments", {"branch": only.name})
    db.refresh(conv)
    assert conv.branch_id == only.id


# --------------------------------------------------------------------------
# _contact_grounding — the booking summary may repeat the customer's own phone
# --------------------------------------------------------------------------
class _Msg:
    def __init__(self, sender, text):
        self.sender, self.text = sender, text


def test_customer_phone_in_a_summary_is_grounded(db, clinic):
    """Echoing the phone the customer typed must not be flagged as a hallucination."""
    cust = _mk_customer(db, clinic, name="มะลิ")
    convo = [_Msg("customer", "เบอร์ 081-234-5678 ค่ะ"), _Msg("ai", "รับทราบค่ะ")]

    grounding = "Signature Facial: from ฿2,800 " + _contact_grounding(convo, cust)
    summary = "คุณมะลิ / 081-234-5678 / Signature Facial / ราคา 2,800 บาท"
    assert guard.check(summary, grounding)["grounded"] is True


def test_a_number_typed_with_plus_66_is_grounded_when_said_back_in_standard_form(db, clinic):
    """The assistant is now told to always SAY the phone in the standard grouped
    form (091-123-4567), never the customer's own raw typed shape (e.g. "+66" with
    the leading 0 kept, "+660911234567") — but the hallucination guard splits on
    non-digit characters, so the grounding text must carry those SAME dash
    positions or a correct, freshly-normalised number reads as ungrounded."""
    cust = _mk_customer(db, clinic, name="มะลิ")
    convo = [_Msg("customer", "+660911234567"), _Msg("ai", "รับทราบค่ะ")]

    grounding = "Signature Facial: from ฿2,800 " + _contact_grounding(convo, cust)
    summary = "คุณมะลิ / 091-123-4567 / Signature Facial / ราคา 2,800 บาท"
    assert guard.check(summary, grounding)["grounded"] is True


def test_contact_grounding_does_not_launder_a_customers_price(db, clinic):
    """Narrow by design: a price the CUSTOMER proposed stays ungrounded, so the AI
    quoting it back is still flagged."""
    cust = _mk_customer(db, clinic, name="มะลิ")
    convo = [_Msg("customer", "ขอลดเหลือ 3000 ได้ไหมคะ")]

    grounding = "Skin Booster: from ฿9,500 " + _contact_grounding(convo, cust)
    assert guard.check("ได้ค่ะ ราคา 3000 บาท", grounding)["unsupported"] == ["3000"]


# --------------------------------------------------------------------------
# The deposit-or-full answer must be VISIBLE in the transcript
# --------------------------------------------------------------------------
def _ready_to_book(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic)
    cust = _mk_customer(db, clinic, name="ไพรวัลย์", phone="0817123482",
                        branch_id=branch.id)
    return branch, svc, cust, _mk_conversation(db, clinic, cust, branch=branch)


def test_a_phone_number_is_not_an_answer_to_the_payment_question(db, clinic):
    """The reported bug: the customer sent only their phone number and got back a
    confirmed booking and a payment link. The model had filled payment_type in itself,
    which a merely-required argument cannot prevent."""
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="ai", text="รบกวนแจ้งเบอร์โทรศัพท์สำหรับการจองด้วยนะคะ"))
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="081-712-3482"))
    db.commit()

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit",
                                  payment_said="081-712-3482"))
    assert res.get("need_payment_choice") is True
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 0
    assert db.query(models.Payment).filter_by(clinic_id=clinic.id).count() == 0


def test_answer_given_before_the_question_does_not_count(db, clinic):
    """"มัดจำเท่าไหร่คะ" asked EARLIER is a question about the deposit, not a choice."""
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="มัดจำเท่าไหร่คะ"))
    db.commit()

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit"))
    assert res.get("need_payment_choice") is True


def test_booking_proceeds_once_they_actually_answer(db, clinic):
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "มัดจำค่ะ")

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit",
                                  payment_said="มัดจำค่ะ"))
    assert res.get("booked") is True


def test_a_typo_in_the_deposit_answer_still_counts(db, clinic):
    """Caught live: a customer typed "มัดเจำ" (ตัวอักษรสลับ, a transposed keystroke) for
    "มัดจำ". None of the exact keywords matched, so book_appointment kept reporting
    need_payment_choice to a customer who had just answered it — and the model, asked
    once and told twice it still wasn't answered, invented a "system trouble" excuse
    rather than the real state or a genuine re-ask."""
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "มัดเจำ")

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit",
                                  payment_said="มัดเจำ"))
    assert res.get("booked") is True


def test_a_typo_in_the_full_amount_answer_still_counts(db, clinic):
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "เต็มจานวนค่ะ")   # missing the ำ

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="full",
                                  payment_said="เต็มจานวนค่ะ"))
    assert res.get("booked") is True


def test_an_unrelated_short_reply_does_not_fuzzy_match_either_word(db, clinic):
    """Typo tolerance must not widen into "any short reply counts" — "ครับ" is not one
    keystroke from either "มัดจำ" or any of the full-amount phrases."""
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "ครับ")

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit"))
    assert res.get("need_payment_choice") is True


def test_a_misquoted_payment_said_does_not_erase_the_real_answer(db, clinic):
    """The customer answered "มัดจำค่ะ", then had to correct their phone number.

    On the retry the model quoted their LATEST message — the phone — as payment_said.
    Narrowing the search to that quote deleted the answer sitting earlier in the very
    same transcript, so a customer who had chosen, corrected their number and asked to
    pay was told the booking could not be made and handed to a human. The quote is
    there to settle a transcript containing BOTH words; it must never subtract evidence.
    """
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "มัดจำค่ะ")
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="อ่อ 0954562666 ค่ะ"))
    db.commit()

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit",
                                  phone="0954562666", payment_said="อ่อ 0954562666 ค่ะ"))
    assert res.get("booked") is True


def test_a_decisive_quote_still_settles_a_transcript_with_both_words(db, clinic):
    """What the quote is FOR: they said both words, and only the quote says which."""
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "ไม่เอาเต็มจำนวนค่ะ ขอมัดจำ")

    assert execute_tool(db, conv, cust, "book_appointment",
                        _book_args(svc, _open_slot(db, branch), payment_type="deposit",
                                   payment_said="ขอมัดจำ")).get("booked") is True


def test_payment_type_must_match_what_they_said(db, clinic):
    """They chose the deposit; the model must not book them for the full amount."""
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "มัดจำค่ะ")

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="full"))
    assert res.get("need_payment_choice") is True
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 0


def test_an_ambiguous_reply_is_not_an_answer(db, clinic):
    """"ครับ" answers a yes/no question, not a choice between two options."""
    branch, svc, cust, conv = _ready_to_book(db, clinic)
    _answered_payment(db, conv, "ครับ")

    res = execute_tool(db, conv, cust, "book_appointment",
                       _book_args(svc, _open_slot(db, branch), payment_type="deposit"))
    assert res.get("need_payment_choice") is True
