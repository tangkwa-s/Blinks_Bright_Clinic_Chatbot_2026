"""A transfer slip pauses the hold until a person checks it.

Payment is by PromptPay QR and nothing tells the server the money arrived, so the hold
used to keep counting while the slip sat unread: a customer who paid at minute 3 was told
at minute 10 that their slot had been released. Now a photo sent while a payment is owed
is checked (slip or not) before the assistant sees it:

- a slip pauses the hold, flags the inbox and gets the same fixed acknowledgement every
  time — the assistant does not answer it, so nothing can "confirm" the payment;
- any other photo gets the assistant's normal reply and the hold keeps running;
- staff confirm (booking confirmation message) or reject (hold restarts, customer asked
  to send the slip again).
"""
import re
from datetime import timedelta

import pytest

from app import models
from app.ai import chat as chat_mod
from app.ai import slip as slip_mod
from app.services import billing
from app.services import booking as bk
from app.services import inbox
from app.services import slips

IMG = "/assets/images/chat-uploads/c1-slip.png"


@pytest.fixture
def replies(monkeypatch):
    """Record generate_ai_reply calls instead of running the model."""
    calls = []
    monkeypatch.setattr(inbox, "generate_ai_reply", lambda cid: calls.append(cid))
    return calls


def _verdict(monkeypatch, answer, amount=None):
    """``answer`` True / False / None (could not ask); ``amount`` what the slip shows."""
    asked = []
    result = None if answer is None else {"is_slip": answer, "amount": amount}
    monkeypatch.setattr(slip_mod, "read_slip",
                        lambda url, cid=None: asked.append(url) or result)
    return asked


def _owed(db, clinic, *, hold_in_minutes=10):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = db.query(models.Service).filter_by(clinic_id=clinic.id, active=True).first()
    cust = models.Customer(clinic_id=clinic.id, name="แจ่มใส", phone="0811111111", channel="web")
    db.add(cust)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    b = models.Booking(clinic_id=clinic.id, customer_id=cust.id, service_id=svc.id,
                       branch_id=branch.id, conversation_id=conv.id,
                       slot_at=bk._now_local() + timedelta(days=2),
                       status="pending", price=3200, deposit_required=600, hold_minutes=10,
                       hold_expires_at=bk._now_local() + timedelta(minutes=hold_in_minutes))
    db.add(b)
    db.commit()
    pay = billing.create_payment(db, booking=b, ptype="deposit")
    return cust, conv, b, pay, svc


def _ai_texts(db, conv):
    db.expire_all()
    return [m.text for m in db.query(models.Message)
            .filter_by(conversation_id=conv.id, sender="ai").order_by(models.Message.id).all()]


def test_a_slip_pauses_the_hold_flags_the_inbox_and_is_acknowledged(
        db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, b, pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True)

    slips.handle_customer_image(conv.id, IMG)

    db.expire_all()
    assert db.get(models.Booking, b.id).hold_expires_at is None, "hold paused"
    p = db.get(models.Payment, pay.id)
    assert p.slip_image == IMG and p.slip_received_at is not None
    assert db.get(models.Conversation, conv.id).escalation_reason.startswith(slips.SLIP_FLAG)
    assert _ai_texts(db, conv) == [slips.ACK_TH + slips.HELD_TH]
    assert replies == [], "the assistant must not answer a slip itself"


def test_every_slip_gets_the_acknowledgement(db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, _b, _pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True)
    slips.handle_customer_image(conv.id, IMG)
    slips.handle_customer_image(conv.id, IMG)
    assert len([t for t in _ai_texts(db, conv) if t.startswith(slips.ACK_TH)]) == 2


