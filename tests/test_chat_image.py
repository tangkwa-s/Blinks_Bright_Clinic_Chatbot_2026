"""A customer can send a photo in the web widget (POST /api/channels/web/image).

The file is validated and stored under chat-uploads/, the path rides on the message's
``meta.image`` (no new column), and ``chat.respond`` hands ONLY the newest photo to the
model as an ``image_url`` part so a long chat does not re-pay for every picture.
"""
import base64

import pytest

from app import avatars, models
from app.ai import chat
from app.security import make_chat_token

# smallest valid 1x1 PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(avatars, "CHAT_UPLOAD_DIR", tmp_path)


@pytest.fixture
def conv(db, make_clinic):
    clinic = make_clinic()
    cust = models.Customer(clinic_id=clinic.id, name="Photo Visitor", channel="web",
                           channel_user_id="web_photo_1")
    db.add(cust)
    db.flush()
    c = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(c)
    db.commit()
    return c


def _post(client, conv, content=PNG, ctype="image/png", name="slip.png", text=""):
    return client.post("/api/channels/web/image",
                       data={"token": make_chat_token(conv.id), "text": text},
                       files={"file": (name, content, ctype)})


def test_photo_is_stored_and_attached_to_the_customer_message(client, db, conv):
    r = _post(client, conv, text="สลิปมัดจำค่ะ")
    assert r.status_code == 200, r.text
    msg = db.query(models.Message).filter_by(conversation_id=conv.id, sender="customer").one()
    assert msg.text == "สลิปมัดจำค่ะ"
    assert msg.meta["image"].startswith("/assets/images/chat-uploads/")
    widget = client.get(f"/api/channels/web/messages?token={make_chat_token(conv.id)}").json()
    mine = [m for m in widget["messages"] if m["sender"] == "customer"]
    assert mine[-1]["image"] == msg.meta["image"]


def test_photo_without_caption_gets_a_neutral_placeholder(client, db, conv):
    _post(client, conv)
    msg = db.query(models.Message).filter_by(conversation_id=conv.id, sender="customer").one()
    assert msg.text == "📷"          # not Thai: it must not flip an English chat's language


@pytest.mark.parametrize("content,ctype,name", [
    (b"GIF89a", "image/gif", "x.gif"),
    (b"%PDF-1.4", "application/pdf", "x.pdf"),
    (b"", "image/png", "empty.png"),
    (b"0" * (4 * 1024 * 1024 + 1), "image/png", "big.png"),
], ids=["gif", "pdf", "empty", "over-4mb"])
def test_bad_files_are_refused_and_no_message_is_created(client, db, conv, content, ctype, name):
    assert _post(client, conv, content, ctype, name).status_code == 400
    assert db.query(models.Message).filter_by(conversation_id=conv.id).count() == 0


def test_bad_token_is_refused(client, conv):
    r = client.post("/api/channels/web/image", data={"token": "nope"},
                    files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 401


def test_only_the_newest_photo_reaches_the_model(client, db, conv):
    _post(client, conv, text="รูปแรก")
    _post(client, conv, text="รูปสอง")
    msgs = (db.query(models.Message).filter_by(conversation_id=conv.id, sender="customer")
            .order_by(models.Message.id).all())
    newest = msgs[-1].meta["image"]
    older = msgs[0].meta["image"]
    assert chat._image_part(newest)["image_url"]["url"].startswith("data:image/png;base64,")
    assert chat._image_part("/assets/images/chat-uploads/../../../app/config.py") is None
    assert chat._image_part("/assets/images/chat-uploads/missing.png") is None
    assert older != newest
