"""System console — cross-clinic administration (platform / super_admin tier).

SECURITY — read before editing:
Every route here is guarded by ``require_system_admin`` (super_admin only) and
INTENTIONALLY uses plain ``db.query(...)`` rather than ``scope.scoped(...)`` so it
can read and write across *all* clinics. This is the one place in the codebase
where bypassing the per-clinic isolation chokepoint is correct — and it is safe
*only* because no non-system-admin user can reach these routes. Do not copy this
pattern into a clinic-scoped router.
"""
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.avatars import save_avatar
from app.database import get_db
from app.deps import SYSTEM_ADMIN, require_system_admin
from app.routers.clinics import _index_clinic_kb
from app.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])

ROLES = {"owner", "super_admin", "branch_manager", "sales", "doctor", "marketing"}
RANGES = {"7d": 7, "30d": 30, "90d": 90, "all": 4000}


# ============================================================
#  Global dashboard — KPIs aggregated across every clinic
# ============================================================
def _group(rows) -> dict:
    """Turn ``[(clinic_id, value), ...]`` into ``{clinic_id: value}`` (drops NULLs)."""
    return {cid: val for cid, val in rows if cid is not None}


@router.get("/overview")
def overview(period: str = "30d", db: Session = Depends(get_db),
             _u: models.User = Depends(require_system_admin)):
    """Cross-clinic headline metrics: per-clinic rows + platform totals."""
    days = RANGES.get(period, 30)
    since = datetime.utcnow() - timedelta(days=days)

    clinics = (db.query(models.Clinic).filter(models.Clinic.status == "active")
               .order_by(models.Clinic.id).all())

    _active = models.Customer.merged_into_id.is_(None)  # exclude merged golden-record stubs
    cust_total = _group(
        db.query(models.Customer.clinic_id, func.count(models.Customer.id))
        .filter(_active)
        .group_by(models.Customer.clinic_id).all())
    leads = _group(
        db.query(models.Customer.clinic_id, func.count(models.Customer.id))
        .filter(models.Customer.created_at >= since, _active)
        .group_by(models.Customer.clinic_id).all())
    # Cohort outcome of THIS window's leads, so conversion moves with the period
    # and Paid + Follow-up add up to it: Conversion = (Paid + Follow-up) / New leads.
    paid = _group(
        db.query(models.Customer.clinic_id, func.count(models.Customer.id))
        .filter(models.Customer.created_at >= since,
                models.Customer.pipeline_stage == "paid", _active)
        .group_by(models.Customer.clinic_id).all())
    followup = _group(
        db.query(models.Customer.clinic_id, func.count(models.Customer.id))
        .filter(models.Customer.created_at >= since,
                models.Customer.pipeline_stage == "followup", _active)
        .group_by(models.Customer.clinic_id).all())
    bookings = _group(
        db.query(models.Booking.clinic_id, func.count(models.Booking.id))
        .filter(models.Booking.created_at >= since)
        .group_by(models.Booking.clinic_id).all())
    revenue = _group(
        db.query(models.Payment.clinic_id,
                 func.coalesce(func.sum(models.Payment.amount), 0.0))
        .filter(models.Payment.status == "paid", models.Payment.paid_at >= since)
        .group_by(models.Payment.clinic_id).all())
    # Paid deposits secure a booking but aren't a settled sale — tracked
    # separately from "paid" (customers who reached the fully-paid stage).
    deposit_paid = _group(
        db.query(models.Payment.clinic_id, func.count(models.Payment.id))
        .filter(models.Payment.status == "paid", models.Payment.type == "deposit",
                models.Payment.paid_at >= since)
        .group_by(models.Payment.clinic_id).all())
    convs = _group(
        db.query(models.Conversation.clinic_id, func.count(models.Conversation.id))
        .group_by(models.Conversation.clinic_id).all())
    staff = _group(
        db.query(models.User.clinic_id, func.count(models.User.id))
        .filter(models.User.active.is_(True))
        .group_by(models.User.clinic_id).all())

    rows = []
    for c in clinics:
        ld = leads.get(c.id, 0)
        pd = paid.get(c.id, 0)
        fu = followup.get(c.id, 0)
        rows.append({
            "clinic_id": c.id, "name": c.name, "slug": c.slug,
            "accent": c.accent or "", "logo": c.logo or "",
            "revenue": round(float(revenue.get(c.id, 0.0)), 2),
            "leads": ld,
            "deposit_paid": deposit_paid.get(c.id, 0),
            "paid": pd,
            "followups": fu,
            "bookings": bookings.get(c.id, 0),
            "customers": cust_total.get(c.id, 0),
            "conversations": convs.get(c.id, 0),
            "staff": staff.get(c.id, 0),
            "conversion": round((pd + fu) / ld * 100, 1) if ld else 0.0,
        })

    all_leads = sum(r["leads"] for r in rows)
    all_paid = sum(r["paid"] for r in rows)
    all_deposit_paid = sum(r["deposit_paid"] for r in rows)
    all_followup = sum(r["followups"] for r in rows)
    totals = {
        "clinics": len(clinics),
        "revenue": round(sum(r["revenue"] for r in rows), 2),
        "leads": all_leads,
        "deposit_paid": all_deposit_paid,
        "paid": all_paid,
        "followups": all_followup,
        "bookings": sum(r["bookings"] for r in rows),
        "customers": sum(r["customers"] for r in rows),
        "conversations": sum(r["conversations"] for r in rows),
        "conversion": round((all_paid + all_followup) / all_leads * 100, 1) if all_leads else 0.0,
        "users": db.query(func.count(models.User.id))
                 .filter(models.User.active.is_(True)).scalar() or 0,
    }
    return {"totals": totals, "clinics": rows, "period": period}


