"""Every endpoint drawn in docs/ARCHITECTURE.md answers.

The course checklist asks that "every endpoint in the architecture diagram works".
This walks the diagram's endpoints in the order a customer and a staff member use
them. It runs offline (no OpenAI: the assistant answers with its fixed fallback
line), so it proves the
plumbing, while evals/deliverable.py proves the answers with the real model.
"""
import base64

import pytest
from starlette.websockets import WebSocketDisconnect

from app import avatars, models

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(avatars, "CHAT_UPLOAD_DIR", tmp_path)


@pytest.mark.parametrize("path", ["/", "/portal", "/admin"])
def test_pages(client, clinic, path):
    r = client.get(path)
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_chat_widget_page(client, clinic):
    r = client.get(f"/chat/{clinic.slug}")
    assert r.status_code == 200 and "chat-msgs" in r.text


def test_health(client):
    assert client.get("/api/health").status_code == 200


def test_portal_home_is_public_catalog(client, clinic):
    r = client.get(f"/api/portal/home?slug={clinic.slug}")
    assert r.status_code == 200, r.text


def test_customer_chat_path(client, db, clinic):
    """start -> text -> photo -> history, the widget's whole path."""
    r = client.post("/api/channels/web/start", json={"clinic": clinic.slug})
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    r = client.post("/api/channels/web/message", json={"token": token, "text": "สวัสดีค่ะ"})
    assert r.status_code == 200, r.text
    r = client.post("/api/channels/web/image", data={"token": token, "text": "สลิปค่ะ"},
                    files={"file": ("slip.png", PNG, "image/png")})
    assert r.status_code == 200, r.text

    r = client.get(f"/api/channels/web/messages?token={token}")
    assert r.status_code == 200
    senders = [m["sender"] for m in r.json()["messages"]]
    # greeting, text, reply, photo, reply — the background reply ran for each turn
    assert senders.count("customer") == 2 and senders.count("ai") == 3, senders


def test_bad_chat_token_is_refused(client, clinic):
    r = client.post("/api/channels/web/message", json={"token": "forged", "text": "hi"})
    assert r.status_code == 401


def test_chat_stream_websocket(client, clinic):
    token = client.post("/api/channels/web/start", json={"clinic": clinic.slug}).json()["token"]
    with client.websocket_connect(f"/api/chat-stream/{token}"):
        pass                                   # accepted
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/chat-stream/forged") as ws:
            ws.receive_json()                  # closed with 1008


def test_staff_path(auth_client, db):
    """login (fixture) -> me -> inbox -> takeover -> reply -> back to AI -> KB -> bookings -> confirm a transfer."""
    c = auth_client
    clinic = c.test_clinic
    assert c.get("/api/auth/me").status_code == 200

    # a customer conversation to work on, made through the Test Console endpoint
    r = c.post("/api/test/simulate", json={"channel": "web", "text": "มีโปรอะไรบ้างคะ"})
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation_id"]

    r = c.get("/api/conversations")
    assert r.status_code == 200
    assert c.get(f"/api/conversations/{conv_id}").status_code == 200
    assert c.post(f"/api/conversations/{conv_id}/takeover").json()["ai_enabled"] is False
    r = c.post(f"/api/conversations/{conv_id}/messages", json={"text": "เดี๋ยวแอดมินตอบให้ค่ะ"})
    assert r.status_code == 200, r.text
    assert c.post(f"/api/conversations/{conv_id}/return-to-ai").status_code == 200
    assert db.get(models.Conversation, conv_id).ai_enabled is True

    assert c.get("/api/knowledge/articles").status_code == 200
    assert c.post("/api/knowledge/reindex").status_code == 200
    assert c.get("/api/bookings").status_code == 200
    assert c.get("/api/payments").status_code == 200
    # staff confirm a transfer after checking the slip (the only way a payment is settled)
    conv = db.get(models.Conversation, conv_id)
    pay = models.Payment(clinic_id=clinic.id, customer_id=conv.customer_id, amount=600,
                         type="custom", status="pending", description="QR transfer")
    db.add(pay)
    db.commit()
    r = c.post(f"/api/payments/{pay.id}/mark-paid")
    assert r.status_code == 200 and r.json()["payment"]["status"] == "paid", r.text
    with c.websocket_connect("/api/ws"):
        pass
