"""Catalog routes — branches, services, promotions, staff."""
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.avatars import save_avatar, save_service_image
from app.database import get_db
from app.deps import (ELEVATED, active_clinic, active_clinic_id, current_user,
                      require_role)
from app.scope import scoped
from app.security import hash_password
from app.services.booking import MAX_HOLD_MINUTES
from app.services.promotions import promo_branch_ids, promo_used_counts

router = APIRouter(prefix="/api", tags=["catalog"])

MANAGER = require_role("branch_manager", "marketing")
# Team management (creating logins / assigning roles) excludes marketing.
STAFF_MANAGER = require_role("branch_manager")

# Roles a clinic-level manager may assign through /staff. ``super_admin`` is a
# platform role (system console only); ``owner`` needs an elevated actor.
CLINIC_ROLES = {"owner", "branch_manager", "sales", "doctor", "marketing"}


def _reindex_async(cid: int) -> None:
    """Refresh the clinic's KB index off the request path after a catalog change, so
    deactivated treatments drop out of AI retrieval and newly added ones appear."""
    import threading
    from app.routers.clinics import _index_clinic_kb
    threading.Thread(target=_index_clinic_kb, args=(cid,), daemon=True).start()


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "").split(".")[0])
    except Exception:
        return None


def _get_or_404(db: Session, model, oid: int, cid: int):
    obj = scoped(db, model, cid).filter(model.id == oid).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


# ----------------------------- branches -----------------------------
def _load_hours(raw):
    """Branch.hours is stored as a JSON string; return it parsed (or {})."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def branch_dict(b: models.Branch) -> dict:
    return {
        "id": b.id, "name": b.name, "code": b.code, "phone": b.phone,
        "address": b.address, "open_hour": b.open_hour, "close_hour": b.close_hour,
        "hours": _load_hours(b.hours),
    }


def _apply_branch_fields(b: models.Branch, data: dict) -> None:
    for field in ("name", "code", "phone", "address", "open_hour", "close_hour"):
        if field in data and data[field] is not None:
            setattr(b, field, data[field])
    if "hours" in data and data["hours"] is not None:
        b.hours = (data["hours"] if isinstance(data["hours"], str)
                   else json.dumps(data["hours"]))


@router.get("/branches")
def list_branches(db: Session = Depends(get_db), _u=Depends(current_user),
                  cid: int = Depends(active_clinic_id)):
    return [branch_dict(b) for b in
            scoped(db, models.Branch, cid).order_by(models.Branch.id).all()]


@router.post("/branches")
def create_branch(data: dict = Body(...),
                  db: Session = Depends(get_db), _u=Depends(MANAGER),
                  cid: int = Depends(active_clinic_id)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Branch name is required")
    b = models.Branch(clinic_id=cid, name=name)
    _apply_branch_fields(b, data)
    db.add(b)
    db.commit()
    _reindex_async(cid)
    return branch_dict(b)


@router.patch("/branches/{bid}")
def update_branch(bid: int, data: dict = Body(...),
                  db: Session = Depends(get_db), _u=Depends(MANAGER),
                  cid: int = Depends(active_clinic_id)):
    b = _get_or_404(db, models.Branch, bid, cid)
    _apply_branch_fields(b, data)
    db.commit()
    _reindex_async(cid)
    return branch_dict(b)


# ----------------------------- AI assistant settings -----------------------------
AI_NAME_MAX = 60
AI_INSTRUCTIONS_MAX = 2000


def _ai_settings_dict(clinic: models.Clinic) -> dict:
    return {"ai_name": clinic.ai_name or "", "ai_instructions": clinic.ai_instructions or "",
           "hold_minutes": clinic.hold_minutes or 0}


@router.get("/clinic/ai-settings")
def get_ai_settings(_u=Depends(current_user),
                    clinic: models.Clinic = Depends(active_clinic)):
    """The clinic's AI assistant persona settings (any logged-in clinic user)."""
    return _ai_settings_dict(clinic)


@router.patch("/clinic/ai-settings")
def update_ai_settings(data: dict = Body(...),
                       db: Session = Depends(get_db), _u=Depends(MANAGER),
                       clinic: models.Clinic = Depends(active_clinic)):
    """Set the assistant's display name and clinic-specific extra guidance. These
    adjust tone / extra policy only — they can never override the safety, pricing
    honesty, or grounding rules baked into the system prompt."""
    if "ai_name" in data:
        name = str(data.get("ai_name") or "").strip()
        if len(name) > AI_NAME_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"Assistant name must be {AI_NAME_MAX} characters or fewer")
        clinic.ai_name = name
    if "ai_instructions" in data:
        instructions = str(data.get("ai_instructions") or "").strip()
        if len(instructions) > AI_INSTRUCTIONS_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"Instructions must be {AI_INSTRUCTIONS_MAX} characters or fewer")
        clinic.ai_instructions = instructions
    if "hold_minutes" in data:
        # 0 = "use the .env default" (resolved_hold_minutes), so 0 stays valid — never
        # clamped UP to a floor the way HOLD_MINUTES itself is.
        clinic.hold_minutes = max(0, min(int(data.get("hold_minutes") or 0), MAX_HOLD_MINUTES))
    db.commit()
    return _ai_settings_dict(clinic)