# ============================================================
#  Clinic management
# ============================================================
def _clinic_dict(db: Session, c: models.Clinic) -> dict:
    branches = (db.query(models.Branch).filter_by(clinic_id=c.id)
                .order_by(models.Branch.id).all())
    paid_payments = db.query(models.Payment).filter(
        models.Payment.clinic_id == c.id, models.Payment.status == "paid")
    return {
        "id": c.id, "name": c.name, "slug": c.slug, "tagline": c.tagline,
        "logo": c.logo, "accent": c.accent, "status": c.status,
        "branches": [{"id": b.id, "name": b.name} for b in branches],
        "branch_count": len(branches),
        "staff": db.query(func.count(models.User.id)).filter(
            models.User.clinic_id == c.id, models.User.active.is_(True)).scalar() or 0,
        "customers": db.query(func.count(models.Customer.id)).filter(
            models.Customer.clinic_id == c.id,
            models.Customer.merged_into_id.is_(None)).scalar() or 0,
        # All-time payment totals (this table has no date-range picker, unlike
        # /admin/overview) — deposit_paid secures a booking, paid is a fully
        # settled sale, revenue is every paid deposit + full payment combined.
        "deposit_paid": paid_payments.filter(models.Payment.type == "deposit").count(),
        "paid": paid_payments.filter(models.Payment.type == "full").count(),
        "revenue": round(float(
            paid_payments.with_entities(
                func.coalesce(func.sum(models.Payment.amount), 0.0)).scalar() or 0.0), 2),
    }


@router.get("/clinics")
def list_clinics(db: Session = Depends(get_db),
                 _u: models.User = Depends(require_system_admin)):
    """Every clinic — active and archived — with workspace counts."""
    clinics = db.query(models.Clinic).order_by(models.Clinic.id).all()
    return [_clinic_dict(db, c) for c in clinics]


@router.post("/clinics")
def create_clinic(data: dict = Body(...), db: Session = Depends(get_db),
                  _u: models.User = Depends(require_system_admin)):
    """Provision a new, immediately usable clinic, then index its KB off-thread."""
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Clinic name is required")
    from app.seed import provision_clinic

    clinic = provision_clinic(db, name, tagline=(data.get("tagline") or "").strip(),
                              starter=False)   # console clinics begin empty
    if data.get("accent"):
        clinic.accent = str(data["accent"])
    db.commit()
    threading.Thread(target=_index_clinic_kb, args=(clinic.id,), daemon=True).start()
    return _clinic_dict(db, clinic)


