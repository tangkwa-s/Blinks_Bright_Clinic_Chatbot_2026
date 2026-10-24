"""Customer / CRM routes — list, pipeline, profiles, timeline, notes."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, realtime
from app.database import get_db
from app.deps import active_clinic_id, current_user, effective_branch, require_role
from app.scope import customer_branch_map, scoped
# Shared with the new-account identity check in ai/sales.py, so "same phone" means
# the same thing to the duplicate finder and to that warning.
from app.services.inbox import phone_key as _phone_key

router = APIRouter(prefix="/api", tags=["customers"])

PIPELINE = ["new_lead", "interested", "booked", "paid", "followup"]


def _in_branch(db: Session, cid: int, bid: int):
    """A filter on the customer's EFFECTIVE branch (own, else booked, else chatted)
    — the same attribution the dashboard and retention views use."""
    ids = [c_id for c_id, b_id in customer_branch_map(db, cid).items() if b_id == bid]
    return models.Customer.id.in_(ids)


def customer_row(c: models.Customer) -> dict:
    return {
        "id": c.id, "name": c.name, "nickname": c.nickname or "",
        "phone": c.phone, "email": c.email,
        "channel": c.channel, "pipeline_stage": c.pipeline_stage,
        "temperature": c.temperature, "lead_score": c.lead_score,
        "branch_id": c.branch_id, "ltv": c.ltv,
        "interested": c.interested, "budget": c.budget, "concern": c.concern,
        "avatar": c.avatar or "", "channel_user_id": c.channel_user_id or "",
        "last_activity_at": c.last_activity_at.isoformat() if c.last_activity_at else None,
    }


@router.get("/customers")
def list_customers(q: str = "", stage: str = "", temperature: str = "",
                   branch_id: str = "", limit: int = 250,
                   db: Session = Depends(get_db), user: models.User = Depends(current_user),
                   cid: int = Depends(active_clinic_id)):
    query = scoped(db, models.Customer, cid).filter(models.Customer.merged_into_id.is_(None))
    if stage:
        query = query.filter(models.Customer.pipeline_stage == stage)
    if temperature:
        query = query.filter(models.Customer.temperature == temperature)
    bid = effective_branch(user, branch_id)
    if bid:
        query = query.filter(_in_branch(db, cid, bid))
    rows = query.order_by(models.Customer.last_activity_at.desc()).limit(limit).all()
    if q:
        ql = q.lower()
        rows = [c for c in rows if ql in c.name.lower() or ql in (c.phone or "")]
    return [customer_row(c) for c in rows]


@router.get("/customers/pipeline")
def pipeline_counts(branch_id: str = "", db: Session = Depends(get_db),
                    user: models.User = Depends(current_user),
                    cid: int = Depends(active_clinic_id)):
    query = scoped(db, models.Customer, cid).filter(models.Customer.merged_into_id.is_(None))
    bid = effective_branch(user, branch_id)
    if bid:
        query = query.filter(_in_branch(db, cid, bid))
    counts = {s: 0 for s in PIPELINE + ["lost"]}
    for c in query.all():
        counts[c.pipeline_stage] = counts.get(c.pipeline_stage, 0) + 1
    return counts


# --------------------------- golden records (dedup) ---------------------------


def _email_key(email: str) -> str:
    e = (email or "").strip().lower()
    return e if "@" in e else ""


_STAGE_RANK = {"lost": 0, "new_lead": 1, "interested": 2, "booked": 3, "paid": 4, "followup": 5}
_TEMP_RANK = {"cold": 0, "warm": 1, "hot": 2}
_PLACEHOLDER_NAMES = {"", "line user", "web visitor", "messenger user", "facebook user"}


def _dup_member(db, c, cid) -> dict:
    d = customer_row(c)
    d.update({
        "bookings": scoped(db, models.Booking, cid).filter_by(customer_id=c.id).count(),
        "conversations": scoped(db, models.Conversation, cid).filter_by(customer_id=c.id).count(),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    })
    return d


@router.get("/customers/duplicates")
def find_duplicates(db: Session = Depends(get_db), _u: models.User = Depends(current_user),
                    cid: int = Depends(active_clinic_id)):
    """Groups of active customers that share a phone number or email — likely the
    same person reaching the clinic from more than one channel. Each group is a
    golden-record merge suggestion."""
    rows = (scoped(db, models.Customer, cid)
            .filter(models.Customer.merged_into_id.is_(None)).all())
    parent = {c.id: c.id for c in rows}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Group by phone number — the identity signal the clinic uses. (Email is
    # intentionally NOT used: the demo seed generates colliding placeholder emails,
    # and a shared phone is the stronger "same person" signal here.)
    first_phone = {}
    for c in rows:
        pk = _phone_key(c.phone)
        if pk:
            union(c.id, first_phone.setdefault(pk, c.id))

    comps = {}
    for c in rows:
        comps.setdefault(find(c.id), []).append(c)

    groups = []
    for members in comps.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda x: (x.created_at or datetime.min))
        groups.append({
            "match": ["phone"],
            "shared_phone": next((m.phone for m in ordered if m.phone), ""),
            "customers": [_dup_member(db, m, cid) for m in ordered],
        })
    groups.sort(key=lambda g: len(g["customers"]), reverse=True)
    return {"groups": groups, "count": len(groups)}


_MERGE_MODELS = (models.Conversation, models.Booking, models.Payment, models.Activity,
                 models.Note, models.Membership, models.Package, models.Reminder)


def _consolidate(primary, dups):
    """Fold the duplicates' best data onto the surviving golden record."""
    recs = [primary] + dups
    if (primary.name or "").strip().lower() in _PLACEHOLDER_NAMES:
        for d in dups:
            if (d.name or "").strip().lower() not in _PLACEHOLDER_NAMES:
                primary.name = d.name
                break
    for field in ("nickname", "phone", "email", "avatar", "budget", "concern",
                  "interested", "channel_user_id"):
        if not getattr(primary, field):
            for d in dups:
                if getattr(d, field):
                    setattr(primary, field, getattr(d, field))
                    break
    for field in ("birthday", "assigned_user_id", "branch_id", "last_treatment_at"):
        if getattr(primary, field) is None:
            for d in dups:
                if getattr(d, field) is not None:
                    setattr(primary, field, getattr(d, field))
                    break
    primary.ltv = round(sum((r.ltv or 0) for r in recs), 2)
    primary.lead_score = max((r.lead_score or 0) for r in recs)
    primary.pipeline_stage = max((r.pipeline_stage for r in recs),
                                 key=lambda s: _STAGE_RANK.get(s, 0))
    primary.temperature = max((r.temperature for r in recs),
                              key=lambda t: _TEMP_RANK.get(t, 0))
    created = [r.created_at for r in recs if r.created_at]
    if created:
        primary.created_at = min(created)
    acts = [r.last_activity_at for r in recs if r.last_activity_at]
    if acts:
        primary.last_activity_at = max(acts)
    treats = [r.last_treatment_at for r in recs if r.last_treatment_at]
    if treats:
        primary.last_treatment_at = max(treats)
    tags = []
    for r in recs:
        for t in (r.tags or []):
            if t not in tags:
                tags.append(t)
    primary.tags = tags


