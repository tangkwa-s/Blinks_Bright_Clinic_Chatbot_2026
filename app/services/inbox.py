"""Messaging pipeline — inbound handling, AI replies, admin replies.

Every conversation belongs to a clinic; inbound routing, AI replies and admin
replies all carry the clinic id so realtime events stay tenant-isolated.
"""
from datetime import datetime, timedelta

from app import models, realtime
from app.database import SessionLocal
from app.scope import scoped


_TOOL_SOURCE = {
    "search_knowledge_base": "Knowledge Base",
    "list_treatments": "Treatments",
    "list_promotions": "Promotions",
    "check_availability": "Availability",
    "book_appointment": "Booking",
    "create_payment_link": "Payment",
    "request_human_help": "Human handoff",
}


def msg_dict(m: models.Message) -> dict:
    meta = m.meta or {}
    d = {
        "id": m.id, "conversation_id": m.conversation_id, "sender": m.sender,
        "text": m.text, "intent": m.intent, "confidence": m.confidence,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
    if meta.get("image"):
        d["image"] = meta["image"]  # photo the customer sent (web widget / inbox bubble)
    payment = meta.get("payment")
    if payment and payment.get("url"):
        d["payment"] = payment  # drives the pay-card in the web/admin chat UIs
    if meta.get("slip"):
        d["slip"] = meta["slip"]  # pauses / resumes the pay-card countdown (slips.py)
    if meta.get("signup"):
        d["signup"] = True  # members-only booking: the widget shows a sign-up button
    if m.sender == "admin" and m.sender_name:
        d["sender_name"] = m.sender_name  # who replied (staff name / automation label)
    if m.sender == "admin":
        # automation/campaign trace — drives the localized tag + the
        # "not delivered" chip on the bubble (mirrors the AI 'ungrounded' flag)
        if meta.get("automation"):
            d["automation"] = True
        if meta.get("delivery") == "failed":
            d["delivery_failed"] = True
    if m.sender == "ai":
        # Which sources the reply was grounded on (KB + the tools the AI called),
        # surfaced in the admin inbox so staff can see where each fact came from.
        sources, seen = [], set()
        if meta.get("kb"):
            sources.append("Knowledge Base")
            seen.add("Knowledge Base")
        for t in meta.get("tools", []):
            label = _TOOL_SOURCE.get(t)
            if label and label not in seen:
                sources.append(label)
                seen.add(label)
        if sources:
            d["sources"] = sources
        if meta.get("grounded") is False:
            d["ungrounded"] = True
        # Guardrail hits the deterministic text filters could not safely auto-strip (a
        # mid-sentence offer claim, an ungrounded discount) or can never edit at all
        # (payment_unverified) — computed every turn by app/ai/guardrails.py but never
        # read anywhere until now, so a flagged reply reached no one but this JSON blob.
        reasons = []
        if meta.get("offer_flags"):
            reasons.append("offer")
        if meta.get("discount_flags"):
            reasons.append("discount")
        if meta.get("payment_unverified"):
            reasons.append("payment")
        if reasons:
            d["flag_reasons"] = reasons
        # The raw reference trail this reply was generated from (KB context, catalog
        # prices, admin messages, every tool result) — set by app/ai/chat.py::respond.
        # STAFF-FACING ONLY: callers on the public chat-widget surface
        # (app/routers/channels.py) must strip this key before it reaches the customer.
        grounding = meta.get("grounding")
        if grounding:
            d["grounding"] = grounding
    return d


def conv_summary(db, conv: models.Conversation) -> dict:
    cust = db.get(models.Customer, conv.customer_id)
    last = (scoped(db, models.Message, conv.clinic_id)
            .filter(models.Message.conversation_id == conv.id)
            .order_by(models.Message.id.desc()).first())
    return {
        "id": conv.id, "customer_id": conv.customer_id,
        "customer_name": cust.name if cust else "Unknown",
        "customer_avatar": (cust.avatar if cust else "") or "",
        "channel": conv.channel, "status": conv.status, "sales_stage": conv.sales_stage,
        "ai_enabled": conv.ai_enabled, "assigned_user_id": conv.assigned_user_id,
        "branch_id": conv.branch_id, "escalation_reason": conv.escalation_reason,
        "ai_summary": conv.ai_summary or "",
        "unread": conv.unread,
        "temperature": cust.temperature if cust else "cold",
        "lead_score": cust.lead_score if cust else 0,
        "last_message": (last.text if last else ""),
        "last_sender": (last.sender if last else ""),
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
    }


def phone_key(phone: str) -> str:
    """A comparable phone key: digits only, last 9 — so 081xxxxxxx, 6681xxxxxxx and
    +6681xxxxxxx all resolve to the same person. Lives here beside the golden-record
    routing because everything that decides "is this the same customer?" must agree
    on it: the duplicate finder, and the identity check on a new account."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else ""


def _resolve_golden(db, cust):
    """Follow merged_into_id to the surviving golden record (cycle-safe), so inbound
    from a merged-away channel identity keeps landing on the unified customer."""
    seen = set()
    while cust and cust.merged_into_id and cust.id not in seen:
        seen.add(cust.id)
        nxt = db.get(models.Customer, cust.merged_into_id)
        if not nxt:
            break
        cust = nxt
    return cust


# How long after a broadcast delivery an inbound message still counts as a
# response to that campaign.
CAMPAIGN_RESPONSE_WINDOW_DAYS = 7


def _track_campaign_reply(db, cust) -> None:
    """Credit an inbound message as a response to the most recent broadcast
    campaign delivered to this customer within the response window.

    One indexed query on the hot path (activities.customer_id); the common case
    (no recent delivery) does no writes. Credited once per campaign+customer.
    Overlapping campaigns: only the newest delivery is credited — a deliberate
    simplification. Never raises — tracking must not block message ingestion.
    The row rides the caller's transaction; no commit here.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=CAMPAIGN_RESPONSE_WINDOW_DAYS)
        # One fetch returns both delivery rows (type='campaign') and prior reply
        # rows (type='campaign_reply' — always newer than their delivery, so
        # inside the window whenever the delivery is).
        rows = (scoped(db, models.Activity, cust.clinic_id)
                .filter(models.Activity.customer_id == cust.id,
                        models.Activity.ref_type == "campaign",
                        models.Activity.created_at >= cutoff).all())
        # "· delivered" suffix is coupled to the summary format written by
        # broadcast.deliver_campaign — change one, change the other.
        delivered = [a for a in rows if a.type == "campaign" and a.ref_id is not None
                     and (a.summary or "").endswith(" · delivered")]
        if not delivered:
            return
        campaign_id = max(delivered, key=lambda a: a.id).ref_id
        if any(a.type == "campaign_reply" and a.ref_id == campaign_id for a in rows):
            return
        db.add(models.Activity(
            clinic_id=cust.clinic_id, customer_id=cust.id, type="campaign_reply",
            summary=f"{cust.name} · {cust.channel or 'web'} · replied",
            ref_type="campaign", ref_id=campaign_id))
    except Exception as exc:  # pragma: no cover
        print("[inbox] campaign reply tracking error:", exc)


def handle_inbound(db, *, clinic_id: int, channel: str, channel_user_id: str,
                   name: str, text: str, branch_id=None,
                   meta: dict | None = None) -> models.Conversation:
    """Route an inbound customer message into a conversation within one clinic."""
    cust = (scoped(db, models.Customer, clinic_id)
            .filter_by(channel=channel, channel_user_id=channel_user_id).first())
    if cust and cust.merged_into_id:
        cust = _resolve_golden(db, cust)
    existed = cust is not None
    if not cust:
        cust = models.Customer(
            clinic_id=clinic_id, name=name or "Web Visitor", channel=channel,
            channel_user_id=channel_user_id, branch_id=branch_id,
            pipeline_stage="new_lead", temperature="warm", lead_score=20,
        )
        db.add(cust)
        db.flush()
        db.add(models.Activity(clinic_id=clinic_id, customer_id=cust.id, type="system",
                               summary=f"New lead from {channel} channel"))

    conv = (scoped(db, models.Conversation, clinic_id)
            .filter_by(customer_id=cust.id, channel=channel)
            .order_by(models.Conversation.id.desc()).first())
    if not conv:
        # branch_id comes ONLY from the caller (a branch-bound channel). Never inherit
        # the customer's home branch here: it is just where they went LAST time, and
        # pre-locking it made the AI assert a branch the customer never chose in this
        # chat (sometimes the wrong one). The home branch is surfaced as a suggestion
        # to CONFIRM instead (tools' usual-branch note + the booking-checklist hint).
        conv = models.Conversation(clinic_id=clinic_id, customer_id=cust.id, channel=channel,
                                   branch_id=branch_id, status="new_lead",
                                   sales_stage="greeting")
        db.add(conv)
        db.flush()

    msg = models.Message(clinic_id=clinic_id, conversation_id=conv.id,
                         sender="customer", text=text, meta=meta or {})
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    conv.unread = True
    cust.last_activity_at = datetime.utcnow()
    if existed:  # a brand-new customer cannot have received a campaign
        _track_campaign_reply(db, cust)
    db.commit()

    realtime.publish({"type": "message", "conversation_id": conv.id,
                      "clinic_id": clinic_id, "message": msg_dict(msg)})
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": clinic_id, "summary": conv_summary(db, conv)})
    return conv


def _ai_still_enabled(db, conversation_id: int) -> bool:
    """``Conversation.ai_enabled`` as it is in the DATABASE right now.

    Not ``conv.ai_enabled``: that attribute was loaded when generate_ai_reply began
    and the takeover route writes from another session, so the object in hand can
    say True for the whole of a 10-second generation while the row already says
    False. One indexed SELECT of one column; the autoflush it triggers is harmless
    (respond's own writes were committed by the tools that made them)."""
    return bool(db.query(models.Conversation.ai_enabled)
                .filter(models.Conversation.id == conversation_id).scalar())


def _suppress_inflight_reply(db, conv, text: str, meta: dict) -> None:
    """A reply finished generating AFTER a human took the conversation over.

    It is not sent to the customer — it would land under the human's own words and
    could contradict them — but it is not discarded either: the admin gets it as a
    ``system`` message (the widget hides system messages; the inbox shows them), so a
    payment link or booking the model produced in that turn stays visible and can be
    forwarded by hand. The partial bubble the widget/inbox streamed meanwhile is
    withdrawn with a ``stream_cancel`` event, and the suppression is logged to the
    WebhookEvent table like the pre-generation skip, so "the bot went quiet" is
    explainable from the Test Console.
    """
    cid = conv.clinic_id
    note = models.Message(
        clinic_id=cid, conversation_id=conv.id, sender="system",
        text=("AI reply withheld — a teammate took over while it was being written. "
              "It was NOT sent to the customer. Draft:\n" + (text or "").strip()),
        meta={**(meta or {}), "suppressed": True},
    )
    db.add(note)
    db.add(models.WebhookEvent(
        clinic_id=cid, source=conv.channel, event_type="reply_suppressed", processed=False,
        note="Human takeover happened during AI generation — the finished reply was "
             "withheld and left for the admin as a system note."))
    db.commit()
    realtime.publish({"type": "stream_cancel", "conversation_id": conv.id, "clinic_id": cid})
    realtime.publish({"type": "message", "conversation_id": conv.id, "clinic_id": cid,
                      "message": msg_dict(note)})


def generate_ai_reply(conversation_id: int) -> None:
    """Background task — orchestrate the AI reply, deliver it, then analyse."""
    db = SessionLocal()
    try:
        conv = db.get(models.Conversation, conversation_id)
        if not conv or not conv.ai_enabled:
            # The AI is off (human takeover). Say so to the customer once per wait:
            # silence left them typing into a chat nobody was answering.
            if conv:
                notify_waiting_for_staff(db, conv)
            return
        cid = conv.clinic_id
        # A customer writing in is the moment their own lapsed hold matters most. The
        # 60-second sweep job narrows the lag, but only THIS call is ordered with the
        # reply: it puts the lapse notice in the thread BEFORE respond() builds its
        # history, so the reply is written knowing the customer has already been told.
        try:
            from app.services.booking import sweep_expired_holds

            sweep_expired_holds(db, cid)
        except Exception as exc:  # pragma: no cover
            print("[inbox] hold sweep skipped:", exc)
        realtime.publish({"type": "typing", "conversation_id": conv.id, "clinic_id": cid})
        from app.ai.chat import respond
        from app.ai.sales import analyze

        # stream partial replies to the chat as the model generates them
        published = {"len": 0}

        def on_token(full_text: str) -> None:
            if len(full_text) - published["len"] >= 14:
                published["len"] = len(full_text)
                realtime.publish({"type": "stream", "conversation_id": conv.id,
                                  "clinic_id": cid, "text": full_text})

        result = respond(db, conv, on_token=on_token)
        text = result["text"]
        meta = result.get("meta", {})
        # A human may have taken over WHILE the model was generating: the takeover
        # route flips ai_enabled, but this task only read it before starting. Seen in
        # a live run: the admin took over and quoted a negotiated ฿4,500, and three
        # seconds later the in-flight AI reply landed underneath it with the ฿25,000
        # standard price. Re-read the flag from the DB (a fresh SELECT, not the ORM
        # object this session has been holding since the start) and, if the AI is off
        # NOW, keep the reply out of the customer's thread. The text is not thrown
        # away — anything the model did in that turn (a payment link, a booking) must
        # not vanish silently — it goes to the admin as a system note instead.
        if not _ai_still_enabled(db, conv.id):
            _suppress_inflight_reply(db, conv, text, meta)
            try:
                analyze(db, conv)   # still about the CUSTOMER's message, not the reply
            except Exception as exc:  # pragma: no cover
                print("[inbox] analyze error:", exc)
            realtime.publish({"type": "conversation", "conversation_id": conv.id,
                              "clinic_id": cid, "summary": conv_summary(db, conv)})
            return
        msg = models.Message(
            clinic_id=cid, conversation_id=conv.id, sender="ai", text=text,
            confidence=0.9 if meta.get("grounded", True) else 0.5, meta=meta,
        )
        db.add(msg)
        conv.last_message_at = datetime.utcnow()
        db.commit()
        realtime.publish({"type": "message", "conversation_id": conv.id,
                          "clinic_id": cid, "message": msg_dict(msg)})

        cust = db.get(models.Customer, conv.customer_id)
        from app.channels.adapters import get_adapter

        get_adapter(conv.channel).send(db, conv, cust, text)

        # post-reply analysis: CRM sync, lead scoring, intent logging, escalation
        try:
            analyze(db, conv)
        except Exception as exc:  # pragma: no cover
            print("[inbox] analyze error:", exc)
        realtime.publish({"type": "conversation", "conversation_id": conv.id,
                          "clinic_id": cid, "summary": conv_summary(db, conv)})
    except Exception as exc:  # pragma: no cover
        print("[inbox] ai reply error:", exc)
    finally:
        db.close()


def broadcast_to_customer(db, customer: models.Customer, text: str,
                          sender_name: str = "") -> bool:
    """Deliver a one-off broadcast to a customer on their OWN channel.

    The message is recorded in their conversation (delivered live if the widget
    is open). Returns True if the message was sent/queued.

    Every attempt — success OR failure — persists a Message in the customer's
    conversation with the delivery outcome stamped in ``meta`` (``automation``
    + ``delivery``), so admins always see a truthful trace in the thread and
    can retry manually.
    """
    if not (text or "").strip():
        return False
    ch = customer.channel or "web"

    conv = (scoped(db, models.Conversation, customer.clinic_id)
            .filter_by(customer_id=customer.id)
            .order_by(models.Conversation.id.desc()).first())
    if not conv:
        conv = models.Conversation(
            clinic_id=customer.clinic_id, customer_id=customer.id, channel=ch,
            branch_id=customer.branch_id, status=customer.pipeline_stage or "new_lead",
            sales_stage="broadcast", last_message_at=datetime.utcnow())
        db.add(conv)
        db.flush()

    msg = models.Message(clinic_id=customer.clinic_id, conversation_id=conv.id,
                         sender="admin", sender_name=sender_name or "", text=text)
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    db.flush()

    delivered = False
    from app.channels.adapters import get_adapter
    try:
        delivered = bool(get_adapter(ch).send(db, conv, customer, text))
    except Exception as exc:  # pragma: no cover
        print("[broadcast] send error:", exc)

    # Stamp the outcome AFTER the send attempt, BEFORE publishing — a fresh
    # dict, not an in-place mutation, so the JSON column is marked dirty.
    meta = {**(msg.meta or {}), "automation": True,
            "delivery": "sent" if delivered else "failed"}
    msg.meta = meta

    realtime.publish({"type": "message", "conversation_id": conv.id,
                      "clinic_id": customer.clinic_id, "message": msg_dict(msg)})
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": customer.clinic_id, "summary": conv_summary(db, conv)})
    return delivered


def send_admin_message(db, conv: models.Conversation, text: str, meta=None,
                       sender_name: str = "") -> models.Message:
    """An admin replies in a conversation. ``meta`` (e.g. ``{"payment": {...}}``)
    rides along on the message so an admin can send a pay-card too.
    ``sender_name`` records WHO replied (shown as the bubble tag in both chat UIs)."""
    msg = models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                         sender="admin", sender_name=sender_name or "",
                         text=text, meta=meta or {})
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    conv.unread = False
    db.commit()
    realtime.publish({"type": "message", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "message": msg_dict(msg)})
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "summary": conv_summary(db, conv)})
    cust = db.get(models.Customer, conv.customer_id)
    from app.channels.adapters import get_adapter

    get_adapter(conv.channel).send(db, conv, cust, text)
    return msg