@router.patch("/clinics/{cid}")
def update_clinic(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
                  _u: models.User = Depends(require_system_admin)):
    """Edit a clinic's name / tagline / accent, or archive / restore it."""
    clinic = db.get(models.Clinic, cid)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")
    if "name" in data and (data.get("name") or "").strip():
        clinic.name = data["name"].strip()
    if "tagline" in data and data["tagline"] is not None:
        clinic.tagline = str(data["tagline"]).strip()
    if data.get("accent"):
        clinic.accent = str(data["accent"])
    if "logo" in data:   # allow clearing the clinic image (revert to initials)
        clinic.logo = str(data.get("logo") or "")
    status = data.get("status")
    if status in ("active", "archived"):
        if (status == "archived" and clinic.status == "active"
                and db.query(models.Clinic).filter_by(status="active").count() <= 1):
            raise HTTPException(status_code=400, detail="Cannot archive the last active clinic")
        clinic.status = status
    db.commit()
    return _clinic_dict(db, clinic)


@router.delete("/clinics/{cid}")
def archive_clinic(cid: int, db: Session = Depends(get_db),
                   _u: models.User = Depends(require_system_admin)):
    """Archive a clinic (keeps its data, removes it from the workspace)."""
    clinic = db.get(models.Clinic, cid)
    if not clinic or clinic.status != "active":
        raise HTTPException(status_code=404, detail="Clinic not found")
    if db.query(models.Clinic).filter_by(status="active").count() <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last clinic")
    clinic.status = "archived"
    db.commit()
    return {"ok": True}


def _tenant_models():
    """Every ORM model that carries a clinic_id (i.e. tenant-scoped data)."""
    import inspect
    return [cls for _, cls in inspect.getmembers(models, inspect.isclass)
            if getattr(cls, "__tablename__", None) and hasattr(cls, "clinic_id")
            and cls is not models.Clinic]


@router.delete("/clinics/{cid}/purge")
def purge_clinic(cid: int, db: Session = Depends(get_db),
                 _u: models.User = Depends(require_system_admin)):
    """Permanently delete an ARCHIVED clinic and ALL of its data. Irreversible.

    Two-step by design: a clinic must be archived first, then purged. Wipes every
    tenant-scoped table for the clinic, then the clinic row itself.
    """
    clinic = db.get(models.Clinic, cid)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")
    if clinic.status != "archived":
        raise HTTPException(status_code=400,
                            detail="Archive the clinic before deleting it permanently")
    for model in _tenant_models():
        q = db.query(model).filter(model.clinic_id == cid)
        if model is models.User:
            q = q.filter(model.role != "super_admin")  # never delete platform admins
        q.delete(synchronize_session=False)
    db.delete(clinic)
    db.commit()
    return {"ok": True}


# ============================================================
#  User & role management (across clinics)
# ============================================================
def _user_dict(u: models.User, clinic_names: dict, branch_names: dict) -> dict:
    return {
        "id": u.id, "name": u.name, "email": u.email, "role": u.role,
        "title": u.title, "active": u.active, "avatar": u.avatar,
        "clinic_id": u.clinic_id, "clinic_name": clinic_names.get(u.clinic_id),
        "branch_id": u.branch_id, "branch_name": branch_names.get(u.branch_id),
    }


def _names(db: Session):
    clinic_names = {c.id: c.name for c in db.query(models.Clinic).all()}
    branch_names = {b.id: b.name for b in db.query(models.Branch).all()}
    return clinic_names, branch_names


def _validate_assignment(db: Session, role: str, clinic_id, branch_id):
    """Validate role / clinic / branch coherence; return the cleaned (clinic_id, branch_id).

    Only ``super_admin`` (the platform tier) may be clinic-less; every other role
    must belong to a clinic, and any branch must live in that same clinic.
    """
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role")
    if role in SYSTEM_ADMIN:
        if clinic_id and not db.get(models.Clinic, clinic_id):
            raise HTTPException(status_code=404, detail="Clinic not found")
        clinic_id = clinic_id or None
    else:
        if not clinic_id:
            raise HTTPException(status_code=400, detail="A clinic is required for this role")
        if not db.get(models.Clinic, clinic_id):
            raise HTTPException(status_code=404, detail="Clinic not found")
    if branch_id:
        branch = db.get(models.Branch, branch_id)
        if not branch or branch.clinic_id != clinic_id:
            raise HTTPException(status_code=400, detail="That branch does not belong to the chosen clinic")
    else:
        branch_id = None
    return clinic_id, branch_id