@router.post("/customers/merge")
def merge_customers(data: dict = Body(...), db: Session = Depends(get_db),
                    _u: models.User = Depends(require_role("branch_manager")),
                    cid: int = Depends(active_clinic_id)):
    """Merge duplicate customers into one golden record: move every linked record
    (conversations, bookings, payments, activities, notes, memberships, packages,
    reminders) onto the chosen primary, fold in the best profile data, then redirect
    the duplicates' channel identities to the golden record (they keep arriving on it)."""
    primary_id = data.get("primary_id")
    dup_ids = [i for i in (data.get("duplicate_ids") or []) if i and i != primary_id]
    if not primary_id or not dup_ids:
        raise HTTPException(status_code=400,
                            detail="Pick a record to keep and at least one to merge")
    primary = (scoped(db, models.Customer, cid)
               .filter(models.Customer.id == primary_id,
                       models.Customer.merged_into_id.is_(None)).first())
    if not primary:
        raise HTTPException(status_code=404, detail="The record to keep was not found")
    dups = (scoped(db, models.Customer, cid)
            .filter(models.Customer.id.in_(dup_ids),
                    models.Customer.merged_into_id.is_(None)).all())
    if not dups:
        raise HTTPException(status_code=404, detail="No duplicate records found to merge")
    real_dup_ids = [d.id for d in dups]
    for model in _MERGE_MODELS:
        (scoped(db, model, cid).filter(model.customer_id.in_(real_dup_ids))
         .update({model.customer_id: primary_id}, synchronize_session=False))
    _consolidate(primary, dups)
    for d in dups:
        d.merged_into_id = primary_id
    # A duplicate being merged may itself be the golden record of an EARLIER merge, with
    # stubs still pointing at it. Re-point those at the new primary so no chain forms
    # (_resolve_golden walks chains, but every other reader only tests IS NULL, and a
    # later purge of the middle row would strand the outer stubs), e.g. a
    # chain A -> B -> C.
    (scoped(db, models.Customer, cid)
     .filter(models.Customer.merged_into_id.in_(real_dup_ids))
     .update({models.Customer.merged_into_id: primary_id}, synchronize_session=False))
    db.add(models.Activity(clinic_id=cid, customer_id=primary_id, type="merge",
                           summary=f"Merged {len(dups)} duplicate record(s) into this golden record"))
    db.commit()
    realtime.publish({"type": "customer", "customer_id": primary_id, "clinic_id": cid})
    for did in real_dup_ids:
        realtime.publish({"type": "customer_deleted", "customer_id": did, "clinic_id": cid})
    return {"ok": True, "primary_id": primary_id, "merged": real_dup_ids,
            "customer": customer_row(primary)}


