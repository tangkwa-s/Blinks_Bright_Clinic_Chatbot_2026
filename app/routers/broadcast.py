"""Broadcast / campaign routes — targeted re-engagement messages."""
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.deps import active_clinic_id, current_user, require_role
from app.scope import scoped

router = APIRouter(prefix="/api", tags=["broadcast"])

MARKETER = require_role("marketing", "branch_manager")

try:
    from zoneinfo import ZoneInfo
    _CLINIC_TZ = ZoneInfo(settings.timezone)
except Exception:  # pragma: no cover
    _CLINIC_TZ = timezone.utc


def _parse_schedule(value):
    """The datetime-local picker sends a NAIVE clinic-local (e.g. Asia/Bangkok) time;
    convert it to naive UTC so it compares correctly against datetime.utcnow()."""
    sa = (value or "").strip()
    if not sa:
        return None
    try:
        local = datetime.fromisoformat(sa.replace("Z", ""))
    except ValueError:
        return None
    return local.replace(tzinfo=_CLINIC_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _audience(db: Session, flt: dict, cid: int) -> list[models.Customer]:
    """Resolve the customers matching an audience filter."""
    customers = scoped(db, models.Customer, cid).filter(models.Customer.merged_into_id.is_(None)).all()
    stage = flt.get("stage")
    temperature = flt.get("temperature")
    inactive = flt.get("inactive_days")
    channel = flt.get("channel")
    # A branch-restricted campaign only reaches customers CONFIRMED to be at one
    # of those branches — unlike a treatment's "no branch_id = every branch",
    # a customer with no branch_id is of unknown branch and stays excluded.
    branch_ids = {int(b) for b in (flt.get("branch_ids") or [])}
    now = datetime.utcnow()
    out = []
    for c in customers:
        if stage and c.pipeline_stage != stage:
            continue
        if temperature and c.temperature != temperature:
            continue
        if channel and channel != "all" and (c.channel or "web") != channel:
            continue
        if branch_ids and c.branch_id not in branch_ids:
            continue
        if inactive:
            if not c.last_treatment_at or (now - c.last_treatment_at).days < int(inactive):
                continue
        out.append(c)
    return out


def _reachable(c: models.Customer) -> bool:
    """Whether a broadcast can actually reach this customer: web chat always can."""
    return True


def audience_row(c: models.Customer) -> dict:
    return {
        "id": c.id, "name": c.name, "channel": c.channel or "web",
        "avatar": c.avatar or "", "channel_user_id": c.channel_user_id or "",
        "pipeline_stage": c.pipeline_stage, "temperature": c.temperature,
        "reachable": _reachable(c),
        "last_activity_at": c.last_activity_at.isoformat() if c.last_activity_at else None,
    }


def campaign_dict(c: models.Campaign, responded: int = 0) -> dict:
    return {
        "id": c.id, "name": c.name, "audience": c.audience or {},
        "channel": c.channel, "message": c.message, "status": c.status,
        "audience_count": c.audience_count, "sent_count": c.sent_count,
        "opened_count": c.opened_count,  # simulated (42% of sent) — kept for compat, not shown in the UI
        "responded_count": responded,
        "response_rate": round(100 * responded / c.sent_count) if c.sent_count else 0,
        "scheduled_at": (c.scheduled_at.isoformat() + "Z") if c.scheduled_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _responded_by_campaign(db: Session, cid: int) -> dict[int, int]:
    """{campaign_id: distinct customers who replied} — one grouped query, no N+1."""
    rows = (scoped(db, models.Activity, cid)
            .filter(models.Activity.type == "campaign_reply",
                    models.Activity.ref_type == "campaign")
            .with_entities(models.Activity.ref_id,
                           func.count(func.distinct(models.Activity.customer_id)))
            .group_by(models.Activity.ref_id).all())
    return {ref_id: n for ref_id, n in rows if ref_id is not None}


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db),
                   _u: models.User = Depends(current_user),
                   cid: int = Depends(active_clinic_id)):
    rows = scoped(db, models.Campaign, cid).order_by(models.Campaign.id.desc()).all()
    responded = _responded_by_campaign(db, cid)
    return [campaign_dict(c, responded.get(c.id, 0)) for c in rows]


