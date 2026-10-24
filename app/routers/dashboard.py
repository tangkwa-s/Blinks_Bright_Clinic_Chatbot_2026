"""Sales dashboard metrics."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import active_clinic_id, current_user, effective_branch
from app.routers.payments import _fully_settled_booking_ids
from app.scope import scoped
from app.services.reporting import RANGES, one_year_days

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(branch_id: str = "", period: str = "30d",
              db: Session = Depends(get_db), user: models.User = Depends(current_user),
              cid: int = Depends(active_clinic_id)):
    now_utc = datetime.utcnow()
    today_bkk_date = (now_utc + timedelta(hours=7)).date()
    days = one_year_days(today_bkk_date) if period == "1y" else RANGES.get(period, 30)
    since = now_utc - timedelta(days=days)
    bid = effective_branch(user, branch_id)

    customers = scoped(db, models.Customer, cid).filter(models.Customer.merged_into_id.is_(None)).all()
    bookings = scoped(db, models.Booking, cid).all()
    payments = scoped(db, models.Payment, cid).filter(models.Payment.status == "paid").all()
    pending_payments = scoped(db, models.Payment, cid).filter(models.Payment.status == "pending").all()
    branches = scoped(db, models.Branch, cid).order_by(models.Branch.id).all()
    services = {s.id: s.name for s in scoped(db, models.Service, cid).all()}
    # A customer's EFFECTIVE branch for attribution: their own branch, else the branch
    # where they actually BOOKED. A Booking always carries a real branch even when the
    # Customer row was created without one (web / AI leads), so attributing leads and
    # revenue by customer.branch_id alone left every per-branch view empty while the
    # booking count was right. Revenue follows the branch of the booking it paid for.
    booking_branch = {b.id: b.branch_id for b in bookings}
    book_branch_of_cust: dict[int, int] = {}
    for b in bookings:
        if b.branch_id:
            book_branch_of_cust.setdefault(b.customer_id, b.branch_id)
    cust_branch = {c.id: (c.branch_id or book_branch_of_cust.get(c.id)) for c in customers}

    def pay_branch(p) -> int | None:
        return booking_branch.get(p.booking_id) or cust_branch.get(p.customer_id)

    if bid:
        customers = [c for c in customers if cust_branch.get(c.id) == bid]
        bookings = [b for b in bookings if b.branch_id == bid]
        payments = [p for p in payments if pay_branch(p) == bid]
        pending_payments = [p for p in pending_payments if pay_branch(p) == bid]

    leads = [c for c in customers if c.created_at and c.created_at >= since]
    range_bookings = [b for b in bookings if b.created_at and b.created_at >= since]
    range_paid = [p for p in payments if p.paid_at and p.paid_at >= since]
    # A pending row has no paid_at yet — bound it by when it was CREATED instead
    # (mirrors payments.py::_filter_by_period's identical fallback), or every
    # unsettled payment ever made would leak into every period no matter how narrow.
    range_pending = [p for p in pending_payments if p.created_at and p.created_at >= since]
    revenue = sum(p.amount for p in range_paid)

    # leads by channel
    by_channel = defaultdict(int)
    for c in leads:
        by_channel[c.channel] += 1

    # Lead funnel — CUMULATIVE: how many leads reached AT LEAST each stage. pipeline_stage
    # is a single current position (a customer at 'booked' already passed new_lead/interested),
    # so we roll the current-stage counts forward. This keeps the funnel monotonically
    # decreasing and every stage's % (of the top) at or below 100% — current-state counts
    # alone left earlier stages at 0 and made later ones read as 300%.
    _ORDER = ["new_lead", "interested", "booked", "paid", "followup"]
    _at_stage = {s: 0 for s in _ORDER}
    for c in customers:
        if c.pipeline_stage in _at_stage:
            _at_stage[c.pipeline_stage] += 1
    funnel = {s: sum(_at_stage[_ORDER[j]] for j in range(i, len(_ORDER)))
              for i, s in enumerate(_ORDER)}

    # Period (cohort) outcome of this window's leads, so the top KPIs add up:
    #   Conversion = (Paid + Follow-up) / New leads — all over the SAME lead cohort,
    # date-filtered by the 7/30/90-day toggle. The Paid and Follow-ups cards expose
    # the numerator so the conversion is transparent/verifiable on the dashboard.
    paid_count = sum(1 for c in leads if c.pipeline_stage == "paid")
    # Payment-transaction count (not a lead cohort like paid_count above) — a paid
    # deposit only secures the booking, so it's tracked separately from a settled sale
    # — UNTIL that same booking's remaining balance is later paid in full, at which
    # point it belongs only in "paid", not still counted here too. Mirrors
    # payments.py::payments_summary's identical fix, via the one shared query both
    # use to agree on a booking's CURRENT state (see _fully_settled_booking_ids).
    settled_booking_ids = {bid for (bid,) in _fully_settled_booking_ids(db, cid)}
    deposit_paid_count = sum(1 for p in range_paid if p.type == "deposit"
                             and p.booking_id not in settled_booking_ids)
    followups = sum(1 for c in leads if c.pipeline_stage == "followup")
    closed = paid_count + followups
    conversion = round(closed / max(len(leads), 1) * 100, 1)
    reminders_due = scoped(db, models.Reminder, cid).filter(
        models.Reminder.status == "scheduled").count()

    # revenue trend + stat-card sparklines — up to 10 Bangkok CALENDAR buckets whose LAST one
    # ends TODAY, so today's revenue lands on today's label (not yesterday's) and the dates
    # match the +7 timezone shown everywhere. paid_at / created_at are stored UTC, so shift +7h
    # before bucketing. Anchoring to midnight (not 'now - days' with its time) keeps days aligned.
    n = min(10, max(days, 2))
    # Integer day-offsets for each bucket's START (0 == trend_start), spread as evenly as
    # possible over the FULL `days` window (first point = days-1 ago, last point = today,
    # n-1 gaps summing to exactly days-1 -> e.g. 364/9 -> 0,40,81,121,...,364 for 1y). Both
    # the x-axis labels and _bk()'s bucket lookup read this SAME array, so a transaction
    # always lands under the label it's plotted against, and no data gets silently clamped
    # into bucket 0 from outside the labelled range (dividing by `n` instead of `n - 1`
    # left the oldest ~days/n days of the window unlabelled and dumped into bucket 0).
    offsets = [round(i * (days - 1) / (n - 1)) for i in range(n)]
    today_bkk = datetime.combine(today_bkk_date, datetime.min.time())
    trend_start = today_bkk - timedelta(days=offsets[-1])
    values = [0.0] * n      # revenue
    sp_leads = [0] * n
    sp_book = [0] * n
    sp_conv = [0] * n       # paid transactions (deposit + full)
    sp_deposit = [0] * n    # paid-deposit transactions only
    sp_pending = [0] * n    # still-unpaid payment links, by when they were created
    sp_closed = [0] * n     # closed leads (paid/followup) per lead-created bucket
    sp_follow = [0] * n     # completed visits
    labels = [(trend_start + timedelta(days=o)).strftime("%d %b") for o in offsets]

    def _bk(dt):            # naive-UTC timestamp -> its Bangkok day -> bucket index
        day_off = ((dt + timedelta(hours=7)) - trend_start).days
        idx = bisect_right(offsets, day_off) - 1
        return min(max(idx, 0), n - 1)

    for p in range_paid:
        idx = _bk(p.paid_at)
        values[idx] += p.amount
        sp_conv[idx] += 1
        if p.type == "deposit":
            sp_deposit[idx] += 1
    for p in range_pending:
        sp_pending[_bk(p.created_at)] += 1
    for c in leads:
        if c.created_at:
            idx = _bk(c.created_at)
            sp_leads[idx] += 1
            if c.pipeline_stage in ("paid", "followup"):
                sp_closed[idx] += 1
    for b in range_bookings:
        if b.created_at:
            idx = _bk(b.created_at)
            sp_book[idx] += 1
            if b.status == "completed":
                sp_follow[idx] += 1

    # top treatments by booking count
    svc_count = defaultdict(int)
    for b in range_bookings:
        svc_count[b.service_id] += 1
    top_treatments = sorted(
        ({"label": services.get(sid, "—"), "value": cnt}
         for sid, cnt in svc_count.items()),
        key=lambda x: x["value"], reverse=True)[:5]

    # per-branch performance
    branch_perf = []
    for br in branches:
        if bid and br.id != bid:
            continue
        b_leads = sum(1 for c in leads if cust_branch.get(c.id) == br.id)
        b_book = sum(1 for b in range_bookings if b.branch_id == br.id)
        b_rev = sum(p.amount for p in range_paid if pay_branch(p) == br.id)
        branch_perf.append({"name": br.name, "leads": b_leads,
                            "bookings": b_book, "revenue": b_rev})

    # per-admin performance (closing)
    users = {u.id: u.name for u in scoped(db, models.User, cid).all()}
    admin_closed = defaultdict(int)
    admin_total = defaultdict(int)
    for c in customers:
        if c.assigned_user_id:
            admin_total[c.assigned_user_id] += 1
            if c.pipeline_stage in ("paid", "followup"):
                admin_closed[c.assigned_user_id] += 1
    admin_perf = sorted(
        ({"name": users.get(uid, "—"), "closed": admin_closed[uid],
          "total": admin_total[uid]} for uid in admin_total),
        key=lambda x: x["closed"], reverse=True)[:5]

    # recent conversations
    cq = scoped(db, models.Conversation, cid).order_by(
        models.Conversation.last_message_at.desc())
    recent = []
    for conv in cq.limit(40).all():
        if bid and cust_branch.get(conv.customer_id) != bid:
            continue
        cust = db.get(models.Customer, conv.customer_id)
        last = (scoped(db, models.Message, cid).filter_by(conversation_id=conv.id)
                .order_by(models.Message.id.desc()).first())
        recent.append({
            "id": conv.id, "customer": cust.name if cust else "—",
            "channel": conv.channel, "status": conv.status,
            "last_message": (last.text[:60] if last else ""),
        })
        if len(recent) >= 6:
            break

    # --- AI token usage + estimated cost (THB) for the selected period ---
    from app.ai.usage import cost_thb
    usage_rows = (scoped(db, models.TokenUsage, cid)
                  .filter(models.TokenUsage.created_at >= since).all())
    in_tok = sum(r.prompt_tokens for r in usage_rows)
    out_tok = sum(r.completion_tokens for r in usage_rows)
    ai_usage = {
        "prompt_tokens": in_tok, "completion_tokens": out_tok,
        "total_tokens": in_tok + out_tok, "calls": len(usage_rows),
        "cost_thb": cost_thb(in_tok, out_tok),
    }

    return {
        "stats": {
            "revenue": round(revenue, 2),
            "leads": len(leads),
            "bookings": len(range_bookings),
            "deposit_paid": deposit_paid_count,
            "paid": paid_count,
            "pending": len(range_pending),
            "followups": followups,
            "conversion": conversion,
            "reminders_due": reminders_due,
        },
        "ai_usage": ai_usage,
        "by_channel": dict(by_channel),
        "funnel": funnel,
        "trend": {"values": values, "labels": labels},
        "sparks": {
            "revenue": [round(v, 2) for v in values],
            "leads": sp_leads, "bookings": sp_book, "paid": sp_conv,
            "deposit_paid": sp_deposit, "pending": sp_pending,
            # per-bucket conversion of that bucket's lead cohort — the same
            # (paid+followup)/leads definition as the headline %, NOT the paid
            # transaction count (which is the Paid card's spark).
            "conversion": [round(sp_closed[i] / sp_leads[i] * 100, 1) if sp_leads[i] else 0
                           for i in range(n)],
            "followups": sp_follow,
        },
        "top_treatments": top_treatments,
        "branch_performance": branch_perf,
        "admin_performance": admin_perf,
        "recent_conversations": recent,
    }
