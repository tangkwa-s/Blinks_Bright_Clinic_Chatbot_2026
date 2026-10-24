"""FastAPI application entry point for Blinks Bright."""
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import models
from app.config import settings
from app.database import SessionLocal, init_db
from app.routers import (admin, analytics, auth, bookings, broadcast, calendar,
                         portal,
                         catalog, channels, clinics, conversations, customers,
                         dashboard, knowledge, payments, retention, testconsole)

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
PUBLIC_PAGES = {"chat", "home", "portal"}


def _index_kb_background() -> None:
    """Build the KB vector index once, off the request path."""
    db = SessionLocal()
    try:
        if db.query(models.KBChunk).count() == 0:
            from app.ai.rag import reindex

            result = reindex(db)
            print("[startup] knowledge base indexed:", result)
    except Exception as exc:  # pragma: no cover
        print("[startup] KB index skipped:", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    db = SessionLocal()
    fresh_db = db.query(models.Clinic).first() is None  # very first run?
    db.close()
    try:
        from app.seed import seed_if_empty

        seed_if_empty()
    except Exception as exc:  # pragma: no cover
        print("[startup] seed skipped:", exc)
    try:
        from app.seed import backfill_staff_members

        db = SessionLocal()
        try:
            moved = backfill_staff_members(db)
            if moved:
                print(f"[startup] migrated {moved} doctors into the staff roster")
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print("[startup] staff-member migration skipped:", exc)
    try:
        from app.seed import backfill_automation_rules

        db = SessionLocal()
        try:
            added = backfill_automation_rules(db)
            if added:
                print(f"[startup] backfilled {added} automation rule(s)")
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print("[startup] automation-rule backfill skipped:", exc)
    try:
        from app.seed import backfill_branch_hours

        db = SessionLocal()
        try:
            fixed = backfill_branch_hours(db)
            if fixed["branches"] or fixed["articles"]:
                print(f"[startup] opening hours: migrated {fixed['branches']} branch(es) "
                      f"to the per-day shape, rewrote {fixed['articles']} stale KB "
                      "article(s)")
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print("[startup] opening-hours backfill skipped:", exc)
    try:
        from app.seed import backfill_promotion_branches

        db = SessionLocal()
        try:
            moved = backfill_promotion_branches(db)
            if moved:
                print(f"[startup] moved {moved} promotion(s) onto the branch join table")
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print("[startup] promotion-branch backfill skipped:", exc)
    try:
        from app.seed import backfill_clinic_logo

        db = SessionLocal()
        try:
            swapped = backfill_clinic_logo(db)
            if swapped:
                print(f"[startup] moved {swapped} clinic(s) onto the new seeded logo")
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print("[startup] clinic-logo backfill skipped:", exc)
    try:
        from app.seed import backfill_owner_email

        db = SessionLocal()
        try:
            if backfill_owner_email(db):
                print("[startup] owner login moved to the new demo address")
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print("[startup] owner-email backfill skipped:", exc)
    try:
        from app.seed import backfill_payment_faq

        db = SessionLocal()
        try:
            clinics = backfill_payment_faq(db)
        finally:
            db.close()
        if clinics:
            from app.routers.clinics import _index_clinic_kb
            print(f"[startup] payment FAQ now describes the QR in clinic(s) {clinics}; reindexing")
            for cid in clinics:   # the AI answers from the index, not the article row
                threading.Thread(target=_index_clinic_kb, args=(cid,), daemon=True).start()
    except Exception as exc:  # pragma: no cover
        print("[startup] payment-FAQ backfill skipped:", exc)
    if fresh_db:   # polish the seeded demo data ONCE; never auto-assign a stock
        try:       # portrait to real team members created later (they show initials)
            from app.avatars import backfill_avatars

            db = SessionLocal()
            try:
                filled = backfill_avatars(db)
                if filled:
                    print(f"[startup] backfilled {filled} avatars")
            finally:
                db.close()
        except Exception as exc:  # pragma: no cover
            print("[startup] avatar backfill skipped:", exc)
    try:
        from app.seed import cleanup_orphan_payments

        db = SessionLocal()
        try:
            removed = cleanup_orphan_payments(db)
            if removed:
                print(f"[startup] removed {removed} orphaned payment(s)")
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print("[startup] orphan payment cleanup skipped:", exc)
    threading.Thread(target=_index_kb_background, daemon=True).start()
    try:
        from app.services.scheduler import start_scheduler

        start_scheduler()
    except Exception as exc:  # pragma: no cover
        print("[startup] scheduler skipped:", exc)
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Keep app code/markup fresh so edits always reach the browser.

    App code (JS/CSS) and HTML entry points are sent ``no-store`` — never cached.
    Plain ``no-cache`` proved insufficient: some browsers (notably Brave) serve a
    cached ES module without revalidating, which left the workspace picker stuck on
    a stale build. Images keep ``no-cache`` (revalidated, not re-downloaded).
    """
    response = await call_next(request)
    path = request.url.path
    if (path.startswith(("/js/", "/css/"))
            or path in ("/", "/admin", "/home", "/portal")):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    elif path.startswith(("/assets/", "/chat")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/api/health")
def health() -> dict:
    """Liveness + the server's own clock.

    The clock is here because a skewed host silently corrupts everything time-based:
    availability drops slots that are still hours away, promotions expire early, the
    no-show sweep fires on live bookings. Compare `clinic_time` against a phone in
    Bangkok — if they disagree, fix the host clock before debugging anything else.
    """
    from app.services.booking import _now_local

    return {"status": "ok", "app": settings.app_name,
            "utc": datetime.utcnow().isoformat(timespec="seconds"),
            "clinic_time": _now_local().isoformat(timespec="seconds"),
            "timezone": settings.timezone}


app.include_router(auth.router)
app.include_router(clinics.router)
app.include_router(admin.router)
app.include_router(catalog.router)
app.include_router(knowledge.router)
app.include_router(conversations.router)
app.include_router(channels.router)
app.include_router(bookings.router)
app.include_router(calendar.router)
app.include_router(payments.router)
app.include_router(customers.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(retention.router)
app.include_router(broadcast.router)
app.include_router(testconsole.router)
app.include_router(portal.router)

app.mount("/css", StaticFiles(directory=WEB_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=WEB_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.get("/")
def index() -> FileResponse:
    """The public landing page. The STAFF app lives at /admin.

    A customer who types the bare domain is the common case, so the root is the
    clinic's shop window; the console is one path deeper. Anything under /admin
    still falls through to the SPA shell below, so its hash routes keep working.
    """
    return FileResponse(WEB_DIR / "home.html")


@app.get("/{full_path:path}")
def spa(full_path: str):
    """Serve standalone public pages and the SPA shell for client-side routes."""
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    # the web-chat widget is clinic-specific: /chat or /chat/<clinic-slug>
    if full_path == "chat" or full_path.startswith("chat/"):
        return FileResponse(WEB_DIR / "chat.html")
    # the customer portal: /portal (login + dashboard), clinic-specific like the widget
    if full_path == "portal" or full_path.startswith("portal/"):
        return FileResponse(WEB_DIR / "portal.html")
    if full_path in PUBLIC_PAGES:
        page = WEB_DIR / f"{full_path}.html"
        if page.exists():
            return FileResponse(page)
    # /admin and everything under it is the staff SPA shell (its own hash router
    # takes it from there); so is any other unmatched path, as before.
    return FileResponse(WEB_DIR / "index.html")