@router.get("/campaigns/preview")
def preview_audience(stage: str = "", temperature: str = "", inactive_days: str = "",
                     channel: str = "", branch_ids: list[int] = Query(default=[]),
                     db: Session = Depends(get_db),
                     _u: models.User = Depends(current_user),
                     cid: int = Depends(active_clinic_id)):
    flt = {}
    if stage:
        flt["stage"] = stage
    if temperature:
        flt["temperature"] = temperature
    if inactive_days:
        flt["inactive_days"] = inactive_days
    if channel:
        flt["channel"] = channel
    if branch_ids:
        flt["branch_ids"] = branch_ids
    audience = _audience(db, flt, cid)
    return {"count": len(audience),
            "reachable": sum(1 for c in audience if _reachable(c)),
            "customers": [audience_row(c) for c in audience[:200]]}


@router.get("/campaigns/{campaign_id}/audience")
def campaign_audience(campaign_id: int, db: Session = Depends(get_db),
                      _u: models.User = Depends(current_user),
                      cid: int = Depends(active_clinic_id)):
    """The customers a campaign targets (resolved live from its saved filter)."""
    campaign = (scoped(db, models.Campaign, cid)
                .filter(models.Campaign.id == campaign_id).first())
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audience = _audience(db, campaign.audience or {}, cid)
    return {"count": len(audience),
            "reachable": sum(1 for c in audience if _reachable(c)),
            "customers": [audience_row(c) for c in audience]}


@router.post("/campaigns")
def create_campaign(data: dict = Body(...), db: Session = Depends(get_db),
                    _u: models.User = Depends(MARKETER),
                    cid: int = Depends(active_clinic_id)):
    flt = dict(data.get("audience") or {})
    channel = data.get("channel", flt.get("channel", "all"))
    flt["channel"] = channel  # keep delivery + audience consistent
    audience = _audience(db, flt, cid)
    # optional scheduling — a future time parks the campaign as "scheduled" and the
    # retention scheduler sends it when due; otherwise it stays a manual "draft".
    # The picker time is clinic-local, stored as UTC so the due-check is correct.
    scheduled_at = _parse_schedule(data.get("scheduled_at"))
    status = "scheduled" if (scheduled_at and scheduled_at > datetime.utcnow()) else "draft"
    # a scheduled campaign sends unattended — an empty message would fail for
    # every recipient invisibly, so refuse it here (manual send has its own guard)
    if status == "scheduled" and not (data.get("message") or "").strip():
        raise HTTPException(status_code=400, detail="Add a message before scheduling")
    campaign = models.Campaign(
        name=data.get("name", "Untitled campaign"),
        audience=flt, channel=channel,
        message=data.get("message", ""), status=status,
        audience_count=len(audience), scheduled_at=scheduled_at,
        clinic_id=cid,
    )
    db.add(campaign)
    db.commit()
    return campaign_dict(campaign)


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                    _u: models.User = Depends(MARKETER),
                    cid: int = Depends(active_clinic_id)):
    """Edit a draft/scheduled campaign in place. A sent campaign is the actual
    delivery record — edit it via "reuse" (a new campaign) instead."""
    campaign = (scoped(db, models.Campaign, cid)
                .filter(models.Campaign.id == campaign_id).first())
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "sent":
        raise HTTPException(status_code=400, detail="A sent campaign can't be edited — reuse it instead")
    flt = dict(data.get("audience") or {})
    channel = data.get("channel", flt.get("channel", "all"))
    flt["channel"] = channel
    audience = _audience(db, flt, cid)
    scheduled_at = _parse_schedule(data.get("scheduled_at"))
    status = "scheduled" if (scheduled_at and scheduled_at > datetime.utcnow()) else "draft"
    if status == "scheduled" and not (data.get("message") or "").strip():
        raise HTTPException(status_code=400, detail="Add a message before scheduling")
    campaign.name = data.get("name", campaign.name)
    campaign.audience = flt
    campaign.channel = channel
    campaign.message = data.get("message", campaign.message)
    campaign.status = status
    campaign.audience_count = len(audience)
    campaign.scheduled_at = scheduled_at
    db.commit()
    return campaign_dict(campaign)


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db),
                    _u: models.User = Depends(MARKETER),
                    cid: int = Depends(active_clinic_id)):
    """Remove a draft/scheduled campaign. A sent one is a delivery record, not
    a draft, so it's kept — same reasoning as the edit guard above."""
    campaign = (scoped(db, models.Campaign, cid)
                .filter(models.Campaign.id == campaign_id).first())
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "sent":
        raise HTTPException(status_code=400, detail="A sent campaign can't be deleted — it's the delivery record")
    (scoped(db, models.Activity, cid)
     .filter(models.Activity.ref_type == "campaign", models.Activity.ref_id == campaign_id)
     .delete(synchronize_session=False))
    db.delete(campaign)
    db.commit()
    return {"ok": True}


