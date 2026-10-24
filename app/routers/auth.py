"""Authentication routes: login, logout, current user."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import (can_access_clinic, can_manage_clinics, current_user,
                      is_system_admin, session_clinic_id)
from app.routers.clinics import clinic_public
from app.security import SESSION_COOKIE, SESSION_MAX_AGE, make_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def user_public(user: models.User, db: Session) -> dict:
    """Serialize a user for the client (no password hash)."""
    branch = db.get(models.Branch, user.branch_id) if user.branch_id else None
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "title": user.title,
        "avatar": user.avatar,
        "branch_id": user.branch_id,
        "branch_name": branch.name if branch else None,
        "clinic_id": user.clinic_id,
    }


@router.post("/login")
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = (
        db.query(models.User)
        .filter(models.User.email == data.email.lower().strip())
        .first()
    )
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.active:
        raise HTTPException(status_code=403, detail="This account is disabled")
    # log in with no clinic selected — the client shows the workspace picker
    response.set_cookie(
        SESSION_COOKIE,
        make_session(user.id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return user_public(user, db)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: models.User = Depends(current_user),
       db: Session = Depends(get_db)):
    """The signed-in user plus the active clinic (None → show the picker)."""
    cid = session_clinic_id(request)
    clinic = db.get(models.Clinic, cid) if cid else None
    if clinic and (clinic.status != "active" or not can_access_clinic(user, clinic)):
        clinic = None
    return {
        "user": user_public(user, db),
        "active_clinic": clinic_public(clinic, db) if clinic else None,
        "can_manage_clinics": can_manage_clinics(user),
        # tier routes the SPA: 'system' → the global console, 'clinic' → a workspace
        "tier": "system" if is_system_admin(user) else "clinic",
    }
