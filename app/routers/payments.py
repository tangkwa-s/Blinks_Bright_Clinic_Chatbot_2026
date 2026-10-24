"""Payment routes — list/summary, the payment QR, and staff confirmation of a transfer."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import active_clinic_id, current_user, require_role
from app.scope import scoped
from app.services import billing
from app.services.promptpay import qr_image_url
from app.services.reporting import period_since

router = APIRouter(prefix="/api", tags=["payments"])


def payment_dict(db: Session, p: models.Payment, cid: int) -> dict:
    cust = (scoped(db, models.Customer, cid)
            .filter(models.Customer.id == p.customer_id).first()
            if p.customer_id else None)
    return {
        "id": p.id, "customer_id": p.customer_id,
        "customer_name": cust.name if cust else "—",
        "booking_id": p.booking_id, "type": p.type, "amount": p.amount,
        "currency": p.currency, "status": p.status, "method": p.method,
        "description": p.description, "stripe_session_id": p.stripe_session_id,
        "slip_image": p.slip_image or "",
        "slip_received_at": p.slip_received_at.isoformat() if p.slip_received_at else None,
        "slip_amount": p.slip_amount,
        "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _filter_by_branch(db: Session, query, cid: int, branch_id: int):
    """A payment's branch: its booking's branch, else its customer's own branch
    (covers standalone/custom charges with no booking) — the same attribution
    dashboard.py uses for per-branch revenue."""
    if not branch_id:
        return query
    booking_ids = (db.query(models.Booking.id)
                   .filter(models.Booking.clinic_id == cid, models.Booking.branch_id == branch_id))
    customer_ids = (db.query(models.Customer.id)
                    .filter(models.Customer.clinic_id == cid, models.Customer.branch_id == branch_id))
    return query.filter(or_(
        models.Payment.booking_id.in_(booking_ids),
        (models.Payment.booking_id.is_(None)) & (models.Payment.customer_id.in_(customer_ids)),
    ))


def _filter_by_period(query, period: str):
    """Bound to payments whose relevant financial event falls within the period —
    ``paid_at`` when the payment is settled, else ``created_at`` for a pending/
    failed/refunded row that has no paid_at yet. Matches the same 7d/30d/90d/1y/all
    tokens the dashboard uses (app.services.reporting), so switching the period on
    either page means the same window. Empty period = no filtering (every payment,
    all time) — the default, so an existing caller that never passes one keeps
    today's behaviour.
    """
    if not period:
        return query
    since = period_since(period, datetime.utcnow())
    return query.filter(or_(
        models.Payment.paid_at >= since,
        (models.Payment.paid_at.is_(None)) & (models.Payment.created_at >= since),
    ))


def _fully_settled_booking_ids(db: Session, cid: int):
    """Bookings that have since collected a paid FULL payment — i.e. any earlier paid
    deposit for these is no longer the booking's current state.

    A booking that paid a deposit and later paid the remaining balance in full ends up
    with TWO paid Payment rows (create_payment never edits the deposit row — the
    top-up is its own row, for just the remaining amount). Counting both as separate
    "achievements" double-counts the same booking into both the deposit and the
    fully-paid buckets forever, even after it is completely settled. This is the one
    query both list_payments' "booked" filter and payments_summary use to agree on
    which bucket a booking is CURRENTLY in.
    """
    return (scoped(db, models.Payment, cid)
            .filter(models.Payment.status == "paid", models.Payment.type == "full",
                    models.Payment.booking_id.isnot(None))
            .with_entities(models.Payment.booking_id))


@router.get("/payments")
def list_payments(status: str = "", branch_id: int = 0, period: str = "",
                  db: Session = Depends(get_db),
                  _u: models.User = Depends(current_user),
                  cid: int = Depends(active_clinic_id)):
    query = _filter_by_period(scoped(db, models.Payment, cid), period)
    # "booked" / "paid" split a single DB status ('paid') by type: a paid
    # deposit reads as booked, a paid full payment reads as settled — mirrors
    # payments.js::displayStatus so the filter matches what's shown.
    if status == "booked":
        query = query.filter(
            models.Payment.status == "paid", models.Payment.type == "deposit",
            ~models.Payment.booking_id.in_(_fully_settled_booking_ids(db, cid)))
    elif status == "paid":
        query = query.filter(models.Payment.status == "paid", models.Payment.type == "full")
    elif status:
        query = query.filter(models.Payment.status == status)
    query = _filter_by_branch(db, query, cid, branch_id)
    rows = query.order_by(models.Payment.id.desc()).limit(300).all()
    return [payment_dict(db, p, cid) for p in rows]


@router.get("/payments/summary")
def payments_summary(branch_id: int = 0, period: str = "", db: Session = Depends(get_db),
                     _u: models.User = Depends(current_user),
                     cid: int = Depends(active_clinic_id)):
    query = _filter_by_branch(
        db, _filter_by_period(scoped(db, models.Payment, cid), period), cid, branch_id)
    rows = query.all()
    paid = [p for p in rows if p.status == "paid"]
    # A booking whose deposit was later topped up to a full settlement now belongs
    # ONLY in "paid" — not in both, and not still in "deposit_paid" forever. Payments
    # with no booking_id (ad-hoc charges) have no "later top-up" to be superseded by,
    # so they always count as their own paid-deposit/paid-full event.
    settled = {bid for (bid,) in _fully_settled_booking_ids(db, cid)}
    return {
        "total": len(rows),
        # "paid" = fully settled sales only; a paid deposit only secures the booking
        # and is counted separately from it — mirrors the booked/paid split in
        # list_payments() and billing.mark_paid's pipeline_stage cascade —
        # UNTIL the same booking's balance is later paid in full, at which point it
        # moves out of deposit_paid and into paid, not double-counted in both.
        "deposit_paid": sum(1 for p in paid if p.type == "deposit"
                            and p.booking_id not in settled),
        "paid": sum(1 for p in paid if p.type == "full"),
        "pending": sum(1 for p in rows if p.status == "pending"),
        "revenue": round(sum(p.amount for p in paid), 2),
    }


@router.post("/payments/link")
def create_link(data: dict = Body(...), db: Session = Depends(get_db),
                _u: models.User = Depends(current_user),
                cid: int = Depends(active_clinic_id)):
    """Raise (or reuse) a payment for a booking and hand back the clinic's payment QR.

    Staff open the QR to show or forward it; once the slip checks out they confirm the
    payment with ``POST /payments/{id}/mark-paid``."""
    booking = (scoped(db, models.Booking, cid)
               .filter(models.Booking.id == data["booking_id"]).first()
               if data.get("booking_id") else None)
    customer = (scoped(db, models.Customer, cid)
                .filter(models.Customer.id == data["customer_id"]).first()
                if data.get("customer_id") else None)
    if data.get("booking_id") and not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    payment = billing.create_payment(
        db, booking=booking, customer=customer,
        amount=data.get("amount"), ptype=data.get("type", "deposit"))
    payment.clinic_id = cid
    db.commit()
    if payment.status == "paid":
        raise HTTPException(status_code=409, detail="This booking's deposit is already paid")
    qr = qr_image_url()
    if not qr:
        raise HTTPException(status_code=503, detail="No payment QR is set up "
                            "(add web/assets/images/payment-qr.png)")
    return {"payment": payment_dict(db, payment, cid), "qr_url": qr}


@router.post("/payments/{payment_id}/mark-paid")
def mark_paid_manual(payment_id: int, db: Session = Depends(get_db),
                     _u: models.User = Depends(require_role("branch_manager")),
                     cid: int = Depends(active_clinic_id)):
    """Confirm a bank-transfer / PromptPay payment by hand, after checking the slip.

    A bank transfer has no webhook to tell the server the money arrived, so a person
    does. It runs the full ``mark_paid`` cascade — booking confirmed (or escalated if the hold lapsed and the slot was taken), customer LTV,
    the "payment received" message in the chat — and is idempotent: a second click is
    reported as already paid, never applied twice."""
    payment = (scoped(db, models.Payment, cid)
               .filter(models.Payment.id == payment_id).first())
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status == "paid":
        return {"ok": True, "already_paid": True, "payment": payment_dict(db, payment, cid)}
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail="Only a pending payment can be confirmed")
    billing.mark_paid(db, payment, method="promptpay")
    db.refresh(payment)
    return {"ok": True, "already_paid": False, "payment": payment_dict(db, payment, cid)}


@router.post("/payments/{payment_id}/reject-slip")
def reject_slip(payment_id: int, db: Session = Depends(get_db),
                _u: models.User = Depends(require_role("branch_manager")),
                cid: int = Depends(active_clinic_id)):
    """The photo was not a slip, or no transfer arrived: resume the paused hold.

    The hold restarts with a fresh window (a customer must not lose a slot because
    staff took twenty minutes to look), and the customer is asked to check the
    transfer and send the slip again."""
    from app.services.slips import reject_slip as _reject

    payment = (scoped(db, models.Payment, cid)
               .filter(models.Payment.id == payment_id).first())
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status != "pending" or not payment.slip_received_at:
        raise HTTPException(status_code=409, detail="No slip is waiting on this payment")
    out = _reject(db, payment)
    db.refresh(payment)
    return {"ok": True, **out, "payment": payment_dict(db, payment, cid)}