# ----------------------------- services -----------------------------
def service_dict(s: models.Service, prices: list[models.ServicePrice],
                 branch_ids: set[int] | None = None) -> dict:
    return {
        "id": s.id, "name": s.name, "category": s.category,
        "description": s.description, "base_price": s.base_price,
        "duration_min": s.duration_min,
        "recommended_interval_days": s.recommended_interval_days,
        "prep_notes": s.prep_notes, "aftercare_notes": s.aftercare_notes,
        "contraindications": s.contraindications, "image": s.image, "active": s.active,
        "deposit": s.deposit,
        "hold_minutes": s.hold_minutes,
        "branch_ids": sorted(branch_ids) if branch_ids else [],  # [] = every branch
        "prices": {p.branch_id: p.price for p in prices if p.service_id == s.id},
    }


def _branch_ids_by_service(db: Session, cid: int) -> dict[int, set[int]]:
    """Every service's restricted-branch set, keyed by service id. A service
    with no entry (or an empty set) is offered at every branch."""
    out: dict[int, set[int]] = {}
    for row in scoped(db, models.ServiceBranch, cid).all():
        out.setdefault(row.service_id, set()).add(row.branch_id)
    return out


@router.get("/services")
def list_services(db: Session = Depends(get_db), _u=Depends(current_user),
                  cid: int = Depends(active_clinic_id)):
    services = (scoped(db, models.Service, cid)
                .order_by(models.Service.category, models.Service.name).all())
    prices = scoped(db, models.ServicePrice, cid).all()
    branch_map = _branch_ids_by_service(db, cid)
    return [service_dict(s, prices, branch_map.get(s.id)) for s in services]


SERVICE_FIELDS = ("name", "category", "description", "base_price", "duration_min",
                  "recommended_interval_days", "deposit", "hold_minutes", "prep_notes",
                  "aftercare_notes", "contraindications", "image", "active")

# Sane upper bounds so a typo / paste can't store an absurd value (the form
# enforces these too; this is the server-side safety net). The deposit is
# capped at the base price — a customer can't be asked for more than the cost.
MAX_DURATION_MIN = 1440       # one full day
MAX_INTERVAL_DAYS = 3650      # ten years
MAX_PRICE = 10_000_000        # ฿10M


def _clamp_service(s: models.Service) -> None:
    """Keep a service's numeric fields within sane ranges; the deposit never
    exceeds the base price (0 = the automatic 20% applied at booking time)."""
    s.base_price = max(0.0, min(float(s.base_price or 0), MAX_PRICE))
    s.duration_min = max(0, min(int(s.duration_min or 0), MAX_DURATION_MIN))
    s.recommended_interval_days = max(0, min(int(s.recommended_interval_days or 0), MAX_INTERVAL_DAYS))
    s.deposit = max(0.0, min(float(s.deposit or 0), s.base_price))
    # 0 = "use the clinic's setting" (resolved_hold_minutes) — stays valid, unlike
    # deposit which clamps to base_price.
    s.hold_minutes = max(0, min(int(s.hold_minutes or 0), MAX_HOLD_MINUTES))


def _coerce_branch_ids(data: dict, all_branch_ids: set[int]) -> set[int]:
    """The submitted ``branch_ids`` (a list) for a treatment or a promotion — the specific branches
    it's restricted to. Missing/not-a-list collapses to "every branch" (empty set);
    selecting EVERY branch in the clinic is the same thing and is normalised the
    same way, so this only ever returns a real, partial subset or nothing."""
    raw = data.get("branch_ids")
    if not isinstance(raw, list):
        return set()
    ids: set[int] = set()
    for v in raw:
        try:
            bid = int(v)
        except (TypeError, ValueError):
            continue
        if bid in all_branch_ids:
            ids.add(bid)
    return set() if (not ids or ids >= all_branch_ids) else ids


def _set_service_branches(db: Session, cid: int, service_id: int, branch_ids: set[int]) -> None:
    (scoped(db, models.ServiceBranch, cid)
     .filter_by(service_id=service_id).delete(synchronize_session=False))
    for bid in branch_ids:
        db.add(models.ServiceBranch(clinic_id=cid, service_id=service_id, branch_id=bid))