# What the customer hears while the AI is paused for a person. No figures: tools.py reads
# clinic-side messages for prices already quoted. Sent as sender="ai" (like the slip and
# hold notices) so the assistant remembers saying it once it is handed back.
WAITING_TH = ("ได้รับข้อความแล้วค่ะ 🙏 ตอนนี้ส่งต่อให้ทีมงานดูแลแล้ว "
              "แอดมินจะตอบกลับในแชทนี้โดยเร็วที่สุดนะคะ")
WAITING_EN = ("Thanks, we've got your message. 🙏 It has been passed to our team, and an "
              "admin will reply in this chat as soon as possible.")
HANDOFF_TH = ("เรื่องนี้ขอส่งต่อให้ทีมงานดูแลนะคะ 🙏 "
              "แอดมินจะตอบกลับในแชทนี้โดยเร็วที่สุดค่ะ")
HANDOFF_EN = ("Let me pass this to our team. 🙏 An admin will reply in this chat as soon "
              "as possible.")


def _is_waiting_notice(m) -> bool:
    return bool((m.meta or {}).get("waiting_notice"))


def _recent_non_system(db, conv):
    return (scoped(db, models.Message, conv.clinic_id).filter_by(conversation_id=conv.id)
            .filter(models.Message.sender != "system")
            .order_by(models.Message.id.desc()).limit(50).all())


