"""A phone number the system will not store must be REFUSED OUT LOUD.

One production chat lost a sale to this. The customer typed 09545626666 — eleven
digits — and ``_extract_phone`` returned "", exactly as it does when nobody has said
anything at all. Everything downstream read that silence as "not asked yet", so:

  - the assistant announced "ขอบคุณค่ะ บันทึกเบอร์ 09545626666 ให้แล้วนะคะ"
  - it summarised the booking with that number, as though it were on file
  - only when the customer went to pay did it refuse - giving no reason, so they had
    to ask "อ่าวทำไมอะคะ" before anyone told them the number was too long

"they gave nothing" and "they gave something unusable" are different facts, and the
customer can only fix the second one if it is named.
"""
from datetime import timedelta

from app import models
from app.ai.chat import _booking_hint
from app.ai.sales import _extract_phone, format_thai_mobile, phone_digits, phone_problem
from app.ai.tools import execute_tool
from app.services import booking


# Booking on the website is members-only (tools.booking_requires_signup), and these
# tests are about the booking itself, so their web customers hold a portal account.
MEMBER = "portal-member"


def _setup(db, clinic, *customer_lines, name="มะลิ ใจดี"):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Signature Facial", category="facial",
                         base_price=2500.0, active=True)
    cust = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name=name, channel="web",
                           branch_id=branch.id)
    db.add_all([svc, cust])
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    for line in customer_lines:
        db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                              sender="customer", text=line))
    db.commit()
    return branch, svc, cust, conv


def _slot(db, branch):
    day = booking._now_local() + timedelta(days=3)
    slots = booking.available_slots(db, branch.id, day)
    assert slots
    return slots[0]


# --------------------------------------------------------------------------
# the shared reader
# --------------------------------------------------------------------------
def test_it_tells_the_two_silences_apart():
    assert phone_problem("09545626666") == "too_long"
    assert phone_problem("0812345") == "too_short"
    assert phone_problem("0954562666") == ""
    assert phone_problem("095-456-2666") == ""
    assert phone_problem("+66954562666") == ""
    assert phone_problem("สนใจ Hifu ค่ะ") == "", "nothing phone-shaped was said"
    assert phone_digits("เบอร์ 09545626666 ค่ะ") == "09545626666"


# --------------------------------------------------------------------------
# every shape a real Thai mobile number can be typed in — all four valid forms,
# plus the odd-but-still-valid groupings a customer might actually type
# --------------------------------------------------------------------------
def test_every_valid_mobile_prefix_and_grouping_is_accepted():
    for text in (
        "0812345678", "081-234-5678",                    # 08x
        "0912345678", "091-234-5678",                     # 09x
        "0612345678", "061-234-5678",                     # 06x
        "+66812345678", "+66 81 234 5678",                # +66, 08x
        "+66912345678",                                   # +66, 09x
        "09-234-55661",                                   # odd grouping, still 10 digits (09-prefix)
        "082-2345-223",                                   # odd grouping, still 10 digits (08-prefix)
    ):
        assert phone_problem(text) == "", text
        assert _extract_phone(text), text


# --------------------------------------------------------------------------
# the exact bug reported live: a genuinely 10-digit number was told back to the
# customer as "11 หลัก" (11 digits) — a fabricated reason — because a bare length
# check accepted ANY 9-10 digit run starting with 0, landline or garbage alike, so
# nothing downstream had a real reason to hand the model and it invented one.
# --------------------------------------------------------------------------
def test_a_ten_digit_number_with_an_invalid_prefix_is_named_correctly_not_miscounted():
    assert phone_problem("041-223-4444") == "invalid_prefix"
    assert phone_digits("041-223-4444") == "0412234444"
    assert not _extract_phone("041-223-4444")


def test_more_invalid_prefix_garbage():
    for text in ("013-442-1456", "0134421456", "0512345678", "0712345678"):
        assert phone_problem(text) == "invalid_prefix", text
        assert not _extract_phone(text), text


def test_a_landline_shaped_number_is_too_short_not_accepted():
    """02-xxx-xxxx (Bangkok/provincial landline, 9 digits) is a company/home line, not
    a customer's own mobile — must not be silently accepted as if it were."""
    for text in ("02-123-4567", "021234567"):
        assert phone_problem(text) == "too_short", text
        assert not _extract_phone(text), text


