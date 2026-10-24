"""Background scheduler (APScheduler) — every periodic job the app runs.

Each job is registered ON ITS OWN. A missing optional dependency or a broken module
must cost that one job, never the scheduler: when calendar_sync gained ``icalendar``
and the server was restarted without ``pip install -r requirements.txt``, the single
import error at the top of this function took the hold-expiry sweep and the retention
reminders down with it — silently, because main.py's try/except turned it into one
``[startup] scheduler skipped`` line while the site kept serving 200s for hours. The
job table below resolves each import at registration time, and a skipped job is
reported loudly, with the fix, on its own line.
"""
import importlib

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings

_scheduler: BackgroundScheduler | None = None
_status: dict | None = None

FIX_HINT = "fix: .venv/bin/pip install -r requirements.txt, then restart the service"


def _jobs() -> list[tuple[str, str, dict, str]]:
    """``(job id, "module:function", add_job kwargs, description)`` for every job.

    Targets are strings, not imported callables, so one module that fails to import
    cannot poison the others — the import happens per job inside start_scheduler.
    """
    cal_minutes = max(1, settings.calendar_sync_minutes)
    takeover_minutes = max(1, settings.takeover_timeout_minutes)
    return [
        ("retention-automations", "app.services.automations:run_automations",
         {"minutes": 30},
         "retention automations every 30 minutes"),
        # A hold is a 10-minute promise ("ไม่ชำระภายใน 10 นาที ระบบจะปล่อยคิว"), so the
        # sweep that makes it come true — status → expired, customer told — cannot ride
        # the 30-minute job. The slot itself frees at read time regardless
        # (day_availability); this narrows the cancel-and-notify lag to ~10 seconds.
        # models.py's ix_bookings_hold_expires_at index is what keeps that cheap at this
        # cadence regardless of how many bookings a clinic has accumulated over time.
        ("hold-expiry-sweep", "app.services.automations:sweep_all_expired_holds",
         {"seconds": 10, "coalesce": True, "max_instances": 1},
         "hold-expiry sweep every 10 seconds"),
        # The one proactive warning before the slot goes that does not depend on the
        # pay-card's live countdown being on screen — and unlike the other sweeps here, a
        # slow tick doesn't just delay this one, it makes its own claim ("about 2
        # minutes left") wrong by the time it arrives. 10 seconds, under
        # booking.HOLD_REMINDER_SWEEP_BUFFER_SECONDS (20) so every tick can still catch
        # a booking within that window before the NEXT tick would have to.
        ("hold-reminder-sweep", "app.services.automations:sweep_all_hold_reminders",
         {"seconds": 10, "coalesce": True, "max_instances": 1},
         "hold-reminder sweep every 10 seconds"),
        # Pulls each doctor's external calendar (ICS/webcal) into ExternalBusyBlock —
        # day_availability reads that table, never the URL itself, so this job is the
        # ONLY place a live fetch happens on the schedule (the other is the admin's
        # on-demand "sync now"). coalesce/max_instances=1 for the same reason as the
        # hold sweep: a slow tick should coalesce into the next, never pile up
        # concurrent fetches against the same doctor's feed. Needs the optional
        # ``icalendar`` + ``recurring-ical-events`` packages.
        ("calendar-sync", "app.services.calendar_sync:sync_all_staff_calendars",
         {"minutes": cal_minutes, "coalesce": True, "max_instances": 1},
         f"calendar sync every {cal_minutes} minutes"),
        # Same 60-second cadence as the hold sweep, and for the same reason: a
        # 15-minute "the AI will pick this back up" promise can't lag behind a slow job.
        ("takeover-timeout-sweep", "app.services.automations:sweep_all_stale_takeovers",
         {"seconds": 60, "coalesce": True, "max_instances": 1},
         f"takeover-timeout sweep every 60 seconds ({takeover_minutes} min timeout)"),
    ]


def _resolve(target: str):
    module, _, func = target.partition(":")
    return getattr(importlib.import_module(module), func)


def start_scheduler() -> dict:
    """Start every periodic job that can be started (idempotent).

    Returns ``{"registered": [job ids], "skipped": {job id: "ExcType: why"}}`` — the
    same dict on every later call — so a test (or an ops check) can see exactly which
    jobs are alive. The scheduler starts even when some jobs are skipped: the jobs that
    did register are worth more than a clean all-or-nothing.
    """
    global _scheduler, _status
    if _scheduler is not None:
        return _status or {"registered": [], "skipped": {}}

    sched = BackgroundScheduler(daemon=True)
    registered, described, skipped = [], [], {}
    for job_id, target, opts, desc in _jobs():
        try:
            sched.add_job(_resolve(target), "interval", id=job_id,
                          replace_existing=True, **opts)
        except Exception as exc:
            # Missing package, broken module, bad trigger value: this job only.
            skipped[job_id] = f"{type(exc).__name__}: {exc}"
            continue
        registered.append(job_id)
        described.append(desc)

    sched.start()
    _scheduler = sched
    _status = {"registered": registered, "skipped": skipped}
    print("[scheduler] " + ("; ".join(described) if described else "NO jobs registered"))
    for job_id, why in skipped.items():
        # One loud line per job, not one quiet line for the whole scheduler.
        print(f"[scheduler] JOB SKIPPED — {job_id}: {why} ({FIX_HINT})")
    return _status