def _last_exchange_message(db, conv):
    """The newest message that is part of the actual conversation: not a system note
    and not a waiting notice, which only says that nobody has answered yet."""
    return next((m for m in _recent_non_system(db, conv) if not _is_waiting_notice(m)), None)


def notify_waiting_for_staff(db, conv, *, handoff: bool = False) -> bool:
    """Tell the customer a person has their message, once per wait, while the AI is
    paused. Nothing is sent once a staff member has spoken since the AI's last reply
    (they are in the conversation) or a notice already covers this wait.

    ``handoff`` is the escalation moment itself, straight after the AI's own reply,
    where "we've got your message" would read oddly."""
    for m in _recent_non_system(db, conv):
        if m.sender == "admin" and not (m.meta or {}).get("automation"):
            return False                 # a person is already answering
        if m.sender == "ai":
            if _is_waiting_notice(m):
                return False             # already told them, for this wait
            break                        # the AI's last reply: the wait starts after it
    from app.services.slips import post_notice

    en = _conversation_language(db, conv) == "en"
    if handoff:
        text = HANDOFF_EN if en else HANDOFF_TH
    else:
        text = WAITING_EN if en else WAITING_TH
    post_notice(db, conv, text, {"waiting_notice": True})
    return True


def auto_return_to_ai(db, conv: models.Conversation, *,
                      note: str = "Conversation handed back to the AI assistant.") -> bool:
    """Flip a conversation back to AI-handled and record why, in the thread. Shared by
    the admin's manual 'Return to AI' button (conversations.py) and the stale-takeover
    sweep below, so both write the exact same state change and a future reader can't
    end up trusting two different versions of "what happens on return".

    Returns True if the customer's latest (non-system) message is still unanswered —
    the caller's cue to trigger generate_ai_reply. A system message is deliberately NOT
    read back by chat.py's history or the web widget (both drop sender='system'), so it
    never substitutes for an actual reply to the customer.
    """
    conv.ai_enabled = True
    conv.escalation_reason = ""
    db.add(models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                          sender="system", text=note))
    db.commit()
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "summary": conv_summary(db, conv)})
    last = _last_exchange_message(db, conv)
    return bool(last and last.sender == "customer")