def _set_promo_branches(db: Session, cid: int, promo_id: int, branch_ids: set[int]) -> None:
    (scoped(db, models.PromotionBranch, cid)
     .filter_by(promotion_id=promo_id).delete(synchronize_session=False))
    for bid in branch_ids:
        db.add(models.PromotionBranch(clinic_id=cid, promotion_id=promo_id, branch_id=bid))
    # The legacy single column would otherwise keep shadowing the join table for any
    # reader that still consults it.
    promo = scoped(db, models.Promotion, cid).filter_by(id=promo_id).first()
    if promo:
        promo.branch_id = None


def _parse_branch_prices(data: dict) -> dict[int, float | None]:
    """The submitted per-branch price map, keys cast to int (JSON keys are strings).
    ``None`` (a blanked input) means "remove the override, use the base price".

    A real override must be a real amount: anything at or below 0 is REJECTED, not
    clamped, because there is no price it could safely become. Clamping a negative
    up to 0 used to store a ฿0 override, and ``booking.resolved_price_detail`` reads
    that back as falsy — so it silently fell through to the base price and the form
    kept showing a price the customer would never be charged. A branch may price
    ABOVE the base price (that is what a premium branch is); the only ceiling is the
    same MAX_PRICE sanity cap the base price gets, and going over it is a paste/typo,
    so it clamps rather than 400s, exactly like ``_clamp_service``."""
    out: dict[int, float | None] = {}
    if not isinstance(data.get("prices"), dict):
        return out
    for bid, price in data["prices"].items():
        try:
            key = int(bid)
        except (TypeError, ValueError):
            continue
        if price is None or price == "":
            out[key] = None
            continue
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            raise HTTPException(
                status_code=400,
                detail="Per-branch price must be greater than 0 (leave it blank to use the base price)")
        out[key] = min(value, float(MAX_PRICE))
    return out


def _assert_unique_service_name(db: Session, cid: int, name: str, branch_ids: set[int],
                                branch_map: dict[int, set[int]],
                                exclude_id: int | None = None) -> None:
    """A treatment name must be unique among treatments whose branch scopes OVERLAP
    (case-insensitive, trimmed) — the live menu the AI prices and books from must
    never offer two identical names AT THE SAME BRANCH. Two treatments scoped to
    disjoint branch subsets may reuse a name for their own version of it; an empty
    set (this treatment, the other, or both) means "every branch" so it always
    overlaps with everything."""
    norm = (name or "").strip().casefold()
    if not norm:
        return
    for other in scoped(db, models.Service, cid).all():
        if other.id == exclude_id:
            continue
        other_ids = branch_map.get(other.id, set())
        overlaps = not branch_ids or not other_ids or bool(branch_ids & other_ids)
        if not overlaps:
            continue
        if (other.name or "").strip().casefold() == norm:
            raise HTTPException(
                status_code=409,
                detail=f'A treatment named "{name.strip()}" already exists at an overlapping branch')


@router.post("/services")
def create_service(data: dict = Body(...),
                   db: Session = Depends(get_db), _u=Depends(MANAGER),
                   cid: int = Depends(active_clinic_id)):
    all_branches = scoped(db, models.Branch, cid).all()
    all_branch_ids = {b.id for b in all_branches}
    branch_ids = _coerce_branch_ids(data, all_branch_ids)
    branch_map = _branch_ids_by_service(db, cid)
    _assert_unique_service_name(db, cid, data.get("name", ""), branch_ids, branch_map)
    # Validated before anything is written, so a rejected price can't leave half a
    # treatment behind.
    overrides = _parse_branch_prices(data)
    s = models.Service(name=data.get("name", "Untitled treatment"), clinic_id=cid)
    for field in SERVICE_FIELDS:
        if field in data:
            setattr(s, field, data[field])
    _clamp_service(s)
    db.add(s)
    db.flush()
    _set_service_branches(db, cid, s.id, branch_ids)
    # Honour per-branch prices typed while creating (previously silently dropped);
    # branches without an explicit override are seeded at the base price. A
    # treatment restricted to specific branches only ever needs price rows for those.
    target_branches = [b for b in all_branches if not branch_ids or b.id in branch_ids]
    for b in target_branches:
        price = overrides.get(b.id)
        db.add(models.ServicePrice(service_id=s.id, branch_id=b.id,
                                   price=s.base_price if price is None else price,
                                   clinic_id=cid))
    db.commit()
    _reindex_async(cid)
    return service_dict(s, scoped(db, models.ServicePrice, cid)
                        .filter_by(service_id=s.id).all(), branch_ids)


