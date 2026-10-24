"""A human takeover DURING AI generation must keep the in-flight reply away from the
customer, without losing it.

generate_ai_reply read ``ai_enabled`` once, before calling the model. The takeover route
flips it from another session, so for the whole of a 5-15 second generation the flag in
hand said True while the row said False — and the finished reply was persisted, streamed
and delivered on top of whatever the human had just typed. Seen in a live run: the admin
took over and quoted a negotiated ฿4,500; three seconds later the AI's answer arrived
underneath with the ฿25,000 standard price.

Now the flag is re-read from the DB after the model returns. If the AI is off by then the
text is withheld from the customer but handed to the admin as a ``system`` note (the
widget hides system messages; the inbox shows them), so a payment link or booking the
model produced in that turn is never silently lost, and the partial stream bubble is
withdrawn with a ``stream_cancel`` event.
"""
from app import models, realtime
from app.database import SessionLocal
from app.services import inbox


def _conversation(db, clinic):
    cust = models.Customer(clinic_id=clinic.id, name="มิ้นท์", channel="web",
                           channel_user_id="w-mid", phone="0955555555")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               ai_enabled=True)
    db.add(conv)
    db.flush()
    db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id, sender="customer",
                          text="HIFU ราคาเท่าไหร่คะ"))
    db.commit()
    return conv


def _fake_respond(*, takeover_mid_way: bool, reply: str):
    """Stand in for app.ai.chat.respond. Optionally flips ai_enabled from ANOTHER
    session while 'generating' — exactly what the takeover route does."""
    def respond(db, conversation, on_token=None):
        if on_token:
            on_token(reply[:20])          # a partial bubble has already been streamed
        if takeover_mid_way:
            other = SessionLocal()
            try:
                row = other.get(models.Conversation, conversation.id)
                row.ai_enabled = False
                other.commit()
            finally:
                other.close()
        return {"text": reply, "meta": {"grounded": True, "kb": [], "tools": ["list_treatments"]}}
    return respond


def _msgs(db, conv_id):
    return (db.query(models.Message).filter_by(conversation_id=conv_id)
            .order_by(models.Message.id).all())


def test_reply_finished_after_a_takeover_is_withheld_and_left_for_the_admin(
        db, clinic, monkeypatch):
    from app.ai import chat as C
    from app.ai import sales as S

    conv = _conversation(db, clinic)
    monkeypatch.setattr(C, "respond", _fake_respond(takeover_mid_way=True,
                                                     reply="HIFU Lifting ราคา 25,000 บาทค่ะ"))
    monkeypatch.setattr(S, "analyze", lambda db, conv: None)
    _events, start = realtime.events_since(0)

    inbox.generate_ai_reply(conv.id)

    db.expire_all()
    msgs = _msgs(db, conv.id)
    assert [m.sender for m in msgs] == ["customer", "system"], [m.sender for m in msgs]
    note = msgs[-1]
    assert "withheld" in note.text and "NOT sent" in note.text
    assert "HIFU Lifting ราคา 25,000 บาทค่ะ" in note.text, "the draft travels with the note"
    assert note.meta.get("suppressed") is True
    # the partial bubble the widget streamed is withdrawn
    events, _ = realtime.events_since(start)
    kinds = [e["type"] for e in events if e.get("conversation_id") == conv.id]
    assert "stream_cancel" in kinds, kinds
    assert not any(e["type"] == "message" and e["message"]["sender"] == "ai" for e in events
                   if e.get("conversation_id") == conv.id), "no AI message reached the thread"
    # and it is explainable from the Test Console
    ev = (db.query(models.WebhookEvent).filter_by(clinic_id=clinic.id,
                                                 event_type="reply_suppressed")
          .order_by(models.WebhookEvent.id.desc()).first())
    assert ev is not None and "during AI generation" in (ev.note or "")


def test_without_a_takeover_the_reply_is_delivered_as_before(db, clinic, monkeypatch):
    from app.ai import chat as C
    from app.ai import sales as S

    conv = _conversation(db, clinic)
    monkeypatch.setattr(C, "respond", _fake_respond(takeover_mid_way=False,
                                                     reply="HIFU Lifting ราคา 25,000 บาทค่ะ"))
    monkeypatch.setattr(S, "analyze", lambda db, conv: None)

    inbox.generate_ai_reply(conv.id)

    db.expire_all()
    msgs = _msgs(db, conv.id)
    assert [m.sender for m in msgs] == ["customer", "ai"]
    assert msgs[-1].text == "HIFU Lifting ราคา 25,000 บาทค่ะ"


def test_the_widget_stream_whitelist_lets_the_cancel_through():
    """chat_ws forwards only a fixed set of event types to the customer's widget; a
    cancel that never reaches it would leave the half-written bubble on screen."""
    import inspect
    from app.routers import channels

    src = inspect.getsource(channels.chat_ws)
    assert '"stream_cancel"' in src