def sweep_stale_takeovers(db, clinic_id: int, now: datetime | None = None) -> int:
    """Auto-return one clinic's stale human takeovers to the AI.

    A takeover (manual, or the automatic 'serious' escalation in sales.py::analyze)
    pauses the AI so a person can handle the conversation — but if nobody actually
    replies, the customer is left with silence indefinitely; there was no mechanism
    that ever reverted this on its own. This sweep triggers once the customer's own
    latest message has sat unanswered longer than settings.takeover_timeout_minutes.

    Measured off ``last_message_at`` (bumped by every message, any sender), not off
    when the takeover began: a staff member actively replying keeps that timestamp
    fresh and is never interrupted, no matter how long ago they took over. Only a
    conversation whose latest non-system message is truly from the customer (nobody
    has said anything back yet) is reverted — one where the admin already replied and
    is simply waiting on the customer is left alone; there is nothing to hand back.
    """
    from app.config import settings

    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=max(1, settings.takeover_timeout_minutes))
    n = 0
    convs = (scoped(db, models.Conversation, clinic_id)
            .filter(models.Conversation.ai_enabled.is_(False),
                    models.Conversation.last_message_at.isnot(None),
                    models.Conversation.last_message_at <= cutoff).all())
    for conv in convs:
        # the waiting notice is not an answer, so it must not make the wait look over
        last = _last_exchange_message(db, conv)
        if not last or last.sender != "customer":
            continue   # a human already replied — just waiting on the customer, not stale
        note = (f"No reply from staff within {settings.takeover_timeout_minutes} "
               "minutes — conversation automatically handed back to the AI assistant.")
        if auto_return_to_ai(db, conv, note=note):
            generate_ai_reply(conv.id)
            n += 1
    return n