@router.patch("/services/{sid}")
def update_service(sid: int, data: dict = Body(...),
                   db: Session = Depends(get_db), _u=Depends(MANAGER),
                   cid: int = Depends(active_clinic_id)):
    s = _get_or_404(db, models.Service, sid, cid)
    price_overrides = _parse_branch_prices(data)   # rejected up front, before any write
    all_branches = scoped(db, models.Branch, cid).all()
    all_branch_ids = {b.id for b in all_branches}
    branch_map = _branch_ids_by_service(db, cid)
    current_branch_ids = branch_map.get(sid, set())
    branch_changing = "branch_ids" in data
    new_branch_ids = (_coerce_branch_ids(data, all_branch_ids) if branch_changing
                      else current_branch_ids)

    if "name" in data or branch_changing:
        _assert_unique_service_name(db, cid, data.get("name", s.name), new_branch_ids,
                                    branch_map, exclude_id=sid)
    old_base = float(s.base_price or 0)
    for field in SERVICE_FIELDS:
        if field in data:
            setattr(s, field, data[field])
    _clamp_service(s)
    if branch_changing and new_branch_ids != current_branch_ids:
        _set_service_branches(db, cid, sid, new_branch_ids)
        if new_branch_ids:
            # Now restricted to specific branches — price rows for branches no
            # longer in scope become unreachable (AI will never offer it there).
            (scoped(db, models.ServicePrice, cid)
             .filter(models.ServicePrice.service_id == sid,
                     ~models.ServicePrice.branch_id.in_(new_branch_ids))
             .delete(synchronize_session=False))
            existing = {p.branch_id for p in scoped(db, models.ServicePrice, cid)
                        .filter_by(service_id=sid).all()}
            for bid in new_branch_ids:
                if bid not in existing:
                    db.add(models.ServicePrice(service_id=sid, branch_id=bid,
                                               price=s.base_price, clinic_id=cid))
        else:
            # Back to "all branches" — seed any branch that doesn't have a row yet.
            existing = {p.branch_id for p in scoped(db, models.ServicePrice, cid)
                        .filter_by(service_id=sid).all()}
            for b in all_branches:
                if b.id not in existing:
                    db.add(models.ServicePrice(service_id=sid, branch_id=b.id,
                                               price=s.base_price, clinic_id=cid))
    if "base_price" in data and float(s.base_price or 0) != old_base:
        # Sync the implicit per-branch seeds (create_service mirrors the base price
        # into a ServicePrice row per branch): rows still equal to the OLD base are
        # not real overrides, so follow the new base — otherwise a base-price edit
        # never changes what the AI quotes or what a booking charges.
        (scoped(db, models.ServicePrice, cid)
         .filter_by(service_id=sid, price=old_base)
         .update({models.ServicePrice.price: s.base_price},
                 synchronize_session=False))
    for bid, price in price_overrides.items():
        row = (scoped(db, models.ServicePrice, cid)
               .filter_by(service_id=sid, branch_id=bid).first())
        if price is None:            # blanked input — "blank uses base price"
            if row:
                db.delete(row)
        elif row:
            row.price = price
        else:
            db.add(models.ServicePrice(service_id=sid, branch_id=bid,
                                       price=price, clinic_id=cid))
    db.commit()
    if any(f in data for f in SERVICE_FIELDS) or branch_changing:  # KB-affecting change -> refresh index
        _reindex_async(cid)
    final_branch_ids = new_branch_ids if branch_changing else current_branch_ids
    return service_dict(s, scoped(db, models.ServicePrice, cid)
                        .filter_by(service_id=sid).all(), final_branch_ids)


@router.delete("/services/{sid}")
def delete_service(sid: int, db: Session = Depends(get_db), _u=Depends(MANAGER),
                   cid: int = Depends(active_clinic_id)):
    """Remove a treatment from the menu and the AI. If it has past bookings it is
    soft-archived (active=False) to keep history intact; otherwise it (and its
    branch prices + promotions) is deleted outright."""
    s = _get_or_404(db, models.Service, sid, cid)
    has_history = (scoped(db, models.Booking, cid)
                   .filter_by(service_id=sid).first() is not None)
    if has_history:
        s.active = False
        db.commit()
        _reindex_async(cid)
        return {"ok": True, "archived": True}
    (scoped(db, models.ServicePrice, cid)
     .filter_by(service_id=sid).delete(synchronize_session=False))
    (scoped(db, models.ServiceBranch, cid)
     .filter_by(service_id=sid).delete(synchronize_session=False))
    (scoped(db, models.Promotion, cid)
     .filter_by(service_id=sid).delete(synchronize_session=False))
    db.delete(s)
    db.commit()
    _reindex_async(cid)
    return {"ok": True, "archived": False}


@router.post("/services/{sid}/image")
def upload_service_image(sid: int, file: UploadFile = File(...),
                         db: Session = Depends(get_db), _u=Depends(MANAGER),
                         cid: int = Depends(active_clinic_id)):
    """Set a treatment's menu / customer-facing photo (clinic-scoped)."""
    s = _get_or_404(db, models.Service, sid, cid)
    s.image = save_service_image(file, f"s{sid}")
    db.commit()
    _reindex_async(cid)
    branch_ids = _branch_ids_by_service(db, cid).get(sid)
    return service_dict(s, scoped(db, models.ServicePrice, cid)
                        .filter_by(service_id=sid).all(), branch_ids)