def test_another_photo_gets_the_normal_reply_and_the_hold_keeps_running(
        db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, b, pay, _svc = _owed(db, clinic)
    deadline = b.hold_expires_at
    _verdict(monkeypatch, False)

    slips.handle_customer_image(conv.id, IMG)

    db.expire_all()
    assert db.get(models.Booking, b.id).hold_expires_at == deadline
    assert db.get(models.Payment, pay.id).slip_received_at is None
    assert replies == [conv.id]
    assert _ai_texts(db, conv) == []


def test_when_the_check_cannot_run_the_photo_is_treated_as_a_slip(
        db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, b, _pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, None)
    slips.handle_customer_image(conv.id, IMG)
    db.expire_all()
    assert db.get(models.Booking, b.id).hold_expires_at is None
    assert replies == []


def test_nothing_owed_means_no_check_and_the_normal_reply(db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    cust = models.Customer(clinic_id=clinic.id, name="ลูกค้า", channel="web")
    db.add(cust)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.commit()
    asked = _verdict(monkeypatch, True)
    slips.handle_customer_image(conv.id, IMG)
    assert asked == [], "no payment owed: never spend a model call on the photo"
    assert replies == [conv.id]


def test_a_lapsed_hold_is_not_bought_back_by_a_slip(db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, b, _pay, _svc = _owed(db, clinic, hold_in_minutes=-1)
    lapsed_at = b.hold_expires_at
    _verdict(monkeypatch, True)
    slips.handle_customer_image(conv.id, IMG)
    db.expire_all()
    assert db.get(models.Booking, b.id).hold_expires_at == lapsed_at
    # still acknowledged and still flagged for staff — but no "your slot is held"
    assert _ai_texts(db, conv) == [slips.ACK_TH]


def test_a_paused_hold_survives_the_expiry_sweep(db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, b, _pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True)
    slips.handle_customer_image(conv.id, IMG)
    bk.sweep_expired_holds(db, clinic.id)
    db.expire_all()
    assert db.get(models.Booking, b.id).status == "pending"


def test_staff_confirm_sends_the_booking_confirmation(db, auth_client, monkeypatch, replies):
    clinic = auth_client.test_clinic
    _cust, conv, b, pay, svc = _owed(db, clinic)
    _verdict(monkeypatch, True)
    slips.handle_customer_image(conv.id, IMG)

    r = auth_client.post(f"/api/payments/{pay.id}/mark-paid")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(models.Booking, b.id).status == "confirmed"
    assert db.get(models.Conversation, conv.id).escalation_reason == ""
    last = _ai_texts(db, conv)[-1]
    assert "การจองของคุณได้รับการยืนยันแล้ว" in last and svc.name in last
    assert f"{b.slot_at:%d/%m}" in last and f"{b.slot_at:%H:%M}" in last
    # tools.py reads clinic-side messages for quoted prices; a deposit figure must not land there
    assert not re.findall(r"\d{3,}", re.sub(r"[,\s]", "", last))


def test_staff_reject_restarts_the_hold_and_asks_again(db, auth_client, monkeypatch, replies):
    clinic = auth_client.test_clinic
    _cust, conv, b, pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True)
    slips.handle_customer_image(conv.id, IMG)

    r = auth_client.post(f"/api/payments/{pay.id}/reject-slip")
    assert r.status_code == 200, r.text
    db.expire_all()
    booking = db.get(models.Booking, b.id)
    assert booking.hold_expires_at is not None
    assert booking.hold_expires_at > bk._now_local() + timedelta(minutes=9), "a fresh window"
    assert db.get(models.Payment, pay.id).slip_received_at is None
    assert db.get(models.Conversation, conv.id).escalation_reason == ""
    assert "ส่งสลิปการโอนเข้ามาใหม่" in _ai_texts(db, conv)[-1]

    again = auth_client.post(f"/api/payments/{pay.id}/reject-slip")
    assert again.status_code == 409, "nothing left to reject"


def test_the_widget_gets_the_slip_state_and_the_assistant_is_told(
        db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    cust, conv, _b, pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True)
    slips.handle_customer_image(conv.id, IMG)
    db.expire_all()
    ack = (db.query(models.Message).filter_by(conversation_id=conv.id, sender="ai")
           .order_by(models.Message.id.desc()).first())
    assert inbox.msg_dict(ack)["slip"] == {"payment_id": pay.id, "state": "received"}
    hint = chat_mod._hold_hint(db, db.get(models.Conversation, conv.id),
                               db.get(models.Customer, cust.id))
    assert "SENT A TRANSFER SLIP" in hint and "Do NOT ask them to pay again" in hint


# ------------------------------------------------- amount on the slip (fraud check)
def test_a_slip_for_the_right_amount_is_acknowledged_as_usual(
        db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, b, pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True, amount=pay.amount)
    slips.handle_customer_image(conv.id, IMG)
    db.expire_all()
    assert _ai_texts(db, conv) == [slips.ACK_TH + slips.HELD_TH]
    assert db.get(models.Booking, b.id).hold_expires_at is None


def test_a_short_slip_is_told_apart_and_does_not_hold_the_slot(
        db, make_clinic, monkeypatch, replies):
    """A ฿1 transfer must not buy an open-ended hold on someone's slot."""
    clinic = make_clinic()
    _cust, conv, b, pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True, amount=1.0)
    slips.handle_customer_image(conv.id, IMG)
    db.expire_all()
    assert _ai_texts(db, conv) == [slips.MISMATCH_TH]
    assert replies == [], "the assistant must not answer a slip itself"
    assert db.get(models.Booking, b.id).hold_expires_at is not None, "hold keeps running"
    p = db.get(models.Payment, pay.id)
    assert p.slip_amount == 1.0 and p.slip_image == IMG
    flag = db.get(models.Conversation, conv.id).escalation_reason
    assert flag.startswith(slips.SLIP_FLAG) and "ยอดไม่ตรง" in flag and "฿1.00" in flag
    ack = (db.query(models.Message).filter_by(conversation_id=conv.id, sender="ai")
           .order_by(models.Message.id.desc()).first())
    assert inbox.msg_dict(ack)["slip"] == {"payment_id": pay.id, "state": "mismatch",
                                           "mismatch": True}
    # tools.py reads clinic-side messages for quoted prices; no figure may land there
    assert not re.findall(r"\d{3,}", re.sub(r"[,\s]", "", ack.text))


def test_an_overpaid_slip_is_flagged_but_still_holds_the_slot(
        db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    _cust, conv, b, pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True, amount=pay.amount + 1000)
    slips.handle_customer_image(conv.id, IMG)
    db.expire_all()
    assert _ai_texts(db, conv) == [slips.MISMATCH_TH + slips.HELD_TH]
    assert db.get(models.Booking, b.id).hold_expires_at is None
    assert "ยอดไม่ตรง" in db.get(models.Conversation, conv.id).escalation_reason


def test_the_assistant_is_told_the_amounts_differ(db, make_clinic, monkeypatch, replies):
    clinic = make_clinic()
    cust, conv, _b, _pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True, amount=1.0)
    slips.handle_customer_image(conv.id, IMG)
    db.expire_all()
    hint = chat_mod._hold_hint(db, db.get(models.Conversation, conv.id),
                               db.get(models.Customer, cust.id))
    assert "does NOT match" in hint and "admin will contact them" in hint


