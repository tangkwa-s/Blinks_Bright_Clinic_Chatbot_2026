"""External calendar (ICS/webcal) sync — pulls each doctor's busy blocks from their own
pasted calendar URL into ``ExternalBusyBlock``, so booking availability can treat time
they've blocked out elsewhere (personal appointments, leave, another clinic's schedule)
as unavailable too.

Runs on a schedule (``app/services/scheduler.py``) and on demand via the admin "sync
now" action (``app/routers/catalog.py``'s ``/team-members/{id}/sync-calendar``). NEVER
called from inside ``booking.claim_slot``/``day_availability`` — those read the
already-synced local table only, so the per-clinic lock in ``claim_slot`` never waits
on a network call. See booking.py's "Holding a slot" notes for why that lock must stay
network-free.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events

from app import models
from app.config import settings
from app.database import SessionLocal
from app.scope import scoped

SYNC_WINDOW_DAYS = 90   # forward-looking window, re-rolled every sync tick — see
                        # CLAUDE.md-style tradeoff note in the plan: trades same-day
                        # freshness / bookable-again lag against fetch volume.
MAX_ICS_BYTES = 5_000_000
FETCH_TIMEOUT = 15.0

try:
    _LOCAL_TZ = ZoneInfo(settings.timezone)
except Exception:  # pragma: no cover
    _LOCAL_TZ = ZoneInfo("Asia/Bangkok")


def _now_local() -> datetime:
    """Naive Bangkok wall-clock — same convention as booking.py's own helper, kept as
    a separate copy so this module has no import-time dependency on booking.py."""
    return datetime.now(_LOCAL_TZ).replace(tzinfo=None)


def _fetch_ics(url: str, timeout: float = FETCH_TIMEOUT) -> str:
    """Download the calendar text. ``webcal://`` is just a hint to calendar apps to
    subscribe rather than download — the bytes at the same host are identical over
    ``https://``, so normalise before fetching (httpx has no webcal:// support)."""
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "blinks-bright-calendar-sync/1.0"})
    resp.raise_for_status()
    if len(resp.content) > MAX_ICS_BYTES:
        raise ValueError(f"calendar feed too large ({len(resp.content)} bytes)")
    return resp.text


def _to_local(value) -> datetime:
    """Convert an icalendar DTSTART/DTEND value to naive Bangkok wall-clock, matching
    Booking.slot_at's storage convention. ``datetime.datetime`` is a subclass of
    ``datetime.date``, so the datetime check MUST come first or every timed event
    would be misread as an all-day one."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(_LOCAL_TZ).replace(tzinfo=None)
        return value   # floating time (no TZID/Z in the source) — treat as already local
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)   # all-day -> local midnight
    raise TypeError(f"unexpected ICS date value: {value!r}")


def _parse_busy_blocks(ics_text: str, window_start: datetime,
                       window_end: datetime) -> list[tuple[datetime, datetime, str]]:
    """Expand every VEVENT — including recurring ones (RRULE/RDATE, with EXDATE and
    RECURRENCE-ID overrides applied) — that falls inside [window_start, window_end)
    into (start_local, end_local, uid) triples. Cancelled and zero/negative-duration
    occurrences are dropped; they were never real busy time."""
    cal = icalendar.Calendar.from_ical(ics_text)
    occurrences = recurring_ical_events.of(cal).between(window_start, window_end)
    out = []
    for ev in occurrences:
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start = _to_local(ev["DTSTART"].dt)
        end_prop = ev.get("DTEND")
        end = _to_local(end_prop.dt) if end_prop else start
        if end <= start:
            continue
        out.append((start, end, str(ev.get("UID", ""))))
    return out


def sync_staff_calendar(db, staff: models.StaffMember, now: datetime | None = None) -> bool:
    """Sync one doctor's external calendar. Returns True on success (including the
    no-op case of no URL configured), False on failure. NEVER raises past this
    function — every failure path is caught and recorded on the StaffMember row so a
    bad feed shows up as a fact ("last error: ...") rather than a crashed job.

    Fail-safe rule: on failure, existing ExternalBusyBlock rows for this staff member
    are left completely untouched — never cleared. Clearing them would silently widen
    availability into time the doctor's own calendar says is taken, which is the worse
    failure mode; this codebase already treats "stay conservative, say it honestly" as
    the default elsewhere (confirm_paid_booking never assumes a slot is free, hold
    expiry is always spoken out loud) and this mirrors it.
    """
    if not staff.ics_url:
        return True
    now = now or _now_local()
    try:
        ics_text = _fetch_ics(staff.ics_url)
        blocks = _parse_busy_blocks(ics_text, now, now + timedelta(days=SYNC_WINDOW_DAYS))
    except Exception as exc:
        staff.ics_last_error = str(exc)[:255]
        staff.ics_last_error_at = datetime.utcnow()
        db.commit()
        return False

    (scoped(db, models.ExternalBusyBlock, staff.clinic_id)
     .filter(models.ExternalBusyBlock.staff_id == staff.id)
     .delete(synchronize_session=False))
    for start, end, uid in blocks:
        db.add(models.ExternalBusyBlock(clinic_id=staff.clinic_id, staff_id=staff.id,
                                        starts_at=start, ends_at=end, uid=uid))
    staff.ics_last_synced_at = datetime.utcnow()
    staff.ics_last_error = ""
    staff.ics_last_error_at = None
    db.commit()
    return True


def sync_all_staff_calendars(now: datetime | None = None) -> dict:
    """Background job (app/services/scheduler.py, every settings.calendar_sync_minutes)
    — sync every configured doctor across every active clinic. Own session, mirroring
    sweep_all_expired_holds. Each STAFF MEMBER gets its own try/except + rollback —
    finer-grained than automations.py's per-clinic pattern, because one doctor's
    malformed/unreachable feed must not break a clinic-mate's sync, let alone another
    clinic's entirely.
    """
    db = SessionLocal()
    synced = failed = 0
    try:
        for clinic in db.query(models.Clinic).filter_by(status="active").all():
            roster = (scoped(db, models.StaffMember, clinic.id)
                     .filter(models.StaffMember.ics_url != "").all())
            for staff in roster:
                try:
                    if sync_staff_calendar(db, staff, now=now):
                        synced += 1
                    else:
                        failed += 1
                except Exception as exc:  # pragma: no cover
                    db.rollback()
                    failed += 1
                    print(f"[calendar-sync] staff={staff.id} unexpected error: {exc}")
        if synced or failed:
            print(f"[calendar-sync] synced={synced} failed={failed}")
        return {"synced": synced, "failed": failed}
    finally:
        db.close()