@router.get("/customers/{cid}")
def get_customer(cid: int, db: Session = Depends(get_db),
                 _u: models.User = Depends(current_user),
                 clinic_id: int = Depends(active_clinic_id)):
    c = (scoped(db, models.Customer, clinic_id)
         .filter(models.Customer.id == cid).first())
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    branch = (scoped(db, models.Branch, clinic_id)
              .filter(models.Branch.id == c.branch_id).first()
              if c.branch_id else None)
    agent = (scoped(db, models.User, clinic_id)
             .filter(models.User.id == c.assigned_user_id).first()
             if c.assigned_user_id else None)
    membership = scoped(db, models.Membership, clinic_id).filter_by(customer_id=cid).first()
    packages = scoped(db, models.Package, clinic_id).filter_by(customer_id=cid).all()
    bookings = (scoped(db, models.Booking, clinic_id).filter_by(customer_id=cid)
                .order_by(models.Booking.slot_at.desc()).all())
    payments = (scoped(db, models.Payment, clinic_id).filter_by(customer_id=cid)
                .order_by(models.Payment.id.desc()).all())
    conv = (scoped(db, models.Conversation, clinic_id).filter_by(customer_id=cid)
            .order_by(models.Conversation.id.desc()).first())

    def svc_name(sid):
        s = (scoped(db, models.Service, clinic_id)
             .filter(models.Service.id == sid).first())
        return s.name if s else "—"

    return {
        "customer": customer_row(c),
        "branch_name": branch.name if branch else None,
        "assigned_user_name": agent.name if agent else None,
        "membership": ({"tier": membership.tier, "points": membership.points,
                        "joined_at": membership.joined_at.isoformat()}
                       if membership else None),
        "packages": [{"id": p.id, "name": p.name,
                      "total": p.total_sessions, "used": p.used_sessions,
                      "remaining": p.total_sessions - p.used_sessions,
                      "expires_at": p.expires_at.isoformat() if p.expires_at else None}
                     for p in packages],
        "bookings": [{"id": b.id, "service": svc_name(b.service_id),
                      "slot_at": b.slot_at.isoformat(), "status": b.status}
                     for b in bookings],
        "payments": [{"id": p.id, "type": p.type, "amount": p.amount,
                      "status": p.status,
                      "paid_at": p.paid_at.isoformat() if p.paid_at else None}
                     for p in payments],
        "conversation_id": conv.id if conv else None,
        "stats": {
            "bookings": len(bookings),
            "payments_paid": sum(1 for p in payments if p.status == "paid"),
            "ltv": c.ltv,
        },
    }


@router.patch("/customers/{cid}")
def update_customer(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
                    _u: models.User = Depends(current_user),
                    clinic_id: int = Depends(active_clinic_id)):
    c = (scoped(db, models.Customer, clinic_id)
         .filter(models.Customer.id == cid).first())
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    if "pipeline_stage" in data and data["pipeline_stage"] in PIPELINE + ["lost"]:
        if c.pipeline_stage != data["pipeline_stage"]:
            db.add(models.Activity(customer_id=cid, type="status",
                summary=f"Moved to {data['pipeline_stage'].replace('_', ' ')}",
                clinic_id=clinic_id))
        c.pipeline_stage = data["pipeline_stage"]
    for field in ("name", "nickname", "phone", "email", "budget", "concern", "interested"):
        if field in data:
            setattr(c, field, data[field])
    db.commit()
    realtime.publish({"type": "customer", "customer_id": cid, "clinic_id": clinic_id})
    return customer_row(c)