def notify_payment_paid(db, payment, outcome: str = "confirmed") -> None:
    """Tell the customer their payment went through, in their web chat.
    Called once from ``mark_paid`` after the paid
    cascade commits. Also flips the original pay-card message to a paid snapshot
    so reopening the thread shows it settled, not still 'pay now'.

    ``outcome`` is what ``booking.confirm_paid_booking`` actually did. ``reinstated`` and
    ``slot_gone`` both need saying out loud: in each case the customer has already been
    told their held slot was released, and a plain "your booking is confirmed" would be
    the second of two contradictory messages."""
    customer = db.get(models.Customer, payment.customer_id) if payment.customer_id else None
    if not customer:
        return
    conv = None
    bk = db.get(models.Booking, payment.booking_id) if payment.booking_id else None
    if bk and bk.conversation_id:
        conv = db.get(models.Conversation, bk.conversation_id)
    if conv is None:
        conv = (db.query(models.Conversation).filter_by(customer_id=customer.id)
                .order_by(models.Conversation.id.desc()).first())
    if conv is None:
        return

    # mark the matching pay-card message as paid (its meta is an immutable snapshot)
    for m in db.query(models.Message).filter_by(conversation_id=conv.id).all():
        pm = (m.meta or {}).get("payment")
        if pm and pm.get("payment_id") == payment.id and not pm.get("paid"):
            m.meta = {**(m.meta or {}), "payment": {**pm, "paid": True}}

    from app.services.slips import clear_slip_flag
    clear_slip_flag(db, conv)
    # No amount in any of these: they are sender="ai" (see below), and tools.py reads the
    # clinic side's own messages for prices it has already quoted — a deposit figure here
    # would be taken as a price the customer was given.
    if outcome in ("reinstated", "slot_gone") and bk:
        svc = db.get(models.Service, bk.service_id) if bk.service_id else None
        en = _conversation_language(db, conv) == "en"
        name = (svc.name if svc else ("your appointment" if en else "ทรีตเมนต์"))
        if outcome == "reinstated":
            text = ("We've received your payment. ✅ The hold on your " f"{name} "
                    f"appointment on {bk.slot_at:%d %b} at {bk.slot_at:%H:%M} had already "
                    "run out, but the time was still free, so we've confirmed your original "
                    "booking. See you then."
                    if en else
                    f"ได้รับการชำระเงินเรียบร้อยแล้วค่ะ ✅ คิว {name} "
                    f"วันที่ {bk.slot_at:%d/%m} เวลา {bk.slot_at:%H:%M} น. "
                    "หมดเวลาถือคิวไปก่อนหน้านี้ แต่เวลานั้นยังว่างอยู่ "
                    "ทางเราจึงยืนยันคิวเดิมให้เรียบร้อยแล้วนะคะ แล้วเจอกันค่ะ")
        else:
            # No refund promised, no replacement time invented, no pretence that the
            # appointment exists. What is true: we have their money and a person will call.
            text = ("We've received your payment. ✅ I'm very sorry, though — the hold "
                    f"on your {name} appointment on {bk.slot_at:%d %b} at "
                    f"{bk.slot_at:%H:%M} ran out before the payment reached us, and that time "
                    "has since been taken. Your payment is safe with the clinic; our team "
                    "will contact you shortly to arrange a new time."
                    if en else
                    "ได้รับการชำระเงินเรียบร้อยแล้วค่ะ ✅ แต่ต้องขออภัยจริง ๆ นะคะ "
                    f"คิว {name} วันที่ {bk.slot_at:%d/%m} เวลา {bk.slot_at:%H:%M} น. "
                    "หมดเวลาถือคิวไปก่อนที่การชำระเงินจะเข้าระบบ และเวลานั้นมีท่านอื่นจองไปแล้วค่ะ "
                    "เงินของคุณยังอยู่กับทางคลินิก ไม่ได้หายไปไหนนะคะ "
                    "ทีมงานจะติดต่อกลับเพื่อจัดเวลาใหม่ให้โดยเร็วที่สุดค่ะ")
    elif bk:
        svc = db.get(models.Service, bk.service_id) if bk.service_id else None
        br = db.get(models.Branch, bk.branch_id) if bk.branch_id else None
        if _conversation_language(db, conv) == "en":
            text = ("We've received your payment. ✅ Your booking is confirmed: "
                    f"{svc.name if svc else 'your appointment'} on {bk.slot_at:%d %b} at "
                    f"{bk.slot_at:%H:%M}" + (f", {br.name}" if br else "") + ". See you then!")
        else:
            text = ("ได้รับการชำระเงินเรียบร้อยแล้วค่ะ ✅ การจองของคุณได้รับการยืนยันแล้ว "
                    f"{svc.name if svc else 'ทรีตเมนต์'} วันที่ {bk.slot_at:%d/%m} "
                    f"เวลา {bk.slot_at:%H:%M} น." + (f" ที่ {br.name}" if br else "")
                    + " แล้วพบกันนะคะ")
    else:
        text = "ได้รับการชำระเงินเรียบร้อยแล้วค่ะ ✅ ขอบคุณค่ะ"
    # sender="ai", like notify_hold_expired: a system message is hidden by the widget on
    # reload and dropped from the model's history — this confirmation must survive both.
    msg = models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                         sender="ai", text=text)
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    db.commit()
    realtime.publish({"type": "message", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "message": msg_dict(msg)})
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "summary": conv_summary(db, conv)})
    try:
        from app.channels.adapters import get_adapter
        get_adapter(conv.channel).send(db, conv, customer, text)
    except Exception as exc:  # pragma: no cover
        print("[inbox] payment notify send error:", exc)


