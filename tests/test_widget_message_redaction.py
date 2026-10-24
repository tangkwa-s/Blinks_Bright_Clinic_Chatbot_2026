"""The AI's raw reference/grounding trail (app/ai/chat.py::respond -> meta.grounding,
surfaced to staff via app/services/inbox.py::msg_dict) is staff-only.

msg_dict() has no notion of who's asking — it's the SAME serializer used by the
staff-only inbox (app/routers/conversations.py, session-cookie auth) and the public,
unauthenticated chat-widget endpoints (app/routers/channels.py: web_start,
web_messages, chat-stream). Without an explicit redaction step at the public
boundary, the widget would ship internal catalog prices, verbatim admin message
text, and raw tool-call JSON straight into the customer's own browser.
"""
from app import models
from app.security import make_chat_token


def test_web_messages_hides_grounding_but_staff_conversation_view_shows_it(db, auth_client):
    cid = auth_client.test_clinic.id
    cust = models.Customer(clinic_id=cid, name="Widget Visitor", channel="web",
                           channel_user_id="web_redact_1")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=cid, customer_id=cust.id, channel="web")
    db.add(conv)
    db.flush()
    ai_msg = models.Message(clinic_id=cid, conversation_id=conv.id, sender="ai",
                            text="ราคาเริ่มต้น 8,900 บาทค่ะ",
                            meta={"grounded": True, "grounding": "secret catalog data + staff chat"})
    db.add(ai_msg)
    db.commit()

    token = make_chat_token(conv.id)
    widget = auth_client.get(f"/api/channels/web/messages?token={token}").json()
    assert widget["messages"], "expected at least the AI message"
    for m in widget["messages"]:
        assert "grounding" not in m

    staff = auth_client.get(f"/api/conversations/{conv.id}").json()
    ai_rows = [m for m in staff["messages"] if m["sender"] == "ai"]
    assert ai_rows and ai_rows[0]["grounding"] == "secret catalog data + staff chat"


def test_web_start_greeting_never_carries_grounding(db, auth_client):
    """web_start's own canned greeting message never has meta.grounding (it isn't an
    AI-generated reply), but the redaction wrapper must be safe to call regardless —
    exercises _customer_safe on a message with no grounding key at all."""
    r = auth_client.post("/api/channels/web/start", json={"clinic": auth_client.test_clinic.slug})
    assert r.status_code == 200, r.text
    for m in r.json()["messages"]:
        assert "grounding" not in m
