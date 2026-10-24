"""Transfer slips: a photo sent while a payment is owed pauses the hold for a person.

Payment is by PromptPay QR, so nothing tells the server money arrived — staff look at
the slip. Without this, the hold kept counting while the slip sat unread: a customer
who transferred at minute 3 was told at minute 10 that their slot had been released.

A web-chat photo goes through ``handle_customer_image`` instead of straight to the AI:

- no payment owed → the assistant answers the photo as it always has;
- a payment owed and the photo is a slip (asked of the vision model, ``ai/slip.py``)
  → the hold is PAUSED, the inbox is flagged, and the customer gets the same fixed
  acknowledgement every time — no AI reply, so nothing can "confirm" the payment;
- a payment owed but some other photo → the normal AI reply, and the hold keeps running;
- a slip whose amount (read by the same call) does not match what is owed → the customer
  is told the amounts differ and an admin will contact them, and the inbox flag says
  so. A SHORT slip does not pause the hold: otherwise a ฿1 transfer would hold any slot
  for as long as nobody looked at it. An over-paid one does, since the money is there.

Staff then confirm (``POST /payments/{id}/mark-paid`` → the booking confirmation message)
or reject (``POST /payments/{id}/reject-slip`` → the hold resumes with a fresh window and
the customer is asked to check the transfer).
"""
from datetime import datetime, timedelta

from app import models, realtime
from app.database import SessionLocal
from app.scope import scoped

# Prefix of Conversation.escalation_reason while a slip waits — the inbox badge. Only
# a reason this module wrote is ever cleared by it.
SLIP_FLAG = "สลิปรอตรวจ"

# No price, no year, no 3+ digit figure in anything said here: tools.py reads the clinic
# side's own messages for prices it has already quoted (see notify_hold_expired).
ACK_TH = "ได้รับรูปเรียบร้อยแล้วค่ะ 🙏 แอดมินกำลังตรวจสอบและจะแจ้งให้ทราบโดยเร็วที่สุดนะคะ"
ACK_EN = ("We've received your photo. 🙏 Our admin is checking it now and will let you know "
          "as soon as possible.")
# The amounts are left out on purpose, for the same reason as above.
MISMATCH_TH = ("ได้รับสลิปแล้วค่ะ 🙏 แต่ยอดเงินในสลิปไม่ตรงกับยอดที่ต้องชำระ "
               "แอดมินจะติดต่อกลับเพื่อตรวจสอบโดยเร็วที่สุดนะคะ")
MISMATCH_EN = ("We've received your slip. 🙏 However, the amount on it does not match the "
               "amount due. Our admin will contact you shortly to sort it out.")
# Added only while the hold is actually paused — never to someone whose hold had lapsed.
HELD_TH = " ระหว่างนี้ระบบยังถือคิวไว้ให้ค่ะ"
HELD_EN = " Your slot stays held in the meantime."


def payments_awaiting(db, conv) -> list[models.Payment]:
    """Every payment this conversation's customer still owes, newest first.

    Recent only (48h), and only while its booking can still be paid for — a cancelled
    or no-show booking has nothing a slip could settle."""
    since = datetime.utcnow() - timedelta(hours=48)
    rows = (scoped(db, models.Payment, conv.clinic_id)
            .filter(models.Payment.customer_id == conv.customer_id,
                    models.Payment.status == "pending",
                    models.Payment.created_at >= since)
            .order_by(models.Payment.id.desc()).all())
    out = []
    for p in rows:
        bk = db.get(models.Booking, p.booking_id) if p.booking_id else None
        if bk is None or bk.status in ("pending", "confirmed", "expired"):
            out.append(p)
    return out


def payment_awaiting(db, conv) -> models.Payment | None:
    """The newest payment this conversation's customer still owes, or None."""
    rows = payments_awaiting(db, conv)
    return rows[0] if rows else None


def amounts_match(read: float, due: float) -> bool:
    return abs(float(read) - float(due or 0)) < 0.01


def _payment_for(payments, amount):
    """The owed payment this slip pays: the one whose amount it matches, else the newest
    — a customer owing a deposit on one treatment and the balance on another is not
    sending a wrong amount just because the newest row is the other one."""
    if amount is not None:
        for p in payments:
            if amounts_match(amount, p.amount):
                return p
    return payments[0]


def handle_customer_image(conversation_id: int, image_url: str) -> None:
    """Background task for a web-chat photo: slip path or the normal AI reply."""
    from app.ai.slip import read_slip
    from app.services.inbox import generate_ai_reply

    db = SessionLocal()
    try:
        conv = db.get(models.Conversation, conversation_id)
        if conv is None:
            return
        owed = payments_awaiting(db, conv)
        if owed:
            # None (could not ask) counts as a slip: a person glancing at a skin photo
            # costs less than a paying customer losing their slot to a timeout.
            verdict = read_slip(image_url, conv.clinic_id)
            if verdict is None or verdict["is_slip"]:
                amount = verdict["amount"] if verdict else None
                receive_slip(db, conv, _payment_for(owed, amount), image_url, amount)
                return
    finally:
        db.close()
    generate_ai_reply(conversation_id)