def test_tool_result_names_the_invalid_prefix_reason_not_a_digit_count(db, clinic):
    branch, svc, cust, conv = _setup(db, clinic, "041-223-4444")
    slot = _slot(db, branch)

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "phone": "041-223-4444"})

    assert res["need_contact"] == ["phone number"]
    assert res["phone_problem"] == "invalid_prefix"
    assert res["phone_given"] == "0412234444"
    assert "11 หลัก" not in res["say_it_like"]        # the fabricated reason must be gone
    assert "06, 08 หรือ 09" in res["say_it_like"]
    assert "NEVER tell them the number was saved" in res["phone_note"]
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 0


def test_intl_prefix_with_the_leading_zero_mistakenly_kept_is_still_recognised():
    """+66912345678 is the correct international form (0 dropped). A customer who just
    prepends +66 to what they normally type keeps the 0 too ("+660912345678") — same
    number, common mistake. That kept 0 sits directly after "+66"'s own digits, so the
    lookbehind that (rightly) refuses to start a match mid-digit-run also blocked this
    genuine one: it was previously invisible to BOTH _extract_phone and phone_problem,
    silently treated as if the customer had said nothing resembling a phone at all —
    worse than being told the wrong reason, since no reason was given at all."""
    assert _extract_phone("+660931112345") == "0931112345"
    assert phone_problem("+660931112345") == ""
    # the malformed-number path must still work through the same normalisation
    assert phone_problem("+66021234567") == "too_short"     # kept-0 landline, 9 digits
    assert phone_digits("+66021234567") == "021234567"


def test_checklist_hint_names_the_invalid_prefix_reason(db, clinic):
    _branch, _svc, cust, conv = _setup(db, clinic, "041-223-4444")

    hint = _booking_hint(db, conv, cust)
    assert "0412234444" in hint
    assert "not a valid Thai mobile number" in hint
    assert "did NOT store it" in hint


def test_checklist_hint_hands_over_the_exact_sentence_to_say(db, clinic):
    """Told only the FACT in prose, the model would still paraphrase it (a live check
    found it sometimes stated the wrong digit count, sometimes reverted to the "a Thai
    phone number has 10 digits" framing this wording deliberately drops) — so the hint
    must carry the SAME finished sentence tools.py::_phone_rejection would give after a
    tool call, not a description the model is left to word itself."""
    from app.ai.sales import phone_rejection_say_it_like

    _branch, _svc, cust, conv = _setup(db, clinic, "093-444-444")
    hint = _booking_hint(db, conv, cust)
    say_it_like, say_it_like_en = phone_rejection_say_it_like("too_short", "093444444")
    assert say_it_like in hint
    assert say_it_like_en in hint
    assert "Say EXACTLY this, word for word" in hint


def test_times_dates_and_prices_are_not_read_as_phone_numbers():
    for text in ("พรุ่งนี้ 09:00 น.", "วันที่ 5 สิงหาคม 2026", "ราคา 5,000 บาท", "มัดจำ 500"):
        assert phone_problem(text) == "", text


# --------------------------------------------------------------------------
# the tool result
# --------------------------------------------------------------------------
def test_an_over_long_number_says_how_many_digits_it_had(db, clinic):
    branch, svc, cust, conv = _setup(db, clinic, "09545626666")
    slot = _slot(db, branch)

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "phone": "09545626666"})

    assert res["need_contact"] == ["phone number"]
    assert res["phone_problem"] == "too_long"
    assert res["phone_given"] == "09545626666"
    assert "11 หลัก" in res["say_it_like"] and "10 หลัก" in res["say_it_like"]
    assert "NEVER tell them the number was saved" in res["phone_note"]
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 0


def test_too_short_and_too_long_just_state_the_count_not_a_rule(db, clinic):
    """States the digit count plainly ("X หลัก, ไม่ครบ/เกิน 10 หลัก") instead of reciting
    "เบอร์โทรของไทยมี 10 หลัก" as a standing rule — the customer typed something wrong
    right now, which is what needs pointing out, not a policy statement."""
    branch, svc, cust, conv = _setup(db, clinic, "093-444-444")
    slot = _slot(db, branch)

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "phone": "093-444-444"})
    assert res["phone_problem"] == "too_short"
    assert res["say_it_like"] == "เบอร์ 093444444 มี 9 หลักค่ะ ไม่ครบ 10 หลัก รบกวนส่งมาอีกครั้งนะคะ"
    assert "เบอร์โทรของไทยมี 10 หลัก" not in res["say_it_like"]

    branch2, svc2, cust2, conv2 = _setup(db, clinic, "09545626666", name="สอง")
    slot2 = _slot(db, branch2)
    res2 = execute_tool(db, conv2, cust2, "book_appointment", {
        "treatment": svc2.name, "date": slot2.strftime("%Y-%m-%d"),
        "time": slot2.strftime("%H:%M"), "phone": "09545626666"})
    assert res2["phone_problem"] == "too_long"
    assert res2["say_it_like"] == "เบอร์ 09545626666 มี 11 หลักค่ะ เกิน 10 หลัก รบกวนส่งมาอีกครั้งนะคะ"
    assert "เบอร์โทรของไทยมี 10 หลัก" not in res2["say_it_like"]


