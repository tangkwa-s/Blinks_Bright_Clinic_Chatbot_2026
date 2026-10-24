"""The payment service: payment rows, and the paid cascade.

Payment is by bank transfer to the clinic's PromptPay QR (``app/services/promptpay``):
``create_payment`` records what is owed, the assistant shows the QR, the customer sends
the slip, and a staff member confirms it (``POST /api/payments/{id}/mark-paid``), which
runs ``mark_paid`` — booking, customer, conversation and the "payment received" message.
There is no card processor.
"""
from datetime import datetime

from sqlalchemy import func

from app import models, realtime
from app.config import settings


def _paid_total_for_booking(db, booking) -> float:
    """Sum of already-PAID payments for this booking (any type). Scoped to the
    booking's own clinic + customer, mirroring the idempotency lookup below, so a
    stale cross-clinic row (SQLite rowid reuse) can't skew the remaining balance."""
    return (db.query(func.coalesce(func.sum(models.Payment.amount), 0.0))
            .filter(models.Payment.booking_id == booking.id,
                    models.Payment.clinic_id == booking.clinic_id,
                    models.Payment.customer_id == booking.customer_id,
                    models.Payment.status == "paid")
            .scalar()) or 0.0


def create_payment(db, *, booking=None, customer=None, amount=None,
                   ptype: str = "deposit"):
    """Create (or reuse) the Payment row for what is owed. Returns the payment.

    **Idempotent per (booking, type)** — a booking never gets two payable rows, so the
    same deposit can't be collected twice: if it is already paid this returns that paid
    row (callers check ``status``); a still-pending row is reused with its amount
    refreshed, since the remaining balance may have changed.
    """
    if booking and not customer:
        customer = db.get(models.Customer, booking.customer_id)
    if booking and amount is None:
        if ptype == "deposit":
            amount = booking.deposit_required
        else:
            # A "full" payment settles whatever price remains. If a deposit (or any
            # other paid payment) already went through for this booking, charge only
            # the remaining balance — never the full price on top of what's paid.
            paid_so_far = _paid_total_for_booking(db, booking)
            amount = max(0.0, booking.price - paid_so_far)
            if amount <= 0 and paid_so_far > 0:
                # A prior payment (e.g. a 100%-deposit service) already covers the
                # full price — report it "already paid" rather than trying to open
                # a ฿0 payment.
                settled = (db.query(models.Payment)
                           .filter(models.Payment.booking_id == booking.id,
                                   models.Payment.clinic_id == booking.clinic_id,
                                   models.Payment.customer_id == booking.customer_id,
                                   models.Payment.status == "paid")
                           .order_by(models.Payment.id.desc()).first())
                if settled:
                    return settled
    amount = float(amount or 0)

    label = "Deposit" if ptype == "deposit" else "Payment"
    if booking:
        svc = db.get(models.Service, booking.service_id)
        description = f"{label} — {svc.name if svc else 'treatment'} (booking #{booking.id})"
    clinic_id = ((booking.clinic_id if booking else None)
                 or (customer.clinic_id if customer else None))
    if not booking:
        clinic = db.get(models.Clinic, clinic_id) if clinic_id else None
        description = f"{label} — {clinic.name if clinic else 'clinic'}"

    payment = None
    if booking:
        # Scope the idempotency lookup to THIS booking's clinic + customer. booking_id
        # alone is unsafe: SQLite reuses the rowid of a deleted booking, so a stale
        # paid payment that still references that id (possibly from another clinic /
        # a since-deleted customer) would otherwise match and wrongly report the new
        # booking as "already paid".
        prior = (db.query(models.Payment)
                 .filter(models.Payment.booking_id == booking.id,
                         models.Payment.clinic_id == booking.clinic_id,
                         models.Payment.customer_id == booking.customer_id,
                         models.Payment.type == ptype,
                         models.Payment.status.in_(["paid", "pending"]))
                 .order_by(models.Payment.id.desc()).first())
        if prior and prior.status == "paid":
            return prior                       # already paid — never charge again
        if prior and prior.status == "pending":
            payment = prior                    # reuse the row; the balance may have moved
            payment.amount = amount

    if payment is None:
        payment = models.Payment(
            clinic_id=clinic_id,
            customer_id=customer.id if customer else None,
            booking_id=booking.id if booking else None,
            type=ptype, amount=amount, currency=settings.currency,
            status="pending", description=description,
        )
        db.add(payment)
        db.flush()

    db.commit()
    return payment


