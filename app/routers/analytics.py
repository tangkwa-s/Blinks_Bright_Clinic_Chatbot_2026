"""AI analytics — conversation insights and continuous-learning signals."""
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import active_clinic_id, current_user, effective_branch
from app.scope import scoped
from app.services.chat_insights import chat_insights
from app.services.reporting import period_since

router = APIRouter(prefix="/api", tags=["analytics"])

INTENT_LABEL = {
    "pricing": "Pricing questions", "booking": "Booking requests",
    "promotion": "Promotion enquiries", "service_info": "Service information",
    "prep_aftercare": "Prep & aftercare", "complaint": "Complaints",
    "greeting": "Greetings", "other": "Other", "unknown": "Unclassified",
}


@router.get("/analytics")
def analytics(db: Session = Depends(get_db), _u: models.User = Depends(current_user),
              cid: int = Depends(active_clinic_id)):
    messages = scoped(db, models.Message, cid).all()
    ai_msgs = [m for m in messages if m.sender == "ai"]
    grounded = sum(1 for m in ai_msgs if (m.meta or {}).get("grounded", True))
    customer_msgs = sum(1 for m in messages if m.sender == "customer")

    convs = scoped(db, models.Conversation, cid).all()
    escalations = sum(1 for c in convs if c.escalation_reason)
    takeovers = sum(1 for c in convs if not c.ai_enabled)

    intent_logs = scoped(db, models.IntentLog, cid).all()
    objection_logs = [il for il in intent_logs if il.predicted_intent == "objection"]
    classified = [il for il in intent_logs if il.predicted_intent != "objection"]
    intent_count = defaultdict(int)
    for il in classified:
        intent_count[il.predicted_intent] += 1
    intents = sorted(
        ({"label": INTENT_LABEL.get(k, k), "value": v} for k, v in intent_count.items()),
        key=lambda x: x["value"], reverse=True)

    unknown = [{"question": il.question, "intent": il.predicted_intent,
                "confidence": round(il.confidence, 2)}
               for il in sorted(classified, key=lambda x: x.id, reverse=True)
               if il.confidence < 0.5][:20]

    objections = [il.question for il in
                  sorted(objection_logs, key=lambda x: x.id, reverse=True)][:15]

    # drop-off funnel — CUMULATIVE: how many leads reached AT LEAST each stage (same
    # fix as app/routers/dashboard.py's lead funnel). pipeline_stage is a single
    # current position, so raw current-stage occupancy counts are NOT nested
    # subsets of each other — dividing a later stage's count by an earlier one's
    # is comparing two unrelated populations and can read well over 100%.
    funnel_stages = ["new_lead", "interested", "booked", "paid"]
    _at_stage = {s: 0 for s in funnel_stages}
    for c in scoped(db, models.Customer, cid).filter(models.Customer.merged_into_id.is_(None)).all():
        stage = "paid" if c.pipeline_stage in ("paid", "followup") else c.pipeline_stage
        if stage in _at_stage:
            _at_stage[stage] += 1
    funnel = {s: sum(_at_stage[funnel_stages[j]] for j in range(i, len(funnel_stages)))
              for i, s in enumerate(funnel_stages)}
    drop_off = []
    for i in range(len(funnel_stages) - 1):
        a, b = funnel_stages[i], funnel_stages[i + 1]
        rate = round((funnel[b] / funnel[a] * 100) if funnel[a] else 0, 1)
        drop_off.append({"from": a, "to": b, "kept_pct": rate})

    # top-converting treatments (completed bookings)
    svc_names = {s.id: s.name for s in scoped(db, models.Service, cid).all()}
    completed = defaultdict(int)
    for b in scoped(db, models.Booking, cid).all():
        if b.status in ("completed", "confirmed"):
            completed[b.service_id] += 1
    top_converting = sorted(
        ({"label": svc_names.get(sid, "—"), "value": cnt} for sid, cnt in completed.items()),
        key=lambda x: x["value"], reverse=True)[:6]

    # LLM token usage + estimated cost (all-time for this clinic)
    from app.ai.usage import cost_thb
    usage_rows = scoped(db, models.TokenUsage, cid).all()
    in_tok = sum(r.prompt_tokens for r in usage_rows)
    out_tok = sum(r.completion_tokens for r in usage_rows)

    return {
        "ai_stats": {
            "ai_messages": len(ai_msgs),
            "customer_messages": customer_msgs,
            "grounded_pct": round(grounded / max(len(ai_msgs), 1) * 100, 1),
            "escalations": escalations,
            "takeovers": takeovers,
        },
        "ai_usage": {
            "prompt_tokens": in_tok, "completion_tokens": out_tok,
            "total_tokens": in_tok + out_tok, "calls": len(usage_rows),
            "cost_thb": cost_thb(in_tok, out_tok),
        },
        "intents": intents,
        "unknown_intents": unknown,
        "objections": objections,
        "drop_off": drop_off,
        "funnel": funnel,
        "top_converting": top_converting,
    }


@router.get("/chat-analysis")
def chat_analysis(period: str = "30d", branch_id: str = "",
                  db: Session = Depends(get_db),
                  user: models.User = Depends(current_user),
                  cid: int = Depends(active_clinic_id)):
    """The Chat Analysis dashboard — what customers write, aggregated.

    Same period tokens as the Dashboard/Payments pages (reporting.period_since) and the
    same branch resolution (effective_branch), so "30d, สาขา X" means one thing across
    every page. Daily trend for the short periods; monthly once a span would give 100+
    bars (1y / all).
    """
    since = period_since(period, datetime.utcnow())
    bid = effective_branch(user, branch_id)
    trend_by = "day" if period in ("7d", "30d", "90d") else "month"
    data = chat_insights(db, cid, since, branch_id=bid, trend_by=trend_by)
    data["period"] = period
    return data
