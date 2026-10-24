"""Conversation memory — the four layers the AI assistant draws on.

- short-term       : recent messages (passed as chat history by the orchestrator)
- persistent CRM   : who the customer is and what they want
- workflow / state : sales stage, bookings, payments
- semantic         : the clinic knowledge base (RAG) + the customer's own history

All lookups are scoped to the customer's clinic.
"""
from app import models
from app.scope import scoped


def customer_memory(db, customer) -> str:
    """Persistent CRM + workflow + history memory for one customer."""
    if not customer:
        return "New visitor — nothing is known about them yet."
    cid = customer.clinic_id

    name_line = f"Name: {customer.name}"
    if getattr(customer, "nickname", ""):
        name_line += f" (nickname: {customer.nickname} — address them by this)"
    lines = [
        name_line,
        f"Pipeline stage: {customer.pipeline_stage.replace('_', ' ')} · "
        f"lead temperature: {customer.temperature} · score {customer.lead_score}/100",
    ]
    contact = []
    if customer.phone:
        contact.append(f"phone {customer.phone}")
    if customer.email:
        contact.append(f"email {customer.email}")
    if contact:
        lines.append("Contact already on file: " + ", ".join(contact)
                     + " — do NOT ask the customer for these again.")
    if customer.interested:
        lines.append(f"Interested in: {customer.interested}")
    if customer.budget:
        lines.append(f"Budget range: {customer.budget}")
    if customer.concern:
        lines.append(f"Stated concern: {customer.concern}")

    bookings = (scoped(db, models.Booking, cid).filter_by(customer_id=customer.id)
                .order_by(models.Booking.slot_at.desc()).all())
    done = [b for b in bookings if b.status == "completed"]
    upcoming = [b for b in bookings if b.status in ("pending", "confirmed")]
    if done:
        names = []
        for b in done[:5]:
            svc = db.get(models.Service, b.service_id)
            if svc:
                names.append(svc.name)
        if names:
            lines.append(f"Past treatments: {', '.join(names)}")
    if upcoming:
        # What the customer has booked + how much of it is already paid, so the AI never
        # re-asks for a payment already made and can quote the exact remaining balance if
        # the customer wants to pay the rest later (sums ALL paid payments for the booking —
        # a deposit followed by a separate remaining-balance top-up is two paid rows).
        for b in upcoming[:3]:
            svc = db.get(models.Service, b.service_id)
            when = b.slot_at.strftime("%d %b at %H:%M")
            paid_total = sum(
                p.amount for p in scoped(db, models.Payment, cid)
                .filter(models.Payment.booking_id == b.id,
                        models.Payment.status == "paid").all())
            line = f"Booked: {svc.name if svc else 'a treatment'} on {when} ({b.status})"
            if paid_total and paid_total >= b.price:
                line += (f", ฿{int(paid_total):,} for THIS booking is ALREADY PAID IN FULL and "
                         "CONFIRMED — do not ask for or offer the payment QR for this booking again")
            elif paid_total:
                remaining = b.price - paid_total
                line += (f", ฿{int(paid_total):,} of this booking's ฿{int(b.price):,} total is "
                         f"ALREADY PAID — do not ask for that again, but the remaining balance of "
                         f"฿{int(remaining):,} is NOT yet paid; if the customer wants to pay the "
                         "rest, quote this exact remaining balance (never recalculate it yourself)")
            elif b.deposit_required:
                line += (f", deposit ฿{int(b.deposit_required):,} is NOT yet paid — this booking "
                         "needs its deposit to be confirmed")
            lines.append(line)

    membership = scoped(db, models.Membership, cid).filter_by(customer_id=customer.id).first()
    if membership:
        lines.append(f"Membership: {membership.tier} tier, {membership.points} points")
    for pkg in scoped(db, models.Package, cid).filter_by(customer_id=customer.id).all():
        remaining = pkg.total_sessions - pkg.used_sessions
        if remaining > 0:
            lines.append(f"Active package: {pkg.name} — {remaining} session(s) remaining")

    return "\n".join(lines)


def workflow_state(conversation, db=None) -> str:
    """Where THIS conversation stands — the state that must survive history trimming.

    The running ``ai_summary`` is rewritten after every reply by ``sales.analyze``
    and is the one carrier of what was agreed early on (treatment, branch, date)
    once those turns fall out of the message window. Without it the assistant
    re-asked things the customer had already answered.
    """
    lines = [f"This conversation's sales stage is '{conversation.sales_stage}' "
             f"on the {conversation.channel} channel."]
    if db is not None and conversation.branch_id:
        branch = db.get(models.Branch, conversation.branch_id)
        if branch:
            lines.append(f"Branch already chosen for this chat: {branch.name} — do not "
                         "ask which branch again unless the customer switches.")
    if (conversation.ai_summary or "").strip():
        lines.append("Where the conversation stands (running summary, may cover turns "
                     f"older than the messages you can see): {conversation.ai_summary.strip()}")
    return "\n".join(lines)


def past_conversations(db, customer, current_conv_id=None) -> str:
    """Semantic / episodic memory — what was discussed in earlier conversations."""
    if not customer:
        return ""
    cid = customer.clinic_id
    query = scoped(db, models.Conversation, cid).filter_by(customer_id=customer.id)
    if current_conv_id:
        query = query.filter(models.Conversation.id != current_conv_id)
    convs = query.order_by(models.Conversation.id.desc()).limit(3).all()
    lines = []
    for c in convs:
        if c.ai_summary:
            lines.append(f"- {c.ai_summary}")
        else:
            last = (scoped(db, models.Message, cid)
                    .filter_by(conversation_id=c.id, sender="customer")
                    .order_by(models.Message.id.desc()).first())
            if last:
                lines.append(f'- Previously asked: "{last.text[:120]}"')
    if not lines:
        return ""
    return "Earlier conversations with this customer:\n" + "\n".join(lines)
