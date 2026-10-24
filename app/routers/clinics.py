"""Clinic (workspace) routes — list, create, delete, enter, leave.

The clinic picker calls these before the user enters a clinic's app. Creating a
clinic provisions it with a working starter setup; deleting archives it.
"""
import secrets
import threading
from pathlib import Path

from fastapi import (APIRouter, Body, Depends, File, HTTPException, Request,
                     Response, UploadFile)
from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal, get_db
from app.deps import (accessible_clinics, can_access_clinic, can_manage_clinics,
                      current_user, session_clinic_id)
from app.security import SESSION_COOKIE, SESSION_MAX_AGE, make_session

router = APIRouter(prefix="/api/clinics", tags=["clinics"])

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
LOGO_DIR = WEB_DIR / "assets" / "images" / "clinic-logos"
LOGO_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def clinic_public(clinic: models.Clinic, db: Session | None = None) -> dict:
    """Serialize a clinic for the client; with ``db`` it adds workspace counts."""
    d = {
        "id": clinic.id, "name": clinic.name, "slug": clinic.slug,
        "tagline": clinic.tagline, "logo": clinic.logo, "cover": clinic.cover,
        "accent": clinic.accent, "status": clinic.status,
    }
    if db is not None:
        d["branches"] = db.query(models.Branch).filter_by(clinic_id=clinic.id).count()
        d["customers"] = (db.query(models.Customer)
                          .filter_by(clinic_id=clinic.id, merged_into_id=None).count())
        d["staff"] = db.query(models.User).filter_by(clinic_id=clinic.id).count()
    return d


def _index_clinic_kb(clinic_id: int) -> None:
    """Embed a freshly provisioned clinic's knowledge base off the request path."""
    db = SessionLocal()
    try:
        from app.ai.rag import reindex

        reindex(db, clinic_id=clinic_id)
    except Exception as exc:  # pragma: no cover
        print("[clinics] KB index skipped:", exc)
    finally:
        db.close()


@router.get("")
def list_clinics(request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(current_user)):
    """Clinics this user may open — drives the workspace picker."""
    clinics = accessible_clinics(db, user)
    return {
        "clinics": [clinic_public(c, db) for c in clinics],
        "can_manage": can_manage_clinics(user),
        "active_id": session_clinic_id(request),
    }


@router.post("")
def create_clinic(data: dict = Body(...), db: Session = Depends(get_db),
                  user: models.User = Depends(current_user)):
    """Provision a new, immediately usable clinic (platform admins only)."""
    if not can_manage_clinics(user):
        raise HTTPException(status_code=403, detail="Only admins can add a clinic")
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Clinic name is required")

    from app.seed import provision_clinic

    clinic = provision_clinic(db, name, tagline=(data.get("tagline") or "").strip(),
                              starter=False)   # new clinics begin empty
    db.commit()
    threading.Thread(target=_index_clinic_kb, args=(clinic.id,), daemon=True).start()
    return clinic_public(clinic, db)


@router.delete("/{cid}")
def delete_clinic(cid: int, db: Session = Depends(get_db),
                  user: models.User = Depends(current_user)):
    """Archive a clinic so it leaves the workspace (platform admins only)."""
    if not can_manage_clinics(user):
        raise HTTPException(status_code=403, detail="Only admins can remove a clinic")
    clinic = db.get(models.Clinic, cid)
    if not clinic or clinic.status != "active":
        raise HTTPException(status_code=404, detail="Clinic not found")
    if db.query(models.Clinic).filter_by(status="active").count() <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last clinic")
    clinic.status = "archived"
    db.commit()
    return {"ok": True}


def _store_clinic_image(cid: int, file: UploadFile, db: Session, user: models.User,
                        attr: str) -> dict:
    """Validate + store an uploaded clinic image and point ``attr`` (logo/cover) at it."""
    if not can_manage_clinics(user):
        raise HTTPException(status_code=403, detail="Only admins can change a clinic image")
    clinic = db.get(models.Clinic, cid)
    if not clinic or clinic.status != "active":
        raise HTTPException(status_code=404, detail="Clinic not found")
    ext = LOGO_EXT.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Please upload a PNG, JPG or WebP image")
    data = file.file.read()
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image is too large (max 4 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{clinic.slug}-{attr}-{secrets.token_hex(4)}.{ext}"
    (LOGO_DIR / fname).write_bytes(data)
    setattr(clinic, attr, f"/assets/images/clinic-logos/{fname}")
    db.commit()
    return clinic_public(clinic, db)


@router.post("/{cid}/logo")
def upload_logo(cid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    """Upload / replace a clinic's business image (platform admins only)."""
    return _store_clinic_image(cid, file, db, user, "logo")


@router.post("/{cid}/cover")
def upload_cover(cid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                 user: models.User = Depends(current_user)):
    """Upload / replace the picker-card cover photo (platform admins only)."""
    return _store_clinic_image(cid, file, db, user, "cover")


@router.patch("/{cid}")
def update_clinic(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
                  user: models.User = Depends(current_user)):
    """Edit a clinic's name / tagline / accent from the workspace picker
    (platform admins only — mirrors the picker's edit-button gating)."""
    if not can_manage_clinics(user):
        raise HTTPException(status_code=403, detail="Only admins can edit a clinic")
    clinic = db.get(models.Clinic, cid)
    if not clinic or clinic.status != "active":
        raise HTTPException(status_code=404, detail="Clinic not found")
    if (data.get("name") or "").strip():
        clinic.name = data["name"].strip()
    if "tagline" in data and data["tagline"] is not None:
        clinic.tagline = str(data["tagline"]).strip()
    if data.get("accent"):
        clinic.accent = str(data["accent"])
    db.commit()
    return clinic_public(clinic, db)


@router.post("/{cid}/enter")
def enter_clinic(cid: int, response: Response, db: Session = Depends(get_db),
                 user: models.User = Depends(current_user)):
    """Set the active clinic on the session and step into its app."""
    clinic = db.get(models.Clinic, cid)
    if not clinic or clinic.status != "active":
        raise HTTPException(status_code=404, detail="Clinic not found")
    if not can_access_clinic(user, clinic):
        raise HTTPException(status_code=403, detail="You do not have access to this clinic")
    response.set_cookie(SESSION_COOKIE, make_session(user.id, clinic.id),
                        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
    return clinic_public(clinic, db)


@router.post("/leave")
def leave_clinic(response: Response, user: models.User = Depends(current_user)):
    """Clear the active clinic — returns the user to the workspace picker."""
    response.set_cookie(SESSION_COOKIE, make_session(user.id, None),
                        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
    return {"ok": True}