# ----------------------------- promotions -----------------------------
def _coerce_quota(value) -> int:
    """Redemption quota from client input — a non-negative int; 0 = unlimited."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def promo_dict(p: models.Promotion, used: int = 0, branch_ids=None) -> dict:
    return {
        "id": p.id, "title": p.title, "detail": p.detail, "service_id": p.service_id,
        # branch_ids is the live field; branch_id stays in the payload only so an old
        # cached page keeps rendering until it reloads.
        "branch_ids": sorted(branch_ids or []),
        "branch_id": p.branch_id, "discount_label": p.discount_label,
        "promo_price": p.promo_price, "active": p.active,
        "quota": int(p.quota or 0), "used": used,
        "valid_from": p.valid_from.isoformat() if p.valid_from else None,
        "valid_to": p.valid_to.isoformat() if p.valid_to else None,
    }


@router.get("/promotions")
def list_promotions(db: Session = Depends(get_db), _u=Depends(current_user),
                    cid: int = Depends(active_clinic_id)):
    rows = scoped(db, models.Promotion, cid).order_by(models.Promotion.id.desc()).all()
    counts = promo_used_counts(db, cid)  # one grouped query for the whole list
    bmap = promo_branch_ids(db, cid)
    return [promo_dict(p, counts.get(p.id, 0), bmap.get(p.id)) for p in rows]


@router.post("/promotions")
def create_promotion(data: dict = Body(...),
                     db: Session = Depends(get_db), _u=Depends(MANAGER),
                     cid: int = Depends(active_clinic_id)):
    p = models.Promotion(
        title=data.get("title", "New promotion"),
        detail=data.get("detail", ""),
        service_id=data.get("service_id"),
        discount_label=data.get("discount_label", ""),
        promo_price=data.get("promo_price"),
        quota=_coerce_quota(data.get("quota")),
        valid_from=_parse_dt(data.get("valid_from")),
        valid_to=_parse_dt(data.get("valid_to")),
        active=data.get("active", True),
        clinic_id=cid,
    )
    db.add(p)
    db.flush()
    all_branch_ids = {b.id for b in scoped(db, models.Branch, cid).all()}
    branch_ids = _coerce_branch_ids(data, all_branch_ids)
    _set_promo_branches(db, cid, p.id, branch_ids)
    db.commit()
    _reindex_async(cid)
    return promo_dict(p, 0, branch_ids)


@router.patch("/promotions/{pid}")
def update_promotion(pid: int, data: dict = Body(...),
                     db: Session = Depends(get_db), _u=Depends(MANAGER),
                     cid: int = Depends(active_clinic_id)):
    p = _get_or_404(db, models.Promotion, pid, cid)
    for field in ("title", "detail", "service_id",
                  "discount_label", "promo_price", "active"):
        if field in data:
            setattr(p, field, data[field])
    if "quota" in data:
        p.quota = _coerce_quota(data["quota"])
    if "valid_from" in data:
        p.valid_from = _parse_dt(data["valid_from"])
    if "valid_to" in data:
        p.valid_to = _parse_dt(data["valid_to"])
    if "branch_ids" in data:
        all_branch_ids = {b.id for b in scoped(db, models.Branch, cid).all()}
        _set_promo_branches(db, cid, p.id, _coerce_branch_ids(data, all_branch_ids))
    db.commit()
    _reindex_async(cid)
    return promo_dict(p, promo_used_counts(db, cid, [p.id]).get(p.id, 0),
                      promo_branch_ids(db, cid).get(p.id))


@router.delete("/promotions/{pid}")
def delete_promotion(pid: int, db: Session = Depends(get_db), _u=Depends(MANAGER),
                     cid: int = Depends(active_clinic_id)):
    """Remove a promotion. If bookings were made under it, it is deactivated
    instead (keeps the redemption/attribution history); otherwise deleted."""
    p = _get_or_404(db, models.Promotion, pid, cid)
    has_history = (scoped(db, models.Booking, cid)
                   .filter(models.Booking.promo_id == pid).first() is not None)
    if has_history:
        p.active = False
        db.commit()
        _reindex_async(cid)
        return {"ok": True, "archived": True}
    db.delete(p)
    db.commit()
    _reindex_async(cid)
    return {"ok": True, "archived": False}


# ----------------------------- staff -----------------------------
@router.get("/staff")
def list_staff(db: Session = Depends(get_db), _u=Depends(current_user),
               cid: int = Depends(active_clinic_id)):
    branches = {b.id: b.name for b in scoped(db, models.Branch, cid).all()}
    return [
        {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
         "title": u.title, "bio": u.bio, "phone": u.phone, "branch_id": u.branch_id,
         "branch_name": branches.get(u.branch_id), "active": u.active, "avatar": u.avatar}
        for u in scoped(db, models.User, cid).order_by(models.User.id).all()
    ]


def _staff_dict(db: Session, u: models.User) -> dict:
    branch = db.get(models.Branch, u.branch_id) if u.branch_id else None
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
            "title": u.title, "bio": u.bio, "phone": u.phone, "branch_id": u.branch_id,
            "branch_name": branch.name if branch else None, "active": u.active,
            "avatar": u.avatar}


def _guard_assigned_role(actor: models.User, role: str) -> None:
    """Clinic managers may not mint platform admins; only elevated actors (owner /
    super_admin) may assign the ``owner`` role."""
    if role == "super_admin":
        raise HTTPException(
            status_code=403, detail="System admins are managed from the system console")
    if role not in CLINIC_ROLES:
        raise HTTPException(status_code=400, detail="Unknown role")
    if role == "owner" and actor.role not in ELEVATED:
        raise HTTPException(status_code=403, detail="Only an owner can assign the owner role")


def _resolve_staff_branch(db: Session, cid: int, branch_id) -> int | None:
    if not branch_id:
        return None
    b = scoped(db, models.Branch, cid).filter(models.Branch.id == int(branch_id)).first()
    if not b:
        raise HTTPException(status_code=400, detail="That branch is not in this clinic")
    return b.id


@router.post("/staff")
def create_staff(data: dict = Body(...), db: Session = Depends(get_db),
                 actor: models.User = Depends(STAFF_MANAGER),
                 clinic: models.Clinic = Depends(active_clinic)):
    """Add a clinic team member (login optional — placeholder email if none given)."""
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A name is required")
    role = (data.get("role") or "sales").strip()
    _guard_assigned_role(actor, role)
    branch_id = _resolve_staff_branch(db, clinic.id, data.get("branch_id"))

    email = (data.get("email") or "").strip().lower()
    if email:
        if db.query(models.User).filter(models.User.email == email).first():
            raise HTTPException(status_code=409, detail="That email is already in use")
    else:
        # team.js adds doctors/staff without a login email — mint a unique placeholder
        email = f"{clinic.slug}.{secrets.token_hex(4)}@staff.local"

    password = data.get("password") or secrets.token_urlsafe(12)
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user = models.User(
        clinic_id=clinic.id, name=name, email=email,
        password_hash=hash_password(password), role=role,
        title=(data.get("title") or "").strip(), phone=(data.get("phone") or "").strip(),
        branch_id=branch_id, active=True,
    )
    db.add(user)
    db.commit()
    return _staff_dict(db, user)


@router.patch("/staff/{uid}")
def update_staff(uid: int, data: dict = Body(...), db: Session = Depends(get_db),
                 actor: models.User = Depends(STAFF_MANAGER),
                 cid: int = Depends(active_clinic_id)):
    """Edit a team member in the active clinic (clinic-scoped — can't reach others)."""
    user = scoped(db, models.User, cid).filter(models.User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Team member not found")
    # a branch manager cannot tamper with the owners / super admins above them
    if actor.role not in ELEVATED and user.role in ELEVATED:
        raise HTTPException(status_code=403, detail="You cannot edit this account")
    if data.get("role") and data["role"].strip() != user.role:
        _guard_assigned_role(actor, data["role"].strip())
        user.role = data["role"].strip()
    if "email" in data:
        new_email = (data.get("email") or "").strip().lower()
        if new_email and new_email != user.email:
            if db.query(models.User).filter(models.User.email == new_email,
                                            models.User.id != user.id).first():
                raise HTTPException(status_code=409, detail="That email is already in use")
            user.email = new_email
    if "branch_id" in data:
        user.branch_id = _resolve_staff_branch(db, cid, data.get("branch_id"))
    for field in ("name", "title", "phone", "bio"):
        if field in data and data[field] is not None:
            setattr(user, field, str(data[field]).strip())
    if "avatar" in data:   # allow clearing (revert to initials)
        user.avatar = str(data.get("avatar") or "")
    if "active" in data:
        if user.id == actor.id and not data["active"]:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        user.active = bool(data["active"])
    if data.get("password"):
        if len(data["password"]) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        user.password_hash = hash_password(data["password"])
    db.commit()
    return _staff_dict(db, user)


@router.delete("/staff/{uid}")
def disable_staff(uid: int, db: Session = Depends(get_db),
                  actor: models.User = Depends(STAFF_MANAGER),
                  cid: int = Depends(active_clinic_id)):
    """Soft-disable a team member (kept for audit / FK integrity)."""
    user = scoped(db, models.User, cid).filter(models.User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Team member not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    if actor.role not in ELEVATED and user.role in ELEVATED:
        raise HTTPException(status_code=403, detail="You cannot remove this account")
    user.active = False
    db.commit()
    return {"ok": True}


@router.delete("/staff/{uid}/purge")
def delete_staff_account(uid: int, db: Session = Depends(get_db),
                         actor: models.User = Depends(STAFF_MANAGER),
                         cid: int = Depends(active_clinic_id)):
    """Permanently delete a team member's login account (vs the reversible Active
    toggle). References to them are detached first so nothing dangles."""
    user = scoped(db, models.User, cid).filter(models.User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Team member not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if actor.role not in ELEVATED and user.role in ELEVATED:
        raise HTTPException(status_code=403, detail="You cannot delete this account")
    if user.role == "owner" and (scoped(db, models.User, cid)
            .filter(models.User.role == "owner", models.User.id != uid).count() == 0):
        raise HTTPException(status_code=400, detail="Cannot delete the clinic's only owner")
    for conv in scoped(db, models.Conversation, cid).filter_by(assigned_user_id=uid).all():
        conv.assigned_user_id = None
    for cust in scoped(db, models.Customer, cid).filter_by(assigned_user_id=uid).all():
        cust.assigned_user_id = None
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.post("/staff/{uid}/avatar")
def upload_staff_avatar(uid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                        actor: models.User = Depends(STAFF_MANAGER),
                        cid: int = Depends(active_clinic_id)):
    """Set a team member's profile photo (clinic-scoped)."""
    user = scoped(db, models.User, cid).filter(models.User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Team member not found")
    if actor.role not in ELEVATED and user.role in ELEVATED:
        raise HTTPException(status_code=403, detail="You cannot edit this account")
    user.avatar = save_avatar(file, f"u{uid}")
    db.commit()
    return _staff_dict(db, user)


# ----------------- team members (clinical roster — NOT login users) -----------------
# `/staff` above manages login Users (accounts). `/team-members` manages the
# separate StaffMember roster shown in Doctors & Staff and assigned to bookings.
TEAM_ROLES = {"doctor", "nurse", "therapist", "staff"}


def _clean_phone(value) -> str:
    """Keep digits only, capped at 10 (a Thai phone number)."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:10]


def _validate_ics_url(value) -> str:
    """Empty clears it. ``webcal://`` is normalised to ``https://`` — that scheme only
    exists to hint a calendar app to subscribe rather than download; calendar_sync
    fetches over plain HTTP(S) either way."""
    url = (value or "").strip()
    if not url:
        return ""
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400,
                            detail="Calendar URL must be http(s):// or webcal://")
    return url[:500]


def _team_member_dict(db: Session, m: models.StaffMember) -> dict:
    branch = db.get(models.Branch, m.branch_id) if m.branch_id else None
    return {"id": m.id, "name": m.name, "role": m.role, "title": m.title,
            "bio": m.bio, "phone": m.phone, "branch_id": m.branch_id,
            "branch_name": branch.name if branch else None,
            "avatar": m.avatar, "active": m.active,
            "ics_url": m.ics_url,
            "ics_last_synced_at": m.ics_last_synced_at.isoformat() if m.ics_last_synced_at else None,
            "ics_last_error": m.ics_last_error,
            "ics_last_error_at": m.ics_last_error_at.isoformat() if m.ics_last_error_at else None}


@router.get("/team-members")
def list_team_members(db: Session = Depends(get_db), _u=Depends(current_user),
                      cid: int = Depends(active_clinic_id)):
    return [_team_member_dict(db, m) for m in
            scoped(db, models.StaffMember, cid).order_by(models.StaffMember.id).all()]


@router.get("/team-members/busy-blocks")
def list_busy_blocks(date: str, db: Session = Depends(get_db), _u=Depends(current_user),
                     cid: int = Depends(active_clinic_id)):
    """A day's synced external-calendar busy blocks, across every doctor — what the
    Team → Booking schedule tab overlays next to real bookings, so 'why is this doctor
    unavailable here' is visible without opening each doctor's edit form."""
    try:
        day_start = datetime.fromisoformat(date).replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")
    day_end = day_start + timedelta(days=1)
    rows = (scoped(db, models.ExternalBusyBlock, cid)
           .filter(models.ExternalBusyBlock.starts_at < day_end,
                   models.ExternalBusyBlock.ends_at > day_start)
           .all())
    staff = {m.id: m for m in scoped(db, models.StaffMember, cid).all()}
    return [{"id": r.id, "staff_id": r.staff_id,
            "staff_name": staff[r.staff_id].name if r.staff_id in staff else None,
            "branch_id": staff[r.staff_id].branch_id if r.staff_id in staff else None,
            "starts_at": r.starts_at.isoformat(), "ends_at": r.ends_at.isoformat()}
           for r in rows if r.staff_id in staff]


@router.post("/team-members")
def create_team_member(data: dict = Body(...), db: Session = Depends(get_db),
                       _u=Depends(STAFF_MANAGER), cid: int = Depends(active_clinic_id)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A name is required")
    role = (data.get("role") or "doctor").strip()
    m = models.StaffMember(
        clinic_id=cid, name=name, role=role if role in TEAM_ROLES else "staff",
        title=(data.get("title") or "").strip(), phone=_clean_phone(data.get("phone")),
        bio=(data.get("bio") or "").strip(),
        branch_id=_resolve_staff_branch(db, cid, data.get("branch_id")), active=True,
        ics_url=_validate_ics_url(data.get("ics_url")),
    )
    db.add(m)
    db.commit()
    _reindex_async(cid)
    return _team_member_dict(db, m)


@router.patch("/team-members/{mid}")
def update_team_member(mid: int, data: dict = Body(...), db: Session = Depends(get_db),
                       _u=Depends(STAFF_MANAGER), cid: int = Depends(active_clinic_id)):
    m = scoped(db, models.StaffMember, cid).filter(models.StaffMember.id == mid).first()
    if not m:
        raise HTTPException(status_code=404, detail="Team member not found")
    if data.get("role") and data["role"].strip() in TEAM_ROLES:
        m.role = data["role"].strip()
    if "branch_id" in data:
        m.branch_id = _resolve_staff_branch(db, cid, data.get("branch_id"))
    for field in ("name", "title", "bio"):
        if field in data and data[field] is not None:
            setattr(m, field, str(data[field]).strip())
    if "phone" in data:
        m.phone = _clean_phone(data.get("phone"))
    if "ics_url" in data:
        m.ics_url = _validate_ics_url(data.get("ics_url"))
        if not m.ics_url:
            # Cleared, not just changed — a busy block from a calendar this doctor no
            # longer has configured must not go on silently blocking their slots.
            (scoped(db, models.ExternalBusyBlock, cid)
             .filter(models.ExternalBusyBlock.staff_id == m.id)
             .delete(synchronize_session=False))
            m.ics_last_synced_at = None
            m.ics_last_error = ""
            m.ics_last_error_at = None
    if "avatar" in data:
        m.avatar = str(data.get("avatar") or "")
    if "active" in data:
        m.active = bool(data["active"])
    db.commit()
    _reindex_async(cid)
    return _team_member_dict(db, m)


@router.delete("/team-members/{mid}")
def delete_team_member(mid: int, db: Session = Depends(get_db),
                       _u=Depends(STAFF_MANAGER), cid: int = Depends(active_clinic_id)):
    """Permanently remove a clinical staff member (the Active toggle handles a
    reversible deactivate). Any bookings assigned to them are unassigned."""
    m = scoped(db, models.StaffMember, cid).filter(models.StaffMember.id == mid).first()
    if not m:
        raise HTTPException(status_code=404, detail="Team member not found")
    for bk in scoped(db, models.Booking, cid).filter(models.Booking.doctor_id == mid).all():
        bk.doctor_id = None
    (scoped(db, models.ExternalBusyBlock, cid)
     .filter(models.ExternalBusyBlock.staff_id == mid)
     .delete(synchronize_session=False))
    db.delete(m)
    db.commit()
    _reindex_async(cid)
    return {"ok": True}


@router.post("/team-members/{mid}/avatar")
def upload_team_member_avatar(mid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                              _u=Depends(STAFF_MANAGER), cid: int = Depends(active_clinic_id)):
    m = scoped(db, models.StaffMember, cid).filter(models.StaffMember.id == mid).first()
    if not m:
        raise HTTPException(status_code=404, detail="Team member not found")
    m.avatar = save_avatar(file, f"sm{mid}")
    db.commit()
    return _team_member_dict(db, m)


@router.post("/team-members/{mid}/sync-calendar")
def sync_team_member_calendar(mid: int, db: Session = Depends(get_db),
                              _u=Depends(STAFF_MANAGER), cid: int = Depends(active_clinic_id)):
    """Manual 'sync now' — lets an admin test a freshly-pasted calendar URL immediately
    rather than waiting for the next scheduled tick (up to calendar_sync_minutes away).
    This DOES make a live network call — that is the point of the button — but only
    here, on an explicit admin action, never inside claim_slot/day_availability."""
    m = scoped(db, models.StaffMember, cid).filter(models.StaffMember.id == mid).first()
    if not m:
        raise HTTPException(status_code=404, detail="Team member not found")
    if not m.ics_url:
        raise HTTPException(status_code=400, detail="No calendar URL configured")
    from app.services.calendar_sync import sync_staff_calendar

    sync_staff_calendar(db, m)
    return _team_member_dict(db, m)   # 200 either way — ics_last_error tells the caller