def _last_system_admin(db: Session, exclude_id: int) -> bool:
    """True if no *other* active system admin remains (lockout protection)."""
    return (db.query(models.User)
            .filter(models.User.role.in_(tuple(SYSTEM_ADMIN)),
                    models.User.active.is_(True), models.User.id != exclude_id)
            .count() == 0)


@router.get("/users")
def list_users(clinic_id: int | None = None, role: str = "", q: str = "",
               db: Session = Depends(get_db),
               _u: models.User = Depends(require_system_admin)):
    """Every login across all clinics, optionally filtered by clinic / role / search."""
    query = db.query(models.User)
    if clinic_id:
        query = query.filter(models.User.clinic_id == clinic_id)
    if role:
        query = query.filter(models.User.role == role)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(func.lower(models.User.name).like(like)
                             | func.lower(models.User.email).like(like))
    users = query.order_by(models.User.clinic_id, models.User.id).all()
    clinic_names, branch_names = _names(db)
    return [_user_dict(u, clinic_names, branch_names) for u in users]


@router.post("/users")
def create_user(data: dict = Body(...), db: Session = Depends(get_db),
                _u: models.User = Depends(require_system_admin)):
    """Create a login and assign it a role + clinic (+ optional branch)."""
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or "sales").strip()
    if not name or not email:
        raise HTTPException(status_code=400, detail="Name and email are required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="A password of at least 6 characters is required")
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(status_code=409, detail="That email is already in use")
    clinic_id, branch_id = _validate_assignment(
        db, role, data.get("clinic_id") or None, data.get("branch_id") or None)
    user = models.User(
        name=name, email=email, password_hash=hash_password(password), role=role,
        title=(data.get("title") or "").strip(), phone=(data.get("phone") or "").strip(),
        clinic_id=clinic_id, branch_id=branch_id, active=True,
    )
    db.add(user)
    db.commit()
    clinic_names, branch_names = _names(db)
    return _user_dict(user, clinic_names, branch_names)


@router.patch("/users/{uid}")
def update_user(uid: int, data: dict = Body(...), db: Session = Depends(get_db),
                actor: models.User = Depends(require_system_admin)):
    """Reassign a user's role / clinic / branch, toggle active, or reset password."""
    user = db.get(models.User, uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role = (data.get("role") or user.role).strip()
    clinic_id, branch_id = _validate_assignment(
        db, role,
        (data["clinic_id"] if "clinic_id" in data else user.clinic_id) or None,
        (data["branch_id"] if "branch_id" in data else user.branch_id) or None)

    next_active = bool(data["active"]) if "active" in data else user.active
    losing_admin = user.role in SYSTEM_ADMIN and (role not in SYSTEM_ADMIN or not next_active)
    if losing_admin:
        if user.id == actor.id:
            raise HTTPException(status_code=400, detail="You cannot disable or demote your own account")
        if _last_system_admin(db, user.id):
            raise HTTPException(status_code=400, detail="Cannot remove the last active system administrator")

    user.role = role
    user.clinic_id = clinic_id
    user.branch_id = branch_id
    for field in ("name", "title", "phone"):
        if field in data and data[field] is not None:
            setattr(user, field, str(data[field]).strip())
    if "active" in data:
        user.active = bool(data["active"])
    if "avatar" in data:   # allow clearing (revert to initials)
        user.avatar = str(data.get("avatar") or "")
    if data.get("password"):
        if len(data["password"]) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        user.password_hash = hash_password(data["password"])
    db.commit()
    clinic_names, branch_names = _names(db)
    return _user_dict(user, clinic_names, branch_names)


@router.delete("/users/{uid}")
def disable_user(uid: int, db: Session = Depends(get_db),
                 actor: models.User = Depends(require_system_admin)):
    """Soft-disable a login (never hard-delete — it would orphan assignment FKs)."""
    user = db.get(models.User, uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    if user.role in SYSTEM_ADMIN and _last_system_admin(db, user.id):
        raise HTTPException(status_code=400, detail="Cannot disable the last active system administrator")
    user.active = False
    db.commit()
    return {"ok": True}


@router.post("/users/{uid}/avatar")
def upload_user_avatar(uid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                       _u: models.User = Depends(require_system_admin)):
    """Set any user's profile photo (system admin)."""
    user = db.get(models.User, uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.avatar = save_avatar(file, f"u{uid}")
    db.commit()
    clinic_names, branch_names = _names(db)
    return _user_dict(user, clinic_names, branch_names)
