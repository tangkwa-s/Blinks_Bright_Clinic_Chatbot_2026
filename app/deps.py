"""FastAPI dependencies: authentication, clinic (tenant) scoping, role guards."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.security import SESSION_COOKIE, read_session

# Two access tiers:
#   SYSTEM_ADMIN — the platform tier. Operates the system console, sees/ manages
#                  every clinic, and is the only tier that may run clinic-less.
#   ELEVATED     — full rights *within a clinic*: bypass every role check and see
#                  all branches. ``owner`` is clinic-scoped (one clinic) but still
#                  the top role inside it; ``super_admin`` is elevated everywhere.
SYSTEM_ADMIN = {"super_admin"}
ELEVATED = {"owner", "super_admin"}


def current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """Resolve the logged-in user from the signed session cookie."""
    sess = read_session(request.cookies.get(SESSION_COOKIE))
    uid = sess.get("uid") if sess else None
    user = db.get(models.User, uid) if uid else None
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> models.User | None:
    """Like current_user but returns None instead of raising (for public routes)."""
    sess = read_session(request.cookies.get(SESSION_COOKIE))
    uid = sess.get("uid") if sess else None
    return db.get(models.User, uid) if uid else None


def require_role(*roles: str):
    """Dependency factory — restricts a route to the given roles (+ elevated)."""
    allowed = set(roles) | ELEVATED

    def _guard(user: models.User = Depends(current_user)) -> models.User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this")
        return user

    return _guard


def require_system_admin(user: models.User = Depends(current_user)) -> models.User:
    """Guard for the system console — platform (super_admin) tier only.

    Note: this does NOT admit ``owner`` (unlike ``require_role``), because owner is
    clinic-scoped. Every ``/api/admin/*`` route uses this.
    """
    if user.role not in SYSTEM_ADMIN:
        raise HTTPException(status_code=403, detail="System administrators only")
    return user


def is_system_admin(user: models.User) -> bool:
    return user.role in SYSTEM_ADMIN


# ============================================================
#  Clinic (tenant) scoping
# ============================================================
def can_manage_clinics(user: models.User) -> bool:
    """Only platform (system) admins may create / archive clinics."""
    return user.role in SYSTEM_ADMIN


def can_access_clinic(user: models.User, clinic: models.Clinic) -> bool:
    """System admins see every clinic; everyone else (incl. owner) only their own."""
    if user.role in SYSTEM_ADMIN:
        return True
    return user.clinic_id == clinic.id


def accessible_clinics(db: Session, user: models.User) -> list[models.Clinic]:
    """The active clinics this user is allowed to open."""
    q = db.query(models.Clinic).filter(models.Clinic.status == "active")
    if user.role in SYSTEM_ADMIN:
        return q.order_by(models.Clinic.id).all()
    if user.clinic_id:
        return q.filter(models.Clinic.id == user.clinic_id).all()
    return []


def session_clinic_id(request: Request) -> int | None:
    """The clinic id stored in the session cookie, if any."""
    sess = read_session(request.cookies.get(SESSION_COOKIE)) or {}
    return sess.get("cid")


def active_clinic(request: Request, db: Session = Depends(get_db),
                  user: models.User = Depends(current_user)) -> models.Clinic:
    """The clinic the session is currently scoped to.

    Raises ``409 no_clinic`` when none is selected or it is no longer
    accessible — the client then shows the clinic picker.
    """
    cid = session_clinic_id(request)
    clinic = db.get(models.Clinic, cid) if cid else None
    if (not clinic or clinic.status != "active"
            or not can_access_clinic(user, clinic)):
        raise HTTPException(status_code=409, detail="no_clinic")
    return clinic


def active_clinic_id(clinic: models.Clinic = Depends(active_clinic)) -> int:
    """Convenience dependency — just the active clinic id, for query scoping."""
    return clinic.id


# ============================================================
#  Branch scoping (within a clinic)
# ============================================================
def branch_scope(user: models.User) -> int | None:
    """The branch a user is locked to; None means they see all branches."""
    if user.role in ("owner", "super_admin", "marketing"):
        return None
    return user.branch_id


def effective_branch(user: models.User, requested) -> int | None:
    """Resolve the branch filter for a request, enforcing the user's role scope."""
    forced = branch_scope(user)
    if forced is not None:
        return forced
    if requested and requested not in ("all", ""):
        try:
            return int(requested)
        except (TypeError, ValueError):
            return None
    return None