def test_reject_clears_the_amount_read(db, auth_client, monkeypatch, replies):
    clinic = auth_client.test_clinic
    _cust, conv, _b, pay, _svc = _owed(db, clinic)
    _verdict(monkeypatch, True, amount=1.0)
    slips.handle_customer_image(conv.id, IMG)
    listed = auth_client.get("/api/payments").json()
    rows = listed if isinstance(listed, list) else listed.get("payments", [])
    assert any(r["id"] == pay.id and r["slip_amount"] == 1.0 for r in rows)
    assert auth_client.post(f"/api/payments/{pay.id}/reject-slip").status_code == 200
    db.expire_all()
    assert db.get(models.Payment, pay.id).slip_amount is None


@pytest.mark.parametrize("answer,expected", [
    ('{"slip": true, "amount": 1.00}', {"is_slip": True, "amount": 1.0}),
    ('```json\n{"slip": true, "amount": "2,500.00"}\n```', {"is_slip": True, "amount": 2500.0}),
    ('{"slip": true, "amount": null}', {"is_slip": True, "amount": None}),
    ('{"slip": false, "amount": 300}', {"is_slip": False, "amount": None}),
    ("yes", {"is_slip": True, "amount": None}),
    ("no", {"is_slip": False, "amount": None}),
    ("maybe", None),
])
def test_the_model_answer_is_read_safely(answer, expected):
    assert slip_mod.parse_answer(answer) == expected