def receive_slip(db, conv, payment, image_url: str, amount: float | None = None) -> None:
    """Pause the hold, flag the inbox, and acknowledge — every time a slip arrives.

    ``amount`` is what the vision model read off the slip (None = not read). One that
    differs from what is owed is a preliminary fraud check, not a verdict: the customer
    is told the amounts differ and that an admin will contact them, and staff still
    decide on the Payments page."""
    from app.services.booking import _now_local

    payment.slip_image = image_url
    payment.slip_received_at = datetime.utcnow()
    payment.slip_amount = amount
    due = float(payment.amount or 0)
    mismatch = amount is not None and not amounts_match(amount, due)
    short = mismatch and amount < due
    bk = db.get(models.Booking, payment.booking_id) if payment.booking_id else None
    # Pause only a hold that is still running. A lapsed one has already released its
    # slot to everyone; un-lapsing it here would hand it back without the claim lock.
    # That case is still acknowledged and still reaches staff — confirm_paid_booking
    # reinstates it if the time is free. A short slip never pauses it.
    if (not short and bk and bk.status == "pending" and bk.hold_expires_at
            and bk.hold_expires_at > _now_local()):
        bk.hold_expires_at = None        # NULL = blocks until a person decides
    held = bool(bk and bk.status == "pending" and bk.hold_expires_at is None
                and bk.hold_minutes)
    if mismatch:
        conv.escalation_reason = (f"{SLIP_FLAG} ยอดไม่ตรง: สลิป ฿{amount:,.2f} / ต้องชำระ "
                                  f"฿{due:,.2f} — ติดต่อลูกค้าเพื่อตรวจสอบ")[:240]
    else:
        conv.escalation_reason = (f"{SLIP_FLAG} ฿{int(due):,} — "
                                  "ตรวจสลิปแล้วกดยืนยันรับเงินที่หน้าการชำระเงิน")[:240]
    db.commit()
    from app.services.inbox import _conversation_language

    en = _conversation_language(db, conv) == "en"
    if mismatch:
        text = MISMATCH_EN if en else MISMATCH_TH
    else:
        text = ACK_EN if en else ACK_TH
    if held:
        text += HELD_EN if en else HELD_TH
    # "received" freezes the widget's countdown; a short slip's hold keeps running, so
    # it reports "mismatch", which the widget leaves alone.
    slip = {"payment_id": payment.id, "state": "received" if held or not mismatch else "mismatch"}
    if mismatch:
        slip["mismatch"] = True
    post_notice(db, conv, text, {"slip": slip})


def reject_slip(db, payment) -> dict:
    """Staff found no transfer behind the slip: resume the hold with a fresh window."""
    from app.services.booking import _now_local

    payment.slip_image = ""
    payment.slip_received_at = None
    payment.slip_amount = None
    bk = db.get(models.Booking, payment.booking_id) if payment.booking_id else None
    until = None
    if bk and bk.status == "pending" and bk.hold_expires_at is None and bk.hold_minutes:
        until = _now_local() + timedelta(minutes=bk.hold_minutes)
        bk.hold_expires_at = until
    conv = _conversation_for(db, payment, bk)
    if conv is not None and (conv.escalation_reason or "").startswith(SLIP_FLAG):
        conv.escalation_reason = ""
    db.commit()
    if conv is not None:
        from app.services.inbox import _conversation_language

        if _conversation_language(db, conv) == "en":
            text = ("Sorry — our team checked the photo but couldn't find the transfer. "
                    "Please check it and send the transfer slip again.")
            if until:
                text += f" Your slot is held until {until:%H:%M}."
        else:
            text = ("ขออภัยค่ะ ทีมงานตรวจสอบแล้วยังไม่พบยอดโอนจากรูปที่ส่งมา "
                    "รบกวนตรวจสอบอีกครั้งแล้วส่งสลิปการโอนเข้ามาใหม่นะคะ")
            if until:
                text += f" ระบบถือคิวไว้ให้ถึงเวลา {until:%H:%M} น. ค่ะ"
        post_notice(db, conv, text, {"slip": {
            "payment_id": payment.id, "state": "rejected",
            "hold_expires_at": until.isoformat() if until else None}})
    return {"hold_resumed_until": until.isoformat() if until else None}


def clear_slip_flag(db, conv) -> None:
    """Drop the inbox badge once the slip has been dealt with (paid)."""
    if conv is not None and (conv.escalation_reason or "").startswith(SLIP_FLAG):
        conv.escalation_reason = ""


def _conversation_for(db, payment, bk):
    if bk is not None and bk.conversation_id:
        conv = db.get(models.Conversation, bk.conversation_id)
        if conv is not None:
            return conv
    if not payment.customer_id:
        return None
    return (db.query(models.Conversation).filter_by(customer_id=payment.customer_id)
            .order_by(models.Conversation.id.desc()).first())


def post_notice(db, conv, text: str, meta: dict) -> None:
    """A clinic-side message the customer sees and the assistant remembers.

    ``sender="ai"`` for the same reason as notify_hold_expired: chat.py drops system
    messages from the model's history and the widget hides them on reload."""
    from app.services.inbox import conv_summary, msg_dict

    msg = models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                         sender="ai", text=text, meta=meta)
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    db.commit()
    realtime.publish({"type": "message", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "message": msg_dict(msg)})
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "summary": conv_summary(db, conv)})
    customer = db.get(models.Customer, conv.customer_id) if conv.customer_id else None
    try:
        from app.channels.adapters import get_adapter
        get_adapter(conv.channel).send(db, conv, customer, text)
    except Exception as exc:  # pragma: no cover
        print("[slips] notice send error:", exc)
