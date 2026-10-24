"""Payment is by QR: the assistant shows the clinic's PromptPay QR, staff confirm it.

There is no card processor. The assistant shows the QR with the amount owed, the
customer sends the slip in chat, and a staff member confirms it on Payments, which runs
the full paid cascade (booking confirmed, customer told).
"""
from datetime import timedelta

from app import models
from app.ai.tools import execute_tool
from app.services import booking as bk
from app.services import promptpay
from app.services.billing import create_payment


def _held_booking(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = db.query(models.Service).filter_by(clinic_id=clinic.id, active=True).first()
    cust = models.Customer(clinic_id=clinic.id, name="แจ่มใส", phone="0811111111",
                           channel="web")
    db.add(cust)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    b = models.Booking(clinic_id=clinic.id, customer_id=cust.id, service_id=svc.id,
                       branch_id=branch.id, conversation_id=conv.id,
                       slot_at=bk._now_local() + timedelta(days=1),
                       status="pending", price=3200, deposit_required=600,
                       hold_expires_at=bk._now_local() + timedelta(minutes=10))
    db.add(b)
    db.commit()
    return cust, conv, b


def test_no_qr_set_up_hands_payment_to_a_person(db, make_clinic):
    clinic = make_clinic()
    cust, conv, _b = _held_booking(db, clinic)
    res = execute_tool(db, conv, cust, "create_payment_link", {"type": "deposit"})
    assert "error" in res and "payment_qr" not in res
    assert "request_human_help" in res["note"]


def test_payment_shows_the_qr_with_the_amount(db, make_clinic, qr_file):
    clinic = make_clinic()
    cust, conv, b = _held_booking(db, clinic)
    res = execute_tool(db, conv, cust, "create_payment_link", {"type": "deposit"})
    assert res["payment_qr"] == qr_file
    assert res["amount_value"] == 600.0 and res["amount"] == "฿600"
    assert res["hold_expires_at"] == b.hold_expires_at.isoformat()
    assert "฿600" in res["qr_say_it_like"] and "สลิป" in res["qr_say_it_like"]
    # the model must not paste the QR address, nor confirm a slip itself
    assert "Do NOT paste the QR address" in res["note"]
    pay = db.get(models.Payment, res["payment_id"])
    assert pay.status == "pending" and pay.booking_id == b.id


def test_qr_path_cannot_escape_the_web_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(promptpay, "WEB_DIR", tmp_path)
    for bad in ("../../etc/passwd", "/../secret.png", "assets/no-leading-slash.png", ""):
        monkeypatch.setattr(promptpay.settings, "payment_qr_image", bad)
        assert promptpay.qr_image_url() is None


def test_staff_confirms_the_transfer_once(db, auth_client, qr_file):
    clinic = auth_client.test_clinic
    cust, conv, b = _held_booking(db, clinic)
    res = execute_tool(db, conv, cust, "create_payment_link", {"type": "deposit"})
    pid = res["payment_id"]

    r = auth_client.post(f"/api/payments/{pid}/mark-paid")
    assert r.status_code == 200, r.text
    assert r.json()["already_paid"] is False
    assert r.json()["payment"]["method"] == "promptpay"
    db.expire_all()
    assert db.get(models.Booking, b.id).status == "confirmed"

    again = auth_client.post(f"/api/payments/{pid}/mark-paid")
    assert again.status_code == 200 and again.json()["already_paid"] is True


def test_mark_paid_is_clinic_scoped(db, auth_client, make_clinic, qr_file):
    other = make_clinic(name="Other", slug="other")
    cust, conv, _b = _held_booking(db, other)
    res = execute_tool(db, conv, cust, "create_payment_link", {"type": "deposit"})
    r = auth_client.post(f"/api/payments/{res['payment_id']}/mark-paid")
    assert r.status_code == 404


def test_book_appointment_shows_the_qr_and_says_the_hold(db, make_clinic, qr_file):
    """The booking turn itself carries the QR, so the customer can pay straight away."""
    clinic = make_clinic()
    cust, conv, b = _held_booking(db, clinic)
    payment = create_payment(db, booking=b, ptype="deposit")
    assert payment.status == "pending" and payment.amount == 600.0
    again = create_payment(db, booking=b, ptype="deposit")
    assert again.id == payment.id, "one payable row per booking and type"


def test_custom_charge_sends_the_qr_in_chat(db, auth_client, qr_file):
    clinic = auth_client.test_clinic
    _cust, conv, _b = _held_booking(db, clinic)
    r = auth_client.post(f"/api/conversations/{conv.id}/charge",
                         json={"amount": 4500, "label": "ราคาที่ตกลงกัน"})
    assert r.status_code == 200, r.text
    pay = r.json()["message"]["payment"]
    assert pay["kind"] == "qr" and pay["url"] == qr_file and pay["amount"] == 4500
    assert "ลิงก์" not in r.json()["message"]["text"]
