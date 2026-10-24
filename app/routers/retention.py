"""Retention routes — metrics now; the automation engine is added in Phase 8."""
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import active_clinic_id, current_user, require_role
from app.scope import scoped

router = APIRouter(prefix="/api/retention", tags=["retention"])

INACTIVE_DAYS = 90


@router.get("/metrics")
def retention_metrics(branch_id: str = "", db: Session = Depends(get_db),
                      _u: models.User = Depends(current_user),
                      cid: int = Depends(active_clinic_id)):
    bid = None
    if branch_id and branch_id != "all":
        try:
            bid = int(branch_id)
        except ValueError:
            bid = None

    customers = scoped(db, models.Customer, cid).filter(models.Customer.merged_into_id.is_(None)).all()
    branches = {b.id: b.name for b in scoped(db, models.Branch, cid).all()}
    services = {s.id: s.name for s in scoped(db, models.Service, cid).all()}
    bookings = scoped(db, models.Booking, cid).all()

    # A customer's EFFECTIVE branch for attribution: their own branch, else the
    # branch where they actually booked — web / AI leads are created with
    # branch_id=None, so filtering on customer.branch_id alone dropped them all
    # (the same fix as the dashboard's per-branch attribution).
    book_branch_of_cust: dict[int, int] = {}
    for b in bookings:
        if b.branch_id:
            book_branch_of_cust.setdefault(b.customer_id, b.branch_id)
    cust_branch = {c.id: (c.branch_id or book_branch_of_cust.get(c.id)) for c in customers}
    if bid:
        customers = [c for c in customers if cust_branch.get(c.id) == bid]

    completed_by_cust = defaultdict(int)
    completed_by_svc = defaultdict(int)
    for b in bookings:
        if b.status == "completed":
            completed_by_cust[b.customer_id] += 1
            completed_by_svc[b.service_id] += 1

    cust_ids = {c.id for c in customers}
    served = [cid for cid in completed_by_cust if cid in cust_ids]
    repeat = [cid for cid in served if completed_by_cust[cid] >= 2]
    repeat_rate = round(len(repeat) / max(len(served), 1) * 100, 1)

    now = datetime.utcnow()
    inactive = sum(1 for c in customers
                   if c.last_treatment_at
                   and (now - c.last_treatment_at).days > INACTIVE_DAYS)

    paying = [c for c in customers if c.ltv > 0]
    clv = round(sum(c.ltv for c in paying) / max(len(paying), 1))

    followups = sum(1 for c in customers if c.pipeline_stage == "followup")
    # follow-up conversion — of post-treatment customers, how many returned
    # for another treatment (2+ completed visits)
    followup_ids = {c.id for c in customers if c.pipeline_stage == "followup"}
    rebooked = sum(1 for cid in followup_ids if completed_by_cust.get(cid, 0) >= 2)
    followup_conversion = round(rebooked / max(len(followup_ids), 1) * 100, 1)

    # retention by branch
    by_branch = []
    for bid2, bname in branches.items():
        b_custs = [c for c in customers if cust_branch.get(c.id) == bid2]
        b_served = [c.id for c in b_custs if completed_by_cust.get(c.id, 0) >= 1]
        b_repeat = [cid for cid in b_served if completed_by_cust[cid] >= 2]
        by_branch.append({
            "label": bname,
            "value": round(len(b_repeat) / max(len(b_served), 1) * 100, 1),
            "display": f"{round(len(b_repeat) / max(len(b_served), 1) * 100)}%",
        })

    top_returning = sorted(
        ({"label": services.get(sid, "—"), "value": cnt}
         for sid, cnt in completed_by_svc.items()),
        key=lambda x: x["value"], reverse=True)[:6]

    return {
        "repeat_rate": repeat_rate,
        "inactive": inactive,
        "clv": clv,
        "active_members": scoped(db, models.Membership, cid).count(),
        "followup_pending": followups,
        "followup_conversion": followup_conversion,
        "retention_by_branch": by_branch,
        "top_returning_treatments": top_returning,
    }


@router.get("/reminders")
def list_reminders(status: str = "", db: Session = Depends(get_db),
                   _u: models.User = Depends(current_user),
                   cid: int = Depends(active_clinic_id)):
    query = scoped(db, models.Reminder, cid)
    if status:
        query = query.filter(models.Reminder.status == status)
    rows = query.order_by(models.Reminder.due_at.desc()).limit(200).all()
    out = []
    for r in rows:
        c = scoped(db, models.Customer, cid).filter(models.Customer.id == r.customer_id).first()
        out.append({
            "id": r.id, "type": r.type, "customer": c.name if c else "—",
            "channel": r.channel, "title": r.title, "body": r.body, "status": r.status,
            "due_at": r.due_at.isoformat() if r.due_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        })
    return out


@router.get("/automations")
def list_automations(db: Session = Depends(get_db),
                     _u: models.User = Depends(current_user),
                     cid: int = Depends(active_clinic_id)):
    rows = scoped(db, models.AutomationRule, cid).order_by(models.AutomationRule.id).all()
    return [{"id": r.id, "type": r.type, "name": r.name,
             "description": r.description, "enabled": r.enabled} for r in rows]


@router.patch("/automations/{aid}")
def toggle_automation(aid: int, data: dict = Body(...), db: Session = Depends(get_db),
                      _u: models.User = Depends(require_role("branch_manager", "marketing")),
                      cid: int = Depends(active_clinic_id)):
    rule = scoped(db, models.AutomationRule, cid).filter(models.AutomationRule.id == aid).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Automation not found")
    if "enabled" in data:
        rule.enabled = bool(data["enabled"])
    db.commit()
    return {"id": rule.id, "enabled": rule.enabled}


@router.post("/run")
def run_now(_u: models.User = Depends(current_user),
            cid: int = Depends(active_clinic_id)):
    """Run the retention automation engine for the active clinic."""
    from app.services.automations import run_automations

    return run_automations(clinic_id=cid)