def _conversation_language(db, conv) -> str:
    """'th' or 'en' for an outbound notice — the same reader the AI's own replies use
    (chat.customer_language), so a notice never arrives in a language the assistant is
    not speaking in this thread."""
    from app.ai.chat import customer_language

    texts = [m.text for m in
             (scoped(db, models.Message, conv.clinic_id)
              .filter_by(conversation_id=conv.id)
              .filter(models.Message.sender == "customer")
              .order_by(models.Message.id).all())]
    return customer_language(texts)


def notify_hold_expired(db, booking) -> None:
    """Tell the customer the slot we were holding for them has been released.

    Called once per booking from ``booking.sweep_expired_holds``, after its commit. A
    customer who was handed a payment link and then quietly un-booked is the worst
    outcome of the whole hold mechanism, so the release is always spoken out loud — and
    it is also the best moment to offer to book them in again.

    Deliberately ``sender="ai"`` (as notify_payment_paid now is too): chat.py
    drops system messages from the history it gives the model, so a system notice would
    leave the assistant unaware it had just told this customer their slot was gone — and
    the web widget hides system messages when the thread is reloaded. This message has to
    survive both.
    """
    customer = db.get(models.Customer, booking.customer_id) if booking.customer_id else None
    if not customer:
        return
    conv = (db.get(models.Conversation, booking.conversation_id)
            if booking.conversation_id else None)
    if conv is None:
        conv = (db.query(models.Conversation).filter_by(customer_id=customer.id)
                .order_by(models.Conversation.id.desc()).first())
    if conv is None:
        return
    svc = db.get(models.Service, booking.service_id) if booking.service_id else None
    from app.services.booking import HOLD_MINUTES
    # The number THIS booking was actually held for, not whatever the clinic/service
    # setting says now — booking.hold_minutes or HOLD_MINUTES covers rows written
    # before this column existed, where it is still 0.
    held_for = booking.hold_minutes or HOLD_MINUTES

    # No year in the date and no 3+ digit figure anywhere in this text: tools.py reads
    # the clinic side's own messages for prices it has already quoted, and a stray 2026
    # would land in that set as a price the customer was given.
    if _conversation_language(db, conv) == "en":
        name = svc.name if svc else "your appointment"
        text = (f"The hold on your {name} appointment on {booking.slot_at:%d %b} at "
                f"{booking.slot_at:%H:%M} has run out — we didn't receive the payment "
                f"within {held_for} minutes, so that time has been released for other "
                f"customers. If you'd still like {name}, just tell me and I'll book you "
                "in again.")
    else:
        name = svc.name if svc else "ทรีตเมนต์"
        text = (f"คิว {name} วันที่ {booking.slot_at:%d/%m} เวลา {booking.slot_at:%H:%M} น. "
                f"หมดเวลาถือคิวแล้วค่ะ เนื่องจากยังไม่ได้รับการชำระเงินภายใน {held_for} นาที "
                "ระบบจึงปล่อยเวลานี้ให้ลูกค้าท่านอื่นแล้วนะคะ "
                f"หากยังต้องการทำ {name} พิมพ์บอกได้เลยค่ะ เดี๋ยวจองใหม่ให้ทันทีค่ะ")

    msg = models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                         sender="ai", text=text)
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    db.commit()
    realtime.publish({"type": "message", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "message": msg_dict(msg)})
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "summary": conv_summary(db, conv)})
    try:
        from app.channels.adapters import get_adapter
        get_adapter(conv.channel).send(db, conv, customer, text)
    except Exception as exc:  # pragma: no cover
        print("[inbox] hold-expiry notify send error:", exc)


