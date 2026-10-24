"""Tests for the running conversation summary (Conversation.ai_summary).

analyze() now persists the LLM's Thai summary on EVERY call (not only at
escalation time), never wipes an existing summary when the LLM is
unavailable/failed, and the summary is exposed on the conversation list
payload + every realtime {type:'conversation'} event via conv_summary().
"""
import json
from types import SimpleNamespace

from app import models
from app.ai import sales
from app.services import inbox

THAI_SUMMARY = "ลูกค้าสนใจโบท็อกซ์ รอเลือกวันนัด"


def _setup_conversation(db, clinic):
    cust = models.Customer(clinic_id=clinic.id, name="A", channel="web",
                           channel_user_id="w1")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.flush()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                          sender="customer", text="สนใจโบท็อกซ์ค่ะ ราคาเท่าไหร่"))
    db.commit()
    return cust, conv


def _stub_llm(monkeypatch, payload: dict):
    """Point the sales-module names (from-imported!) at a canned LLM response."""
    resp = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(sales, "is_configured", lambda: True)
    monkeypatch.setattr(sales, "chat_completion", lambda *a, **kw: resp)


def test_analyze_writes_running_summary_without_escalation(db, clinic, monkeypatch):
    """The summary persists on a plain positive conversation — no escalation needed."""
    _cust, conv = _setup_conversation(db, clinic)
    _stub_llm(monkeypatch, {"summary": THAI_SUMMARY, "sentiment": "positive",
                            "buying_intent": "medium", "intent": "pricing"})
    sales.analyze(db, conv)
    db.refresh(conv)
    assert conv.ai_summary == THAI_SUMMARY
    assert not conv.escalation_reason  # summary no longer rides on escalation


def test_analyze_updates_summary_even_after_escalation_froze_the_reason(db, clinic, monkeypatch):
    """escalation_reason freezes at first set; the summary keeps rolling forward."""
    _cust, conv = _setup_conversation(db, clinic)
    conv.escalation_reason = "old reason"
    conv.ai_summary = "old summary"
    db.commit()
    _stub_llm(monkeypatch, {"summary": THAI_SUMMARY, "sentiment": "negative",
                            "buying_intent": "low", "intent": "complaint"})
    sales.analyze(db, conv)
    db.refresh(conv)
    assert conv.ai_summary == THAI_SUMMARY
    assert conv.escalation_reason == "old reason"


def test_analyze_never_wipes_summary_when_llm_unavailable(db, clinic):
    """is_configured() is False in tests → signals={} → the old summary survives."""
    _cust, conv = _setup_conversation(db, clinic)
    conv.ai_summary = "เดิม"
    db.commit()
    sales.analyze(db, conv)
    db.refresh(conv)
    assert conv.ai_summary == "เดิม"


def test_analyze_ignores_blank_summary_from_llm(db, clinic, monkeypatch):
    """A whitespace-only summary from the LLM must not blank the stored one."""
    _cust, conv = _setup_conversation(db, clinic)
    conv.ai_summary = "เดิม"
    db.commit()
    _stub_llm(monkeypatch, {"summary": "   ", "sentiment": "neutral",
                            "buying_intent": "low", "intent": "greeting"})
    sales.analyze(db, conv)
    db.refresh(conv)
    assert conv.ai_summary == "เดิม"


def test_summary_is_truncated_to_500_chars(db, clinic, monkeypatch):
    _cust, conv = _setup_conversation(db, clinic)
    _stub_llm(monkeypatch, {"summary": "ก" * 900, "sentiment": "positive",
                            "buying_intent": "low", "intent": "other"})
    sales.analyze(db, conv)
    db.refresh(conv)
    assert conv.ai_summary == "ก" * 500


def test_conv_summary_and_list_payload_include_ai_summary(db, clinic, auth_client):
    """conv_summary() (list rows + realtime events) carries ai_summary."""
    _cust, conv = _setup_conversation(db, clinic)
    conv.ai_summary = THAI_SUMMARY
    db.commit()

    row = inbox.conv_summary(db, conv)
    assert row["ai_summary"] == THAI_SUMMARY

    r = auth_client.get("/api/conversations")
    assert r.status_code == 200, r.text
    rows = r.json()
    mine = next(x for x in rows if x["id"] == conv.id)
    assert mine["ai_summary"] == THAI_SUMMARY


def test_conv_summary_defaults_to_empty_string(db, clinic):
    """A fresh conversation with no summary yet still carries the key (as '')."""
    _cust, conv = _setup_conversation(db, clinic)
    assert inbox.conv_summary(db, conv)["ai_summary"] == ""