def mark_paid(db, payment, method: str = "promptpay") -> bool:
    """Mark a payment paid exactly once; cascade to booking, customer, conversation.

    The pending->paid transition is an **atomic conditional UPDATE** (compare-and-set
    on ``status``), so concurrent callers — two staff members confirming the same
    slip, or a double click — can never both run the cascade. Only the caller that actually flips the row proceeds; the rest get
    ``False``. This prevents double-counted ``customer.ltv``, duplicate Activity rows
    and duplicate realtime events from racing payment confirmations.

    Everything below, including the compare-and-set itself, runs inside THIS booking's
    clinic claim_lock — the same lock claim_slot uses (see confirm_paid_booking for why
    the lock has to stay held through the commit at the bottom, not just around the
    booking decision). **The lock is acquired FIRST, before any write** — this is not
    negotiable. claim_slot itself always takes the lock before touching the database; if
    this function instead wrote first (the compare-and-set) and only acquired the lock
    afterwards, a thread here could be holding SQLite's write lock (from the uncommitted
    compare-and-set) while blocked waiting for the app lock — and a claim_slot caller
    that grabbed the app lock first, wanting to write, would then block waiting for
    SQLite's lock that THIS thread holds. Two threads, each holding what the other
    needs: a deadlock, resolved only by pysqlite's busy-timeout finally giving up and
    raising ``database is locked``. Acquiring the lock before any write is how every
    caller of it — this function and claim_slot alike — avoids that ordering entirely.
    """
    booking = db.get(models.Booking, payment.booking_id) if payment.booking_id else None
    from contextlib import nullcontext

    from app.services.booking import claim_lock, confirm_paid_booking

    with claim_lock(booking.clinic_id) if booking else nullcontext():
        won = (db.query(models.Payment)
               .filter(models.Payment.id == payment.id, models.Payment.status != "paid")
               .update({models.Payment.status: "paid",
                        models.Payment.paid_at: datetime.utcnow(),
                        models.Payment.method: method or "card"},
                       synchronize_session=False))
        if not won:
            db.rollback()       # someone else already confirmed it — no double cascade
            return False
        db.refresh(payment)     # load the just-committed values into the ORM object

        # Not a bare pending->confirmed any more: the hold may have lapsed before the
        # money arrived, and money must never buy back a slot somebody else has taken.
        outcome = confirm_paid_booking(db, booking)

        customer = db.get(models.Customer, payment.customer_id) if payment.customer_id else None
        if customer:
            customer.ltv = round((customer.ltv or 0) + payment.amount, 2)
            # Any non-deposit payment (full, or an admin's standalone "custom" charge)
            # fully settles the sale — a deposit only secures the booking.
            if payment.type != "deposit" and customer.pipeline_stage in (
                    "new_lead", "interested", "booked"):
                customer.pipeline_stage = "paid"
            db.add(models.Activity(
                clinic_id=customer.clinic_id, customer_id=customer.id, type="payment",
                summary=f"{payment.type.title()} paid — ฿{int(payment.amount):,}",
                ref_type="payment", ref_id=payment.id))

        # Resolve the conversation this payment settles the same way notify_payment_paid
        # does (the booking's conversation, else the customer's latest) — a custom charge
        # (POST /conversations/{id}/charge) has no booking, so without this fallback its
        # conversation would never flip out of its pre-payment pipeline stage.
        conv_id = booking.conversation_id if booking else None
        if conv_id is None and payment.customer_id:
            latest = (db.query(models.Conversation)
                      .filter_by(customer_id=payment.customer_id)
                      .order_by(models.Conversation.id.desc()).first())
            conv_id = latest.id if latest else None
        if conv_id:
            conv = db.get(models.Conversation, conv_id)
            if conv:
                conv.status = "booked" if payment.type == "deposit" else "paid"
                if outcome == "slot_gone":
                    # The one case a person must handle: they have paid and have no
                    # appointment. escalation_reason is how this app already says "a
                    # human is needed here" — the inbox renders it as the request-admin
                    # badge.
                    conv.escalation_reason = ("ชำระเงินหลังหมดเวลาถือคิว — เวลานั้นถูกจองไปแล้ว "
                                              "ต้องติดต่อลูกค้าเพื่อจัดเวลาใหม่")[:240]

        db.commit()   # while still holding the lock, so the write is durable before it releases
    realtime.publish({"type": "payment", "payment_id": payment.id, "status": "paid",
                      "clinic_id": payment.clinic_id,
                      "conversation_id": conv_id})
    if booking and outcome != "noop":
        realtime.publish({"type": "booking", "booking_id": booking.id,
                          "clinic_id": payment.clinic_id})
    # Tell the customer in their chat and settle the
    # pay-card. Runs once — only the caller that won the compare-and-set reaches here.
    try:
        from app.services.inbox import notify_payment_paid

        notify_payment_paid(db, payment, outcome=outcome)
    except Exception as exc:  # pragma: no cover
        print("[billing] payment notify error:", exc)
    return True