def notify_hold_reminder(db, booking, *, minutes_left: int) -> None:
    """Warn the customer their hold is about to lapse — a message in the thread, so
    the warning survives even when the pay-card's live countdown is not on screen
    (the widget closed, the tab in the background). Called once per booking from
    ``booking.sweep_hold_reminders``, after its commit.

    Same sender="ai" reasoning as notify_hold_expired: a system notice would leave the
    assistant unaware it had just nudged this customer, and the web widget hides system
    messages on reload.
    """
    customer = db.get(models.Customer, booking.customer_id) if booking.customer_id else None
    if not customer:
        return
    conv = (db.get(models.Conversation, booking.conversation_id)
           if booking.conversation_id else None)
    if conv is None:
        conv = (db.query(models.Conversation).filter_by(customer_id=customer.id)
               .order_by(models.Conversation.id.desc()).first())
    if conv is None:
        return
    svc = db.get(models.Service, booking.service_id) if booking.service_id else None

    # No price, no year, no 3+ digit figure — same discipline as notify_hold_expired:
    # tools.py reads the clinic side's own messages for prices already quoted, and a
    # stray number here would land in that set as a figure the customer was given.
    if _conversation_language(db, conv) == "en":
        name = svc.name if svc else "your appointment"
        text = (f"⏰ Just a heads-up — the hold on your {name} appointment runs out in "
                f"about {minutes_left} minutes. Please complete the payment through the "
                "link soon so the slot isn't released.")
    else:
        name = svc.name if svc else "ทรีตเมนต์"
        # "จะหมดเวลา...ใน X นาที" (WILL run out, future tense) — deliberately not the
        # expiry notice's "หมดเวลาถือคิวแล้ว" (HAS run out, already happened). The two
        # must read as unmistakably different moments, not near-identical wording a
        # customer skimming on their phone could mix up.
        text = (f"⏰ แจ้งเตือนค่ะ คิว {name} จะหมดเวลาถือคิวในอีกประมาณ {minutes_left} "
                "นาทีนะคะ รบกวนรีบชำระเงินผ่านลิงก์ที่ส่งไปก่อนหน้านี้ด้วยนะคะ "
                "ก่อนที่คิวจะถูกปล่อยให้ลูกค้าท่านอื่นค่ะ")

    msg = models.Message(clinic_id=conv.clinic_id, conversation_id=conv.id,
                         sender="ai", text=text)
    db.add(msg)
    conv.last_message_at = datetime.utcnow()
    db.commit()
    realtime.publish({"type": "message", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "message": msg_dict(msg)})
    realtime.publish({"type": "conversation", "conversation_id": conv.id,
                      "clinic_id": conv.clinic_id, "summary": conv_summary(db, conv)})
    try:
        from app.channels.adapters import get_adapter
        get_adapter(conv.channel).send(db, conv, customer, text)
    except Exception as exc:  # pragma: no cover
        print("[inbox] hold-reminder notify send error:", exc)