def deliver_campaign(db: Session, campaign: models.Campaign, cid: int) -> dict:
    """Send a campaign to its audience now. Records a per-recipient delivery log in
    the Activity trail (ref_type='campaign') and truthful sent/failed counts —
    'delivered' only when the channel adapter confirms it actually went out."""
    from app.services.inbox import broadcast_to_customer

    audience = _audience(db, campaign.audience or {}, cid)
    sent = failed = 0
    by_channel: dict[str, int] = {}
    for cust in audience[:1000]:
        ch = cust.channel or "web"
        ok = broadcast_to_customer(db, cust, campaign.message,
                                   sender_name=campaign.name or "Automation")
        if ok:
            sent += 1
            by_channel[ch] = by_channel.get(ch, 0) + 1
            status = "delivered"
        else:
            failed += 1
            status = "unreachable" if not _reachable(cust) else "failed"
        # summary format is parsed by campaign_log and matched by
        # inbox._track_campaign_reply ("· delivered") — change all three together
        db.add(models.Activity(
            clinic_id=cid, customer_id=cust.id, type="campaign",
            summary=f"{cust.name} · {ch} · {status}",
            ref_type="campaign", ref_id=campaign.id))
    campaign.status = "sent"
    campaign.audience_count = len(audience)
    campaign.sent_count = sent
    campaign.opened_count = int(sent * 0.42)  # simulated open rate
    campaign.scheduled_at = datetime.utcnow()
    db.commit()
    return {"sent": sent, "failed": failed, "audience": len(audience), "by_channel": by_channel}


@router.post("/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: int, db: Session = Depends(get_db),
                  _u: models.User = Depends(MARKETER),
                  cid: int = Depends(active_clinic_id)):
    campaign = (scoped(db, models.Campaign, cid)
                .filter(models.Campaign.id == campaign_id).first())
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not (campaign.message or "").strip():
        raise HTTPException(status_code=400, detail="Add a message before sending")
    out = campaign_dict(campaign)
    out["delivered"] = deliver_campaign(db, campaign, cid)
    out["status"] = campaign.status
    out["sent_count"] = campaign.sent_count
    return out


@router.get("/campaigns/{campaign_id}/log")
def campaign_log(campaign_id: int, db: Session = Depends(get_db),
                 _u: models.User = Depends(current_user),
                 cid: int = Depends(active_clinic_id)):
    """Per-recipient delivery log for a campaign (recipient · channel · status),
    with real response tracking (did the recipient message back within the window)."""
    campaign = (scoped(db, models.Campaign, cid)
                .filter(models.Campaign.id == campaign_id).first())
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    # type filter keeps campaign_reply rows (same ref_type+ref_id) out of the parse
    rows = (scoped(db, models.Activity, cid)
            .filter(models.Activity.type == "campaign",
                    models.Activity.ref_type == "campaign",
                    models.Activity.ref_id == campaign_id)
            .order_by(models.Activity.id.desc()).limit(500).all())
    replied_ids = {a.customer_id for a in
                   scoped(db, models.Activity, cid)
                   .filter(models.Activity.type == "campaign_reply",
                           models.Activity.ref_type == "campaign",
                           models.Activity.ref_id == campaign_id).all()}
    log = []
    for a in rows:
        parts = (a.summary or "").split(" · ")
        log.append({
            "name": parts[0] if parts else "",
            "channel": parts[1] if len(parts) > 1 else "web",
            "status": parts[2] if len(parts) > 2 else "",
            "responded": a.customer_id in replied_ids,
            "at": a.created_at.isoformat() if a.created_at else None,
        })
    return {"count": len(log), "sent": campaign.sent_count,
            "audience": campaign.audience_count,
            "responded": len(replied_ids), "log": log}
