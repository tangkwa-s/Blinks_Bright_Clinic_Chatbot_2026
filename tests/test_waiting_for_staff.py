"""While the AI is paused for a person, the customer is told so.

The analysis model flagged "needs a human" whenever the AI did not know something (a
doctor it had no record of), and that flag paused the AI. The pause note is a system
message the widget hides, so the customer kept typing into a chat nobody answered until
someone pressed Return to AI. Now:

- "needs a human" flags the inbox but leaves the AI replying; only a medical concern
  pauses it, and then the customer is told the team is taking over;
- any message that arrives while the AI is paused gets one "the team has your message"
  notice per wait, none once a staff member is answering;
- that notice is not an answer, so the stale-takeover sweep still hands the chat back.
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from app import models
from app.ai import sales
from app.services import inbox


def _conv(db, clinic, *, ai_enabled=True):
    cust = models.Customer(clinic_id=clinic.id, name="ลูกค้า", channel="web",
                           channel_user_id="w1")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               ai_enabled=ai_enabled, last_message_at=datetime.utcnow())
    db.add(conv)
    db.commit()
    return conv


def _say(db, conv, sender, text, meta=None):
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender=sender, text=text, meta=meta or {}))
    db.commit()


def _notices(db, conv):
    db.expire_all()
    return [m.text for m in db.query(models.Message).filter_by(conversation_id=conv.id)
            .order_by(models.Message.id) if (m.meta or {}).get("waiting_notice")]


def _stub_llm(monkeypatch, payload):
    resp = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(sales, "is_configured", lambda: True)
    monkeypatch.setattr(sales, "chat_completion", lambda *a, **kw: resp)


def test_not_knowing_something_flags_the_inbox_but_keeps_the_ai_replying(
        db, make_clinic, monkeypatch):
    conv = _conv(db, make_clinic())
    _say(db, conv, "customer", "วาเป็นแพทย์อยู่สาขาไหน")
    _say(db, conv, "ai", "ขออภัยค่ะ ตอนนี้ยังไม่มีข้อมูลแพทย์ชื่อ วา")
    _stub_llm(monkeypatch, {"needs_human": True, "human_reason": "ตรวจสอบข้อมูลแพทย์ชื่อวา",
                            "sentiment": "neutral", "intent": "doctor"})
    sales.analyze(db, conv)
    db.expire_all()
    c = db.get(models.Conversation, conv.id)
    assert c.ai_enabled is True
    assert "ตรวจสอบข้อมูลแพทย์ชื่อวา" in c.escalation_reason
    assert _notices(db, conv) == []


def test_a_medical_concern_pauses_the_ai_and_tells_the_customer(db, make_clinic, monkeypatch):
    conv = _conv(db, make_clinic())
    word = sales.MEDICAL_WORDS[0]
    _say(db, conv, "customer", f"ทำแล้ว{word}ค่ะ")
    _say(db, conv, "ai", "ขอบคุณที่แจ้งนะคะ")
    _stub_llm(monkeypatch, {"sentiment": "negative", "intent": "complaint"})
    sales.analyze(db, conv)
    db.expire_all()
    assert db.get(models.Conversation, conv.id).ai_enabled is False
    assert _notices(db, conv) == [inbox.HANDOFF_TH]


def test_a_message_while_paused_gets_one_notice_per_wait(db, make_clinic):
    conv = _conv(db, make_clinic(), ai_enabled=False)
    _say(db, conv, "ai", "ขออภัยค่ะ ยังไม่มีข้อมูลค่ะ")
    _say(db, conv, "customer", "สรุปมีไหมคะ")
    inbox.generate_ai_reply(conv.id)
    assert _notices(db, conv) == [inbox.WAITING_TH]
    _say(db, conv, "customer", "ฮัลโหล")
    inbox.generate_ai_reply(conv.id)
    assert _notices(db, conv) == [inbox.WAITING_TH], "once per wait, not per message"


def test_no_notice_once_a_staff_member_is_answering(db, make_clinic):
    conv = _conv(db, make_clinic(), ai_enabled=False)
    _say(db, conv, "ai", "ขออภัยค่ะ")
    _say(db, conv, "admin", "สวัสดีค่ะ แอดมินเองค่ะ")
    _say(db, conv, "customer", "ค่ะ")
    inbox.generate_ai_reply(conv.id)
    assert _notices(db, conv) == []


def test_the_notice_is_in_english_for_an_english_chat(db, make_clinic):
    conv = _conv(db, make_clinic(), ai_enabled=False)
    _say(db, conv, "customer", "Which branch is Dr. Wa at?")
    inbox.generate_ai_reply(conv.id)
    assert _notices(db, conv) == [inbox.WAITING_EN]


def test_the_notice_does_not_stop_the_stale_takeover_sweep(db, make_clinic, monkeypatch):
    clinic = make_clinic()
    conv = _conv(db, clinic, ai_enabled=False)
    _say(db, conv, "customer", "สรุปมีไหมคะ")
    inbox.generate_ai_reply(conv.id)
    assert _notices(db, conv) == [inbox.WAITING_TH]
    replied = []
    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: replied.append(cid))
    later = datetime.utcnow() + timedelta(hours=1)
    assert inbox.sweep_stale_takeovers(db, clinic.id, now=later) == 1
    assert replied == [conv.id]
    db.expire_all()
    assert db.get(models.Conversation, conv.id).ai_enabled is True
