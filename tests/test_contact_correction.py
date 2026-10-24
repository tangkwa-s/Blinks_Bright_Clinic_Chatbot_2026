"""A customer correcting a detail must actually change their profile.

Reported: the customer typed "บอกเบอร์ผิดครับ 0922222222", the AI answered "บันทึกเบอร์
ใหม่ 0922222222 ให้แล้วนะคะ", and the CRM went on showing 0911111111. Two things were
happening at once — sales.analyze read the customer's messages as ONE string and took
the FIRST phone in it (always the typo), and because analyze runs AFTER
book_appointment has saved the corrected number, it actively put the wrong one back.
"""
from app import models
from app.ai import sales


def _conversation(db, clinic, name="สมปอง", phone="", channel="web"):
    cust = models.Customer(clinic_id=clinic.id, name=name, phone=phone, channel=channel)
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel=channel)
    db.add(conv)
    db.commit()
    return conv, cust


def _say(db, conv, text, sender="customer"):
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender=sender, text=text))
    db.commit()


# --------------------------------------------------------------------------
# phone
# --------------------------------------------------------------------------
def test_a_corrected_phone_replaces_the_first_one(db, clinic):
    """The reported case, end to end."""
    conv, cust = _conversation(db, clinic)
    _say(db, conv, "เบอร์ 0911111111 ครับ")
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.phone == "0911111111"

    _say(db, conv, "บอกเบอร์ผิดครับ 0922222222")
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.phone == "0922222222"


def test_analyze_does_not_revert_what_book_appointment_saved(db, clinic):
    """book_appointment saves the corrected number, then analyze runs. It used to
    overwrite it with the typo from the top of the transcript."""
    conv, cust = _conversation(db, clinic)
    _say(db, conv, "เบอร์ 0911111111 ครับ")
    _say(db, conv, "บอกเบอร์ผิดครับ 0922222222")
    cust.phone = "0922222222"                     # as _capture_contact left it
    db.commit()

    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.phone == "0922222222"


def test_a_later_message_without_a_phone_keeps_the_last_one_given(db, clinic):
    conv, cust = _conversation(db, clinic)
    _say(db, conv, "เบอร์ 0911111111 ครับ")
    _say(db, conv, "บอกเบอร์ผิดครับ 0922222222")
    _say(db, conv, "ขอบคุณครับ")

    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.phone == "0922222222"


def test_international_form_still_works(db, clinic):
    conv, cust = _conversation(db, clinic)
    _say(db, conv, "เบอร์ 0911111111 ครับ")
    _say(db, conv, "ขอแก้เป็น +66 92 222 2222 ครับ")

    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.phone == "0922222222"


def test_the_ais_own_message_never_supplies_the_phone(db, clinic):
    """Only what the CUSTOMER typed counts — the AI echoes numbers back constantly."""
    conv, cust = _conversation(db, clinic)
    _say(db, conv, "เบอร์ 0911111111 ครับ")
    _say(db, conv, "ยืนยันเบอร์ 0999999999 นะคะ", sender="ai")

    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.phone == "0911111111"


# --------------------------------------------------------------------------
# email
# --------------------------------------------------------------------------
def test_a_corrected_email_replaces_the_first_one(db, clinic):
    conv, cust = _conversation(db, clinic)
    _say(db, conv, "อีเมล somchai@example.com ครับ")
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.email == "somchai@example.com"

    _say(db, conv, "พิมพ์ผิดครับ sompong@example.com")
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.email == "sompong@example.com"


# --------------------------------------------------------------------------
# name — comes from the LLM signal, so the model call is stubbed and the REAL
# extraction path (verbatim check + self-id cue + overwrite) still runs
# --------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, payload):
        import json
        self.choices = [type("C", (), {"message": type("M", (), {"content": json.dumps(payload)})})]
        self.usage = None


def _stub_llm(monkeypatch, payload):
    monkeypatch.setattr(sales, "is_configured", lambda: True)
    monkeypatch.setattr(sales, "chat_completion", lambda *a, **k: _FakeResp(payload))


def test_a_typo_the_customer_fixes_does_not_become_their_nickname(db, clinic, monkeypatch):
    """สมปอแง -> สมปอง. The old value was THEIR OWN typing, so it is a correction:
    keeping it as the nickname would leave the typo in the profile, and the assistant
    addresses people by nickname, so it would go on calling them "คุณสมปอแง"."""
    conv, cust = _conversation(db, clinic, name="Web Visitor")
    _say(db, conv, "ชื่อ สมปอแง ครับ")
    _stub_llm(monkeypatch, {"customer_name": "สมปอแง"})
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.name == "สมปอแง"

    _say(db, conv, "ขอโทษครับ พิมพ์ผิด ชื่อ สมปอง")
    _stub_llm(monkeypatch, {"customer_name": "สมปอง"})
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.name == "สมปอง"
    assert not (cust.nickname or "")           # the typo is gone, not filed as a nickname


def test_a_web_channel_name_does_not_become_the_nickname(db, clinic, monkeypatch):
    """The bug this guards: web_start (public, unauthenticated) and the test console
    both accept ANY client-supplied string as the initial customer name — unlike LINE,
    nothing verifies it. A visitor who opened chat as "'or 1'=1" and later stated a real
    name had "'or 1'=1" promoted to nickname, and the prompt's "address them by
    nickname" rule then had the assistant tell them their own name was "or 1'=1" —
    correct per the data, but the data was never a real nickname to begin with."""
    conv, cust = _conversation(db, clinic, name="'or 1'=1", channel="web")
    _say(db, conv, "ต่อไปนี้ฉันชื่อสมชายนะ")
    _stub_llm(monkeypatch, {"customer_name": "สมชาย"})
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.name == "สมชาย"
    assert not (cust.nickname or "")


def test_a_name_the_customer_never_typed_is_rejected(db, clinic, monkeypatch):
    """The verbatim guard still holds: a name only the model produced is ignored."""
    conv, cust = _conversation(db, clinic, name="Web Visitor")
    _say(db, conv, "ผมชื่อสมปองครับ")
    _stub_llm(monkeypatch, {"customer_name": "Somchai Jaidee"})
    sales.analyze(db, conv)
    db.refresh(cust)
    assert cust.name == "Web Visitor"


def test_the_analysis_prompt_asks_for_the_LATEST_name():
    """The DB side handles a corrected name fine — what failed was upstream: the
    analysis prompt never said which of several stated names to return, so the model
    kept handing back the FIRST one and the correction never differed from what was
    already stored. Nothing else can pin this, so pin the instruction itself."""
    from app.ai.sales import ANALYSIS_PROMPT

    assert "THE LATEST ONE WINS" in ANALYSIS_PROMPT
    assert "a correction replaces what it corrects" in ANALYSIS_PROMPT
    assert "MOST RECENT" in ANALYSIS_PROMPT