def test_the_reason_is_found_even_when_the_model_passes_no_phone(db, clinic):
    """The customer typed it; the model just didn't relay it."""
    branch, svc, cust, conv = _setup(db, clinic, "เบอร์ 09545626666 ค่ะ")
    slot = _slot(db, branch)

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M")})
    assert res["phone_problem"] == "too_long"


def test_no_phone_at_all_carries_no_invented_reason(db, clinic):
    """Saying "your number is too long" to someone who never gave one would be worse
    than saying nothing."""
    branch, svc, cust, conv = _setup(db, clinic, "สนใจ Signature Facial ค่ะ")
    slot = _slot(db, branch)

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M")})
    assert res["need_contact"] == ["phone number"]
    assert "phone_problem" not in res
    assert "say_it_like" not in res


def test_a_valid_number_is_stored_and_the_booking_proceeds(db, clinic):
    branch, svc, cust, conv = _setup(db, clinic, "0954562666")
    slot = _slot(db, branch)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                          text="ต้องการชำระมัดจำหรือชำระเต็มจำนวนคะ"))
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="มัดจำค่ะ"))
    db.commit()

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "phone": "0954562666",
        "payment_type": "deposit", "payment_said": "มัดจำค่ะ"})
    assert "need_contact" not in res
    db.refresh(cust)
    assert cust.phone == "0954562666"


# --------------------------------------------------------------------------
# phone declined — the customer said outright, after being asked, that they have none
# --------------------------------------------------------------------------
def test_customer_who_confirms_no_phone_can_book_without_one(db, clinic):
    branch, svc, cust, conv = _setup(db, clinic)
    slot = _slot(db, branch)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                          text="ขอชื่อและเบอร์โทรสำหรับการจองด้วยนะคะ"))
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="customer",
                          text="ไม่มีเบอร์ค่ะ"))
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                          text="ต้องการชำระมัดจำหรือชำระเต็มจำนวนคะ"))
    db.commit()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="มัดจำค่ะ"))
    db.commit()

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "no_phone_said": "ไม่มีเบอร์ค่ะ",
        "payment_type": "deposit", "payment_said": "มัดจำค่ะ"})
    assert "need_contact" not in res
    db.refresh(cust)
    assert cust.phone_declined is True
    assert cust.phone == ""
    assert db.query(models.Booking).filter_by(clinic_id=clinic.id).count() == 1


def test_no_phone_said_the_model_invented_is_ignored(db, clinic):
    """``no_phone_said`` passed by the model, but the customer never actually said
    anything decline-shaped — must stay blocked, same as an invented branch/payment
    choice (see ``_branch_said_by_customer`` / ``_payment_choice_by_customer``)."""
    branch, svc, cust, conv = _setup(db, clinic, "สนใจ Signature Facial ค่ะ")
    slot = _slot(db, branch)
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="ai",
                          text="ขอชื่อและเบอร์โทรสำหรับการจองด้วยนะคะ"))
    db.commit()

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "no_phone_said": "ไม่มีเบอร์ค่ะ"})
    assert res["need_contact"] == ["phone number"]
    db.refresh(cust)
    assert cust.phone_declined is False


def test_no_phone_said_before_ever_asking_is_not_a_decline(db, clinic):
    """A bare "ไม่มี" about something else entirely, with no prior phone-ask anywhere
    in the transcript, must not be read as declining a phone number."""
    branch, svc, cust, conv = _setup(db, clinic, "ไม่มีโปรโมชั่นอื่นแล้วหรอคะ")
    slot = _slot(db, branch)

    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"),
        "time": slot.strftime("%H:%M"), "no_phone_said": "ไม่มีโปรโมชั่นอื่นแล้วหรอคะ"})
    assert res["need_contact"] == ["phone number"]
    db.refresh(cust)
    assert cust.phone_declined is False


