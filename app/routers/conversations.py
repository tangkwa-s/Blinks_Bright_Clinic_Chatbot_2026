"""Unified inbox routes + admin realtime WebSocket."""
import asyncio

from fastapi import (APIRouter, BackgroundTasks, Body, Depends, HTTPException,
                     WebSocket, WebSocketDisconnect)
from sqlalchemy.orm import Session

from app import models, realtime
from app.database import get_db
from app.deps import active_clinic_id, current_user, effective_branch, require_role
from app.scope import scoped
from app.security import SESSION_COOKIE, read_session
from app.services.inbox import (auto_return_to_ai, conv_summary, generate_ai_reply,
                                msg_dict, send_admin_message)

router = APIRouter(prefix="/api", tags=["conversations"])


@router.get("/conversations")
def list_conversations(status: str = "", channel: str = "", branch_id: str = "",
                       q: str = "", db: Session = Depends(get_db),
                       clinic_id: int = Depends(active_clinic_id),
                       user: models.User = Depends(current_user)):
    query = scoped(db, models.Conversation, clinic_id)
    if status:
        query = query.filter(models.Conversation.status == status)
    if channel:
        query = query.filter(models.Conversation.channel == channel)
    bid = effective_branch(user, branch_id)
    if bid:
        query = query.filter(models.Conversation.branch_id == bid)
    convs = query.order_by(models.Conversation.last_message_at.desc()).limit(250).all()
    rows = [conv_summary(db, c) for c in convs]
    if q:
        ql = q.lower()
        rows = [r for r in rows
                if ql in r["customer_name"].lower() or ql in (r["last_message"] or "").lower()]
    return rows


@router.get("/conversations/counts")
def conversation_counts(db: Session = Depends(get_db),
                        clinic_id: int = Depends(active_clinic_id),
                        _u: models.User = Depends(current_user)):
    out = {"all": 0, "unread": 0}
    for c in scoped(db, models.Conversation, clinic_id).all():
        out["all"] += 1
        out[c.status] = out.get(c.status, 0) + 1
        if c.unread:
            out["unread"] += 1
    return out


def _conv_or_404(db: Session, conv_id: int, clinic_id: int) -> models.Conversation:
    conv = (scoped(db, models.Conversation, clinic_id)
            .filter(models.Conversation.id == conv_id).first())
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.get("/conversations/{cid}")
def conversation_detail(cid: int, db: Session = Depends(get_db),
                        clinic_id: int = Depends(active_clinic_id),
                        _u: models.User = Depends(current_user)):
    conv = _conv_or_404(db, cid, clinic_id)
    cust = db.get(models.Customer, conv.customer_id)
    branch = db.get(models.Branch, conv.branch_id) if conv.branch_id else None
    agent = db.get(models.User, conv.assigned_user_id) if conv.assigned_user_id else None
    messages = (scoped(db, models.Message, clinic_id)
                .filter(models.Message.conversation_id == cid)
                .order_by(models.Message.created_at).all())
    conv.unread = False
    db.commit()
    return {
        "conversation": {
            "id": conv.id, "channel": conv.channel, "status": conv.status,
            "sales_stage": conv.sales_stage, "ai_enabled": conv.ai_enabled,
            "escalation_reason": conv.escalation_reason, "ai_summary": conv.ai_summary,
            "assigned_user_id": conv.assigned_user_id,
            "assigned_user_name": agent.name if agent else None,
            "branch_id": conv.branch_id, "branch_name": branch.name if branch else None,
        },
        "customer": {
            "id": cust.id, "name": cust.name, "nickname": cust.nickname or "",
            "phone": cust.phone, "email": cust.email,
            "channel": cust.channel, "pipeline_stage": cust.pipeline_stage,
            "temperature": cust.temperature, "lead_score": cust.lead_score,
            "budget": cust.budget, "concern": cust.concern, "interested": cust.interested,
            "avatar": cust.avatar or "", "channel_user_id": cust.channel_user_id or "",
        } if cust else None,
        "messages": [msg_dict(m) for m in messages],
    }


@router.post("/conversations/{cid}/messages")
def post_message(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
                 clinic_id: int = Depends(active_clinic_id),
                 user: models.User = Depends(current_user)):
    conv = _conv_or_404(db, cid, clinic_id)
    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text is required")
    # The AI owns the conversation until an admin explicitly takes it over —
    # otherwise a human reply races the AI's own answer to the same customer.
    if conv.ai_enabled:
        raise HTTPException(status_code=409, detail="takeover_required")
    msg = send_admin_message(db, conv, text, sender_name=user.name)
    return msg_dict(msg)


