"""An admin may only reply to a customer AFTER taking the conversation over.

While `Conversation.ai_enabled` is true the AI owns the thread; a human reply
sent then would race the AI's own answer to the same customer. The composer is
disabled in the UI and the server rejects the post with 409 `takeover_required`.
"""
from app import models


def _conversation(db, clinic):
    cust = models.Customer(clinic_id=clinic.id, name="A", channel="web",
                           channel_user_id="w1")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.commit()
    return conv


def test_post_message_rejected_while_ai_enabled(db, clinic, auth_client):
    conv = _conversation(db, clinic)
    r = auth_client.post(f"/api/conversations/{conv.id}/messages", json={"text": "hi"})
    assert r.status_code == 409
    assert r.json()["detail"] == "takeover_required"
    assert db.query(models.Message).filter_by(conversation_id=conv.id).count() == 0


def test_post_message_allowed_after_takeover(db, clinic, auth_client):
    conv = _conversation(db, clinic)
    assert auth_client.post(f"/api/conversations/{conv.id}/takeover").status_code == 200

    r = auth_client.post(f"/api/conversations/{conv.id}/messages", json={"text": "hi"})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "hi"

    db.expire_all()
    texts = [m.text for m in db.query(models.Message)
             .filter_by(conversation_id=conv.id, sender="admin").all()]
    assert texts == ["hi"]


def test_post_message_rejected_again_after_return_to_ai(db, clinic, auth_client):
    conv = _conversation(db, clinic)
    auth_client.post(f"/api/conversations/{conv.id}/takeover")
    auth_client.post(f"/api/conversations/{conv.id}/return-to-ai")

    r = auth_client.post(f"/api/conversations/{conv.id}/messages", json={"text": "hi"})
    assert r.status_code == 409
    assert r.json()["detail"] == "takeover_required"


def test_blank_message_still_400_when_taken_over(db, clinic, auth_client):
    conv = _conversation(db, clinic)
    auth_client.post(f"/api/conversations/{conv.id}/takeover")
    r = auth_client.post(f"/api/conversations/{conv.id}/messages", json={"text": "  "})
    assert r.status_code == 400
