"""app/ai/chat.py::respond persists its raw `grounding` string (KB context, catalog
prices, admin messages, every tool call's JSON result) into the returned meta, so a
hallucinated reply can be debugged later (see app/services/inbox.py::msg_dict and
tests/test_widget_message_redaction.py for the staff-only exposure of this field).

No existing fixture stubs app/ai/chat.py's own streaming chat_completion() call (the
_stub_llm pattern in test_contact_correction.py/test_conversation_summary.py targets
app.ai.sales's non-streaming call shape), so this builds a small fake chunk-stream:
the first call yields a tool-call chunk for list_treatments (a real, read-only,
no-required-argument tool), forcing the actual tool-loop branch to run and genuinely
append the tool's JSON result to `grounding`; the second call yields plain content,
ending the loop normally.
"""
from types import SimpleNamespace

from app import models
from app.ai import chat as C


def _content_chunk(text):
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=delta)])


def _tool_call_chunk(call_id, name, arguments):
    tc = SimpleNamespace(index=0, id=call_id,
                         function=SimpleNamespace(name=name, arguments=arguments))
    delta = SimpleNamespace(content=None, tool_calls=[tc])
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=delta)])


def test_respond_persists_a_real_grounding_trail(db, clinic, monkeypatch):
    cust = models.Customer(clinic_id=clinic.id, name="Ground Test", channel="web",
                           channel_user_id="ground-test-1")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.flush()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="customer",
                          text="มีทรีตเมนต์อะไรบ้างคะ"))
    db.commit()

    calls = []

    def _fake_chat_completion(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return [_tool_call_chunk("call_1", "list_treatments", "{}")]
        return [_content_chunk("มีหลายทรีตเมนต์ให้เลือกค่ะ")]

    monkeypatch.setattr(C, "is_configured", lambda: True)
    monkeypatch.setattr(C, "chat_completion", _fake_chat_completion)

    result = C.respond(db, conv)

    assert len(calls) == 2, "expected the tool-call turn, then the follow-up reply turn"
    grounding = result["meta"]["grounding"]
    assert grounding
    # list_treatments' own JSON result (not just its name) must be in the trail —
    # "price_from" is the field it always sets per treatment.
    assert "price_from" in grounding


def test_respond_truncates_an_oversized_grounding_trail_keeping_the_tail(db, clinic, monkeypatch):
    """Tool results are appended LAST and are the most specific evidence for a claim,
    so truncation must keep the tail, not the head, and must say so visibly.

    Pads the STATIC preamble (kb_context + catalog_prices + admin messages +
    _contact_grounding — built first, chat.py:870-875) past the cap with an oversized
    admin message, rather than an oversized tool argument: a garbage tool argument risks
    the tool's own filtering logic (list_treatments matches `category` as a substring)
    legitimately returning nothing, which would prove nothing about truncation direction.
    """
    cust = models.Customer(clinic_id=clinic.id, name="Ground Test 2", channel="web",
                           channel_user_id="ground-test-2")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.flush()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="customer",
                          text="มีทรีตเมนต์อะไรบ้างคะ"))
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="admin",
                          text="PADDING_" + "A" * (C.GROUNDING_TRAIL_MAX_CHARS + 1000)))
    db.commit()

    calls = []

    def _fake_chat_completion(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return [_tool_call_chunk("call_1", "list_treatments", "{}")]
        return [_content_chunk("มีหลายทรีตเมนต์ให้เลือกค่ะ")]

    monkeypatch.setattr(C, "is_configured", lambda: True)
    monkeypatch.setattr(C, "chat_completion", _fake_chat_completion)

    result = C.respond(db, conv)
    grounding = result["meta"]["grounding"]
    assert grounding.startswith("…[earlier grounding trail truncated]…")
    assert "price_from" in grounding        # the tool's real evidence (appended LAST) survives
    assert "PADDING_" not in grounding      # the oversized static preamble (built FIRST) is cut