def test_booking_hint_states_the_phone_was_confirmed_declined(db, clinic):
    branch, svc, cust, conv = _setup(db, clinic)
    cust.phone_declined = True
    db.commit()

    hint = _booking_hint(db, conv, cust)
    assert "confirmed they have none" in hint
    assert "write '-' for phone" in hint
    assert "NOT on file — ask for it before the booking summary" not in hint


# --------------------------------------------------------------------------
# the checklist hint — the line that let the assistant claim it had saved it
# --------------------------------------------------------------------------
def test_the_checklist_says_the_number_was_not_stored(db, clinic):
    _branch, _svc, cust, conv = _setup(db, clinic, "09545626666")

    hint = _booking_hint(db, conv, cust)
    assert "09545626666" in hint and "11 digits" in hint
    assert "did NOT store it" in hint
    assert "Do NOT say it was saved" in hint


def test_the_checklist_still_reads_a_good_number_off_the_transcript(db, clinic):
    _branch, _svc, cust, conv = _setup(db, clinic, "เบอร์ 0954562666 ค่ะ")

    hint = _booking_hint(db, conv, cust)
    assert "already TYPED it" in hint
    assert "095-456-2666" in hint      # standard grouped form, not the raw typed digits
    assert _extract_phone("0954562666") == "0954562666"


# --------------------------------------------------------------------------
# saying the number back — a summary must show the standard grouped form, never
# whatever raw shape the customer happened to type it in (a "+66" prefix, no
# dashes, unusual spacing)
# --------------------------------------------------------------------------
def test_format_thai_mobile_groups_as_0xx_xxx_xxxx():
    assert format_thai_mobile("0911234567") == "091-123-4567"
    assert format_thai_mobile("0812345678") == "081-234-5678"
    assert format_thai_mobile("123") == "123"          # not a real 10-digit number: unchanged


def test_checklist_hint_gives_the_grouped_form_for_a_number_typed_with_plus_66(db, clinic):
    """The exact bug reported live: a customer typed "+660911234567" (kept the leading
    0 after +66 — a common mistake, still a genuine number), and the assistant copied
    that raw text straight into "บันทึกเบอร์ ... ให้แล้ว" and the booking summary."""
    _branch, _svc, cust, conv = _setup(db, clinic, "+660911234567")

    hint = _booking_hint(db, conv, cust)
    assert "091-123-4567" in hint
    assert "+660911234567" not in hint
    assert "never their raw typed text" in hint


def test_checklist_hint_gives_the_grouped_form_once_the_number_is_on_file(db, clinic):
    _branch, _svc, cust, conv = _setup(db, clinic)
    cust.phone = "0911234567"
    db.commit()

    hint = _booking_hint(db, conv, cust)
    assert "KNOWN = 0911234567" in hint      # the raw stored value, unchanged
    assert "091-123-4567" in hint            # but the model is told to SAY the grouped form
    assert "never the customer's own typed formatting" in hint


def test_playbook_prompt_defers_to_the_checklist_for_phone_validity():
    """A customer who volunteers a phone number before anything else has been asked
    (no treatment or branch chosen yet) still got told an invalid landline-shaped
    number was saved: the general "confirm it is saved" contact-details rule has no
    validity check of its own and, on that turn, overrode the per-number check the
    booking checklist hint (_booking_hint) actually carries. The playbook must state
    this rule does not win over the checklist's phone-validity line."""
    from app.ai import prompts

    assert "does NOT override the booking checklist status" in prompts._PLAYBOOK
    assert "never claim it was saved" in prompts._PLAYBOOK


def test_playbook_name_and_phone_bullet_also_defers_to_checklist_validity():
    """The SAME failure, worse: a customer who answers the checklist's own combined
    "name and phone" question with an invalid number got told it was saved and was
    handed a full booking summary — this time from the booking-flow-specific "Name and
    phone" bullet, not the general contact-details one (test above). This can happen even
    immediately after the tool had correctly rejected a DIFFERENT bad number earlier in
    the same conversation, so this bullet's own "confirm it is saved... even when the
    very next thing you send is the booking summary" instruction must be conditional on
    validity too, not just the general rule's."""
    from app.ai import prompts

    assert "conditional on the phone number actually being" in prompts._PLAYBOOK
    assert "do not send a summary" in prompts._PLAYBOOK
