"""Channel routes — the web chat widget.

The widget is clinic-specific: it passes a clinic slug.
"""
import asyncio
import secrets
from datetime import datetime

from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, Form,
                     HTTPException, UploadFile, WebSocket, WebSocketDisconnect)
from sqlalchemy.orm import Session

from app import models, realtime
from app.avatars import save_chat_image
from app.database import get_db
from app.scope import scoped
from app.security import make_chat_token, read_chat_token
from app.services.inbox import conv_summary, generate_ai_reply, handle_inbound, msg_dict

router = APIRouter(prefix="/api", tags=["channels"])

# The first thing a visitor reads, so it says what the assistant can actually do and
# how to start — the old "สนใจบริการไหน ทักมาได้เลย" left a first-time visitor guessing.
# The widget renders shortcut chips under it; every item here is something a tool or
# the KB really answers (medical questions are routed to a doctor, so it says so).
WEB_GREETING = {
    "th": ("สวัสดีค่ะ ยินดีต้อนรับสู่ {name} 🌿 ดิฉันเป็นผู้ช่วย AI ของคลินิก ช่วยได้เรื่อง\n"
           "- ราคาและรายละเอียดทรีตเมนต์\n"
           "- โปรโมชัน สาขา และเวลาเปิด-ปิด\n"
           "- จองคิวและชำระมัดจำ (สำหรับสมาชิก)\n"
           "- ดูรูปที่ส่งมา เช่น สลิปโอนมัดจำ หรือป้ายราคา (กดปุ่มรูปภาพด้านล่าง)\n\n"
           "เลือกหัวข้อด้านล่าง หรือพิมพ์คำถามได้เลยค่ะ "
           "ส่วนคำถามเรื่องอาการหรือผลข้างเคียง ทีมแพทย์จะเป็นผู้ดูแลให้นะคะ"),
    "en": ("Hello, welcome to {name} 🌿 I'm the clinic's AI assistant. I can help with\n"
           "- treatment prices and details\n"
           "- promotions, branches and opening hours\n"
           "- booking a slot and paying the deposit (members)\n"
           "- photos you send, such as a deposit slip or a price sign (tap the photo button below)\n\n"
           "Pick a topic below or type your question. "
           "For symptoms or side effects, our doctors will take care of you."),
}


def web_greeting(clinic_name: str, lang: str = "th") -> str:
    return WEB_GREETING["en" if lang == "en" else "th"].format(name=clinic_name)

def _resolve_clinic(db: Session, slug) -> models.Clinic | None:
    """Resolve a clinic by slug, falling back to the first active clinic."""
    if slug:
        c = (db.query(models.Clinic)
             .filter_by(slug=str(slug), status="active").first())
        if c:
            return c
    return (db.query(models.Clinic).filter_by(status="active")
            .order_by(models.Clinic.id).first())


# ----------------------------- web chat -----------------------------
def _customer_safe(d: dict) -> dict:
    """Strip staff-only fields from a msg_dict() result before it reaches the
    customer's own browser. msg_dict() is shared with the staff-only inbox
    (app/routers/conversations.py) and has no notion of who's asking — every path
    below is public and unauthenticated, so the redaction has to happen here.
    Currently just ``grounding`` (the AI's raw reference trail: catalog prices,
    verbatim admin message text, tool-call JSON) — add any future staff-only
    meta-derived field to this list too, not just to msg_dict().
    """
    return {k: v for k, v in d.items() if k != "grounding"}


@router.post("/channels/web/start")
def web_start(data: dict = Body(default={}), db: Session = Depends(get_db)):
    clinic = _resolve_clinic(db, data.get("clinic"))
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not available")
    name = (data.get("name") or "").strip() or "Web Visitor"
    uid = "web_" + secrets.token_hex(6)
    cust = models.Customer(clinic_id=clinic.id, name=name, channel="web",
                           channel_user_id=uid, pipeline_stage="new_lead",
                           temperature="warm", lead_score=20)
    db.add(cust)
    db.flush()
    db.add(models.Activity(clinic_id=clinic.id, customer_id=cust.id, type="system",
                           summary="New lead from web chat"))
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               status="new_lead", sales_stage="greeting",
                               last_message_at=datetime.utcnow())
    db.add(conv)
    db.flush()
    greeting = models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                              sender="ai", text=web_greeting(clinic.name, data.get("lang")))
    db.add(greeting)
    db.commit()
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": clinic.id, "summary": conv_summary(db, conv)})
    return {"token": make_chat_token(conv.id), "conversation_id": conv.id, "member": False,
            "clinic": {"name": clinic.name, "slug": clinic.slug,
                       "logo": clinic.logo, "tagline": clinic.tagline},
            "messages": [_customer_safe(msg_dict(greeting))]}