@router.post("/conversations/{cid}/charge")
def charge_custom(cid: int, data: dict = Body(...),
                  db: Session = Depends(get_db),
                  clinic_id: int = Depends(active_clinic_id),
                  user: models.User = Depends(require_role("branch_manager"))):
    """Admin-initiated custom charge — e.g. a negotiated price the admin approved.
    Creates a standalone payment (not tied to a booking, so no booking amount is
    overwritten) and posts the clinic's payment QR with that amount to the customer as
    an admin pay-card message; staff confirm the slip on Payments. Guarded to
    branch_manager / owner / super_admin."""
    conv = _conv_or_404(db, cid, clinic_id)
    cust = db.get(models.Customer, conv.customer_id)
    if not cust:
        raise HTTPException(status_code=404, detail="No customer on this conversation")
    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Enter an amount greater than 0")
    label = (data.get("label") or "").strip() or "ชำระเงิน"
    from app.services.billing import create_payment
    from app.services.promptpay import qr_image_url

    qr = qr_image_url()
    if not qr:
        raise HTTPException(status_code=503, detail="No payment QR is set up "
                            "(add web/assets/images/payment-qr.png)")
    payment = create_payment(db, customer=cust, amount=amount, ptype="custom")
    payment.clinic_id = clinic_id
    db.commit()
    pay_meta = {"url": qr, "kind": "qr", "amount": amount, "label": label,
                "payment_id": payment.id}
    text = (f"{label} ฿{int(amount):,} สแกน QR เพื่อโอนชำระได้เลยค่ะ "
            "แล้วส่งสลิปในแชทนี้ ทีมงานจะตรวจสอบให้นะคะ")
    msg = send_admin_message(db, conv, text, meta={"payment": pay_meta}, sender_name=user.name)
    return {"ok": True, "payment_id": payment.id, "amount": amount, "message": msg_dict(msg)}


@router.post("/conversations/{cid}/status")
def set_status(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
               clinic_id: int = Depends(active_clinic_id),
               _u: models.User = Depends(current_user)):
    conv = _conv_or_404(db, cid, clinic_id)
    status = data.get("status")
    if status not in ("new_lead", "interested", "booked", "paid", "followup"):
        raise HTTPException(status_code=400, detail="Invalid status")
    conv.status = status
    cust = db.get(models.Customer, conv.customer_id)
    if cust:
        cust.pipeline_stage = status
        db.add(models.Activity(clinic_id=clinic_id, customer_id=cust.id, type="status",
                               summary=f"Moved to {status.replace('_', ' ')}"))
    db.commit()
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": clinic_id, "summary": conv_summary(db, conv)})
    return {"ok": True, "status": status}


@router.post("/conversations/{cid}/takeover")
def takeover(cid: int, db: Session = Depends(get_db),
             clinic_id: int = Depends(active_clinic_id),
             user: models.User = Depends(current_user)):
    conv = _conv_or_404(db, cid, clinic_id)
    conv.ai_enabled = False
    conv.assigned_user_id = user.id
    if not conv.escalation_reason:
        conv.escalation_reason = "Manual takeover by admin"
    if not conv.ai_summary:
        msgs = (scoped(db, models.Message, clinic_id).filter_by(conversation_id=cid)
                .order_by(models.Message.created_at).all())
        last_c = next((m.text for m in reversed(msgs) if m.sender == "customer"), "")
        conv.ai_summary = (f"{len(msgs)} messages exchanged. Latest customer message: "
                           f"\"{last_c[:140]}\"")
    db.add(models.Message(clinic_id=clinic_id, conversation_id=cid, sender="system",
                          text=f"{user.name} took over the conversation. AI replies are paused."))
    db.commit()
    realtime.publish({"type": "conversation", "conversation_id": cid,
                      "clinic_id": clinic_id, "summary": conv_summary(db, conv)})
    realtime.publish({"type": "takeover", "conversation_id": cid, "clinic_id": clinic_id})
    return {"ok": True, "ai_enabled": False}


@router.post("/conversations/{cid}/return-to-ai")
def return_to_ai(cid: int, background_tasks: BackgroundTasks,
                 db: Session = Depends(get_db),
                 clinic_id: int = Depends(active_clinic_id),
                 user: models.User = Depends(current_user)):
    conv = _conv_or_404(db, cid, clinic_id)
    # If the customer's last message is still waiting, let the AI answer it right away.
    ai_replying = auto_return_to_ai(db, conv)
    if ai_replying:
        background_tasks.add_task(generate_ai_reply, cid)
    return {"ok": True, "ai_enabled": True, "ai_replying": ai_replying}


# --------------------------- admin WebSocket ---------------------------
@router.websocket("/ws")
async def admin_ws(websocket: WebSocket):
    sess = read_session(websocket.cookies.get(SESSION_COOKIE))
    if not sess or not sess.get("uid"):
        await websocket.close(code=1008)
        return
    my_clinic = sess.get("cid")
    await websocket.accept()
    last = realtime.head()
    ticks = 0
    try:
        while True:
            events, last = realtime.events_since(last)
            for e in events:
                # only deliver events for the admin's active clinic
                if e.get("clinic_id") in (None, my_clinic):
                    await websocket.send_json(e)
            ticks += 1
            if ticks % 30 == 0:
                await websocket.send_json({"type": "ping"})
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError, Exception):
        return
