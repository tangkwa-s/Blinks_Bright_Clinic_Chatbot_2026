"""Test Console routes — simulate inbound, AI sandbox, health checks."""
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.deps import active_clinic_id, require_role
from app.scope import scoped
from app.services.inbox import conv_summary, generate_ai_reply, handle_inbound

router = APIRouter(prefix="/api/test", tags=["test-console"])
TESTER = require_role()  # owner / super_admin only


@router.post("/simulate")
def simulate(background_tasks: BackgroundTasks, data: dict = Body(...),
             db: Session = Depends(get_db), cid: int = Depends(active_clinic_id),
             _u: models.User = Depends(TESTER)):
    """Inject an inbound web-chat message."""
    channel = "web"
    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text is required")
    name = (data.get("name") or "").strip() or f"{channel.title()} Tester"
    uid = data.get("channel_user_id") or f"{channel}_sim_{name.lower().replace(' ', '_')}"
    conv = handle_inbound(db, clinic_id=cid, channel=channel, channel_user_id=uid,
                          name=name, text=text)
    background_tasks.add_task(generate_ai_reply, conv.id)
    return {"ok": True, "conversation_id": conv.id, "summary": conv_summary(db, conv)}


@router.post("/mark-paid")
def mark_paid_test(data: dict = Body(...), db: Session = Depends(get_db),
                   cid: int = Depends(active_clinic_id), _u: models.User = Depends(TESTER)):
    """Simulate a confirmed transfer (no slip needed) so the whole paid
    flow — confirmation message on the channel + settled pay-card — can be tested
    end to end. Targets an explicit payment_id, or the newest pending payment of a
    conversation."""
    from app.services.billing import mark_paid

    payment = None
    if data.get("payment_id"):
        payment = (scoped(db, models.Payment, cid)
                   .filter(models.Payment.id == data["payment_id"]).first())
    elif data.get("conversation_id"):
        conv = (scoped(db, models.Conversation, cid)
                .filter(models.Conversation.id == data["conversation_id"]).first())
        if conv:
            bk_ids = [b.id for b in scoped(db, models.Booking, cid)
                      .filter_by(conversation_id=conv.id).all()]
            q = scoped(db, models.Payment, cid).filter(models.Payment.status == "pending")
            if bk_ids:
                payment = (q.filter(models.Payment.booking_id.in_(bk_ids))
                           .order_by(models.Payment.id.desc()).first())
            if not payment:
                payment = (scoped(db, models.Payment, cid)
                           .filter(models.Payment.status == "pending",
                                   models.Payment.customer_id == conv.customer_id)
                           .order_by(models.Payment.id.desc()).first())
    if not payment:
        raise HTTPException(status_code=404, detail="No pending payment found to mark paid")
    ok = mark_paid(db, payment, method="test")
    return {"ok": True, "payment_id": payment.id, "amount": payment.amount,
            "already_paid": not ok}


@router.post("/ai-sandbox")
def ai_sandbox(data: dict = Body(...), db: Session = Depends(get_db),
               cid: int = Depends(active_clinic_id),
               _u: models.User = Depends(TESTER)):
    """Run the AI on a message in isolation, exposing the retrieved KB context."""
    from app.ai import rag
    from app.ai.client import chat_completion, is_configured
    from app.ai.prompts import build_system_prompt

    text = (data.get("text") or "").strip()
    chunks = rag.retrieve(db, text, cid, k=5) if text else []
    context = "\n\n".join(f"[{c['title']}]\n{c['text']}" for c in chunks)
    reply = ""
    if not is_configured():
        reply = "(OpenAI is not configured — set OPENAI_API_KEY in .env)"
    elif text:
        try:
            resp = chat_completion(
                [{"role": "system", "content": build_system_prompt(context)},
                 {"role": "user", "content": text}],
                temperature=0.6, max_tokens=420)
            reply = (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            reply = f"(AI error: {exc})"
    return {"reply": reply, "chunks": chunks}


@router.get("/connections")
def connections(db: Session = Depends(get_db), cid: int = Depends(active_clinic_id),
                _u: models.User = Depends(TESTER)):
    """One-click health checks for every integration."""
    from app.ai.client import ping as openai_ping
    from app.services.promptpay import qr_image_url

    qr = qr_image_url()
    return {
        "openai": openai_ping(),
        "gemini": {"ok": bool(settings.gemini_api_key),
                   "detail": "API key present" if settings.gemini_api_key else "GEMINI_API_KEY not set"},
        "payment_qr": {"ok": bool(qr),
                       "detail": f"QR image found ({qr})" if qr
                                 else "no QR — add web/assets/images/payment-qr.png"},
    }