@router.get("/channels/web/messages")
def web_messages(token: str, db: Session = Depends(get_db)):
    cid = read_chat_token(token)
    conv = db.get(models.Conversation, cid) if cid else None
    if not conv:
        raise HTTPException(status_code=401, detail="Invalid chat session")
    msgs = (scoped(db, models.Message, conv.clinic_id).filter_by(conversation_id=conv.id)
            .order_by(models.Message.created_at).all())
    clinic = db.get(models.Clinic, conv.clinic_id) if conv.clinic_id else None
    cust = db.get(models.Customer, conv.customer_id)
    return {"conversation_id": conv.id,
            # a portal member's own thread: the widget's "book" shortcut chats as usual,
            # an anonymous visitor's is sent to sign up (tools.py::booking_requires_signup)
            "member": bool(cust and cust.password_hash),
            # same clinic block as web_start, so the widget can restore its branding
            "clinic": ({"name": clinic.name, "slug": clinic.slug,
                        "logo": clinic.logo, "tagline": clinic.tagline}
                       if clinic else None),
            "messages": [_customer_safe(msg_dict(m)) for m in msgs if m.sender != "system"]}


@router.post("/channels/web/message")
def web_message(background_tasks: BackgroundTasks, data: dict = Body(...),
                db: Session = Depends(get_db)):
    cid = read_chat_token(data.get("token"))
    conv = db.get(models.Conversation, cid) if cid else None
    if not conv:
        raise HTTPException(status_code=401, detail="Invalid chat session")
    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")
    cust = db.get(models.Customer, conv.customer_id)
    handle_inbound(db, clinic_id=conv.clinic_id, channel="web",
                   channel_user_id=cust.channel_user_id, name=cust.name, text=text)
    background_tasks.add_task(generate_ai_reply, conv.id)
    return {"ok": True}


@router.post("/channels/web/image")
def web_image(background_tasks: BackgroundTasks, token: str = Form(...),
              text: str = Form(""), file: UploadFile = File(...),
              db: Session = Depends(get_db)):
    """A customer sends a photo (payment slip, price sign, skin photo...) in web chat.

    The file is validated (PNG/JPG/WebP, <= 4 MB) and stored; the path rides on the
    message's ``meta.image`` so the AI reads it as part of that turn (chat.py). While a
    payment is owed, a slip takes a different path first (services/slips.py): the hold
    pauses and a person checks it."""
    cid = read_chat_token(token)
    conv = db.get(models.Conversation, cid) if cid else None
    if not conv:
        raise HTTPException(status_code=401, detail="Invalid chat session")
    url = save_chat_image(file, f"c{conv.id}")
    caption = (text or "").strip()[:1000] or "📷"
    cust = db.get(models.Customer, conv.customer_id)
    handle_inbound(db, clinic_id=conv.clinic_id, channel="web",
                   channel_user_id=cust.channel_user_id, name=cust.name,
                   text=caption, meta={"image": url})
    from app.services.slips import handle_customer_image
    background_tasks.add_task(handle_customer_image, conv.id, url)
    return {"ok": True, "image": url}


@router.websocket("/chat-stream/{token}")
async def chat_ws(websocket: WebSocket, token: str):
    cid = read_chat_token(token)
    if not cid:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    last = realtime.head()
    ticks = 0
    try:
        while True:
            events, last = realtime.events_since(last)
            for e in events:
                # Whitelist what a CUSTOMER's browser may receive. Internal events
                # ('conversation' summaries with lead_score / temperature /
                # escalation_reason / assigned agent, 'takeover', …) also carry a
                # matching conversation_id but must never leave the admin side.
                if (e.get("conversation_id") == cid
                        and e.get("type") in ("stream", "stream_cancel", "message", "typing",
                                              "payment")):
                    if e.get("type") == "message":
                        # Rebuild rather than mutate: realtime.events_since() returns
                        # references into the SAME shared event list admin_ws also
                        # polls, so stripping the key in place would silently strip
                        # it from the staff side too if their poll lands after this one.
                        e = {**e, "message": _customer_safe(e["message"])}
                    await websocket.send_json(e)
            ticks += 1
            if ticks % 30 == 0:
                await websocket.send_json({"type": "ping"})
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError, Exception):
        return