@router.delete("/customers/{cid}")
def delete_customer(cid: int, db: Session = Depends(get_db),
                    _u: models.User = Depends(require_role("branch_manager")),
                    clinic_id: int = Depends(active_clinic_id)):
    """Delete a customer and everything linked to them — conversations, messages,
    bookings, payments, reminders, notes, activities, memberships, packages,
    intent logs. Lets you re-test the same person from scratch.

    Scoped to the active clinic so it can never reach another tenant's data.
    """
    c = (scoped(db, models.Customer, clinic_id)
         .filter(models.Customer.id == cid).first())
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")

    conv_ids = [x.id for x in scoped(db, models.Conversation, clinic_id)
                .filter_by(customer_id=cid).all()]
    booking_ids = [x.id for x in scoped(db, models.Booking, clinic_id)
                   .filter_by(customer_id=cid).all()]

    def wipe(model, *conds) -> int:
        q = scoped(db, model, clinic_id)
        for cond in conds:
            q = q.filter(cond)
        return q.delete(synchronize_session=False)

    # children of the customer's conversations
    if conv_ids:
        wipe(models.Message, models.Message.conversation_id.in_(conv_ids))
        wipe(models.IntentLog, models.IntentLog.conversation_id.in_(conv_ids))
    # payments / reminders — by the customer or by any of their bookings
    pay_cond = models.Payment.customer_id == cid
    rem_cond = models.Reminder.customer_id == cid
    if booking_ids:
        pay_cond = or_(pay_cond, models.Payment.booking_id.in_(booking_ids))
        rem_cond = or_(rem_cond, models.Reminder.booking_id.in_(booking_ids))
    wipe(models.Payment, pay_cond)
    wipe(models.Reminder, rem_cond)
    # records that reference the customer directly
    wipe(models.Booking, models.Booking.customer_id == cid)
    wipe(models.Activity, models.Activity.customer_id == cid)
    wipe(models.Note, models.Note.customer_id == cid)
    wipe(models.Membership, models.Membership.customer_id == cid)
    wipe(models.Package, models.Package.customer_id == cid)
    wipe(models.Conversation, models.Conversation.customer_id == cid)
    db.delete(c)
    db.commit()
    realtime.publish({"type": "customer_deleted", "customer_id": cid,
                      "clinic_id": clinic_id})
    return {"ok": True, "deleted_customer_id": cid,
            "conversations": len(conv_ids), "bookings": len(booking_ids)}


@router.get("/customers/{cid}/timeline")
def timeline(cid: int, db: Session = Depends(get_db),
             _u: models.User = Depends(current_user),
             clinic_id: int = Depends(active_clinic_id)):
    acts = (scoped(db, models.Activity, clinic_id).filter_by(customer_id=cid)
            .order_by(models.Activity.created_at.desc()).limit(60).all())
    return [{"type": a.type, "summary": a.summary,
             "at": a.created_at.isoformat() if a.created_at else None}
            for a in acts]


@router.get("/customers/{cid}/notes")
def list_notes(cid: int, db: Session = Depends(get_db),
               _u: models.User = Depends(current_user),
               clinic_id: int = Depends(active_clinic_id)):
    rows = (scoped(db, models.Note, clinic_id).filter_by(customer_id=cid)
            .order_by(models.Note.id.desc()).all())
    out = []
    for n in rows:
        author = (scoped(db, models.User, clinic_id)
                  .filter(models.User.id == n.user_id).first()
                  if n.user_id else None)
        out.append({"id": n.id, "text": n.text,
                    "author": author.name if author else "System",
                    "at": n.created_at.isoformat() if n.created_at else None})
    return out


@router.post("/customers/{cid}/notes")
def add_note(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
             user: models.User = Depends(current_user),
             clinic_id: int = Depends(active_clinic_id)):
    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Note text is required")
    note = models.Note(customer_id=cid, user_id=user.id, text=text, clinic_id=clinic_id)
    db.add(note)
    db.add(models.Activity(customer_id=cid, type="note", summary="Note added",
                           user_id=user.id, clinic_id=clinic_id))
    db.commit()
    return {"id": note.id, "text": note.text, "author": user.name,
            "at": note.created_at.isoformat()}
