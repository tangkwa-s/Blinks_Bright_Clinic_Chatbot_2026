"""Booking availability and creation — used by the AI tools and the bookings API."""
import calendar
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import models, realtime
from app.config import settings
from app.scope import scoped
from app.services.promotions import (exhausted_promo_ids, promo_branch_ids,
                                     promo_runs_at)

SLOT_MINUTES = 30  # appointment grid; a branch's open/close can be any 15-min time
NO_SHOW_GRACE_HOURS = 2  # a pending booking this long past its slot becomes a no-show
# An unpaid AI booking holds its slot this long, then the slot is released (default 10,
# .env HOLD_MINUTES). A bank transfer can land after the hold (and staff confirm the slip
# later still) — which is safe, not sloppy: a payment landing after the deadline goes
# through confirm_paid_booking,
# which reinstates the booking while the slot is still free and escalates to a human
# (money kept, said out loud) once it is gone. max(1, …) because 0 would silently switch
# holds off and bring back the abandoned-checkout-blocks-the-slot-for-weeks bug.
HOLD_MINUTES = max(1, settings.hold_minutes)
# Ceiling for a clinic/service hold_minutes override (see resolved_hold_minutes below).
# 3 hours: past this a "hold" stops meaning "reserved briefly while paying" and starts
# meaning "booked" in every practical sense.
MAX_HOLD_MINUTES = 180
# How close to the hold deadline sweep_hold_reminders nudges the customer: a message in
# the thread, the one warning that does not depend on the pay-card's live countdown
# being on screen. Deliberately a plain constant, not .env-tunable:
# unlike HOLD_MINUTES this isn't a business policy someone needs to retune per clinic.
HOLD_REMINDER_MINUTES = 2
# How far PAST the HOLD_REMINDER_MINUTES mark a booking is still allowed to be caught.
# The sweep's own tick interval (scheduler.py) is what actually bounds how late a catch
# can be, but this must be >= that interval or a booking's eligible instant can fall
# between two ticks and be missed by both — this buffer is that safety margin, not a
# second source of truth for the interval. Widening the reminder's own window (see
# sweep_hold_reminders) rather than shortening the wait was a decision, not the only
# fix: the same story played out twice — first the message text lagged reality (fixed
# by reading the real remaining time instead of a flat constant), then the SEND itself
# was seen firing with only ~1:30 left rather than ~2:00, because catching the window
# only AFTER a booking had already dropped below HOLD_REMINDER_MINUTES means a slow
# poll tick reports a number that was already stale the moment it arrived. Catching it
# on the way IN — while still >= HOLD_REMINDER_MINUTES — makes "about 2 minutes" true
# at send time instead of true only at the instant the row became eligible. 20 seconds
# is 2x the sweep's own 10-second interval (scheduler.py) — comfortable margin against
# tick jitter without widening the guaranteed range ([2:00, 2:20]) more than it has to.
HOLD_REMINDER_SWEEP_BUFFER_SECONDS = 20
EXPIRED = "expired"  # the unpaid hold ran out and the slot went back on the menu
BOOKING_STATUSES = ("pending", "confirmed", "completed", "cancelled", "no_show", EXPIRED)
_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

try:
    _LOCAL_TZ = ZoneInfo(settings.timezone)
except Exception:  # pragma: no cover
    _LOCAL_TZ = ZoneInfo("Asia/Bangkok")


def _now_local() -> datetime:
    """Current wall-clock in the clinic timezone (naive). Branch hours and booking
    slots are expressed in this local time, so 'now' must be too — a UTC 'now' would
    hide slots that are still hours away in Bangkok."""
    return datetime.now(_LOCAL_TZ).replace(tzinfo=None)


def _expire_if_still_pending(db, booking_id: int) -> int:
    """Compare-and-set pending → expired. Returns 1 iff THIS call flipped the row.

    The 60-second scheduler job, the bookings-list lazy sweep and generate_ai_reply's
    sweep can all run inside the same second — three threads, three sessions, each of
    which may have SELECTed the row as ``pending`` a beat before the others committed.
    Whoever actually flips the row owns its side effects (the Activity, the reminder
    cancellation, telling the customer); everyone else finds nothing to flip and stays
    silent, so the customer can never be told "หมดเวลาถือคิว" twice. Same pattern as
    mark_paid's atomic conditional UPDATE. ``hold_expires_at`` is deliberately KEPT: on
    a non-pending row it is no longer a deadline, it is the record of when it lapsed.
    """
    return (db.query(models.Booking)
            .filter(models.Booking.id == booking_id,
                    models.Booking.status == "pending")
            .update({models.Booking.status: EXPIRED}, synchronize_session=False))


def sweep_expired_holds(db, clinic_id: int, now: datetime | None = None) -> int:
    """Mark one clinic's PENDING bookings whose unpaid hold has lapsed as ``expired``
    (an Activity per transition, scheduled reminders cancelled, the customer told).

    The slot itself is already free — day_availability drops a lapsed hold at read time,
    so this sweep is NOT what releases it. What it does is make every OTHER reader agree:
    the reminder generator, the ICS feed, create_payment_link's live set, the AI's memory
    and the bookings list all key off ``status``, and until this runs they still see a live
    booking. It also owns the one thing a lazy read cannot do — telling the customer.

    Runs BEFORE sweep_no_shows (see run_automations): a hold that lapsed and is now also
    hours past its slot is an EXPIRY, not a no-show. "No-show" says the customer failed to
    turn up; they never had an appointment to turn up to.

    hold_expires_at is naive Bangkok wall-clock -> compare against _now_local, not UTC.
    """
    now = now or _now_local()
    rows = (scoped(db, models.Booking, clinic_id)
            .filter(models.Booking.status == "pending",
                    models.Booking.hold_expires_at.isnot(None),
                    models.Booking.hold_expires_at <= now).all())
    if not rows:
        return 0

    # Belt and braces: confirm_paid_booking clears the hold, so a PAID booking should never
    # be in this set. If one is, the payment cascade half-ran — repair it rather than
    # expiring a slot somebody has paid for. Scoped to just these ids, so the lazy call
    # sites stay cheap.
    paid = {pid for (pid,) in
            db.query(models.Payment.booking_id)
            .filter(models.Payment.booking_id.in_([b.id for b in rows]),
                    models.Payment.clinic_id == clinic_id,
                    models.Payment.status == "paid").all()}

    expired = []
    for b in rows:
        if b.id in paid:
            # Conditional for the same reason as the expiry flip below: if mark_paid's
            # cascade confirmed it (or another sweep expired it) since our SELECT, the
            # caller with more information has already acted — repair nothing on top.
            (db.query(models.Booking)
             .filter(models.Booking.id == b.id, models.Booking.status == "pending")
             .update({models.Booking.status: "confirmed",
                      models.Booking.hold_expires_at: None}, synchronize_session=False))
            continue
        if not _expire_if_still_pending(db, b.id):
            continue   # a concurrent sweep (or confirm_paid_booking) beat us to this row
        svc = db.get(models.Service, b.service_id) if b.service_id else None
        db.add(models.Activity(
            clinic_id=clinic_id, customer_id=b.customer_id, type="booking",
            summary=(f"Hold expired — {svc.name if svc else 'treatment'} "
                     f"on {b.slot_at:%d %b %H:%M} unpaid, slot released"),
            ref_type="booking", ref_id=b.id,
        ))
        # A reminder already written for a booking that no longer holds anything would tell
        # the customer "พรุ่งนี้คุณมีนัด…" for an appointment they lost. generate_reminders
        # stops making NEW ones (its filter is pending|confirmed); the rows already
        # scheduled are this sweep's to close.
        (scoped(db, models.Reminder, clinic_id)
         .filter(models.Reminder.booking_id == b.id,
                 models.Reminder.status == "scheduled")
         .update({models.Reminder.status: "cancelled"}, synchronize_session=False))
        expired.append(b)

    db.commit()
    for b in expired:
        realtime.publish({"type": "booking", "booking_id": b.id, "clinic_id": clinic_id})
    # After the commit, and outside it: the notice is delivered through the channel adapter
    # and must never hold a write transaction open across it.
    from app.services.inbox import notify_hold_expired

    for b in expired:
        try:
            notify_hold_expired(db, b)
        except Exception as exc:  # pragma: no cover
            print("[booking] hold-expiry notify error:", exc)
    return len(expired)


def sweep_hold_reminders(db, clinic_id: int, now: datetime | None = None) -> int:
    """Nudge one clinic's customers whose unpaid hold is about to lapse
    (HOLD_REMINDER_MINUTES out), so a web customer who has simply looked away from
    the pay-card's live countdown gets one proactive warning before the
    slot is gone, not just the one-time deadline mentioned when they first booked.

    Catches a booking on the way IN to "about HOLD_REMINDER_MINUTES left" — while
    remaining is still >= HOLD_REMINDER_MINUTES, in the HOLD_REMINDER_SWEEP_BUFFER_SECONDS
    right after it crosses that mark — not after it has already dropped below. Catching
    it only after meant a slow poll tick could report "about 2 minutes" when the real
    number, by the time the message actually sent, was closer to 1:30: true the instant
    the row became eligible, stale by the time anyone read it. Catching it on the way in
    keeps the claim true at send time instead.

    hold_reminder_sent_at makes this idempotent across ticks — a row could otherwise sit
    inside this (now widened) window across more than one tick and be nudged twice.
    """
    now = now or _now_local()
    window_start = now + timedelta(minutes=HOLD_REMINDER_MINUTES)
    window_end = window_start + timedelta(seconds=HOLD_REMINDER_SWEEP_BUFFER_SECONDS)
    rows = (scoped(db, models.Booking, clinic_id)
           .filter(models.Booking.status == "pending",
                   models.Booking.hold_expires_at.isnot(None),
                   models.Booking.hold_expires_at >= window_start,
                   models.Booking.hold_expires_at <= window_end,
                   models.Booking.hold_reminder_sent_at.is_(None)).all())
    if not rows:
        return 0
    for b in rows:
        b.hold_reminder_sent_at = datetime.utcnow()
    db.commit()
    # Outside the transaction, same reasoning as sweep_expired_holds above: the notice
    # goes through the channel adapter.
    from app.services.inbox import notify_hold_reminder

    for b in rows:
        try:
            # The ACTUAL time left, not the flat window width: a booking can enter the
            # window anywhere from just under HOLD_REMINDER_MINUTES down to just over 0
            # (the sweep only ticks every 60s against a 2-minute-wide window). Rounded to
            # the NEAREST minute, not up: ceil() said "2 minutes" for 1:12 left, which
            # read as wrong next to a customer comparing two clock times they can also
            # see (now 18:18, expires 18:19 — a 1-minute gap by the numbers in front of
            # them). max(1, …) still keeps it off "0 minutes" while the hold is live.
            # Same `now` the query above ran against — one clock for the whole sweep.
            remaining_min = max(1, round((b.hold_expires_at - now).total_seconds() / 60))
            notify_hold_reminder(db, b, minutes_left=remaining_min)
        except Exception as exc:  # pragma: no cover
            print("[booking] hold-reminder notify error:", exc)
    return len(rows)


def sweep_no_shows(db, clinic_id: int, now: datetime | None = None) -> int:
    """Mark one clinic's PENDING bookings whose slot passed more than
    NO_SHOW_GRACE_HOURS ago as ``no_show`` (with an Activity per transition).

    Only 'pending' transitions — past CONFIRMED bookings are deliberately left
    for staff to mark completed/no_show manually. Runs from the 30-min
    automations job AND lazily on the bookings list, so it must stay a cheap
    indexed query and commit only when something actually changed.
    slot_at is naive Bangkok wall-clock → compare against _now_local, not UTC.
    """
    cutoff = (now or _now_local()) - timedelta(hours=NO_SHOW_GRACE_HOURS)
    rows = (scoped(db, models.Booking, clinic_id)
            .filter(models.Booking.status == "pending",
                    models.Booking.slot_at < cutoff).all())
    if not rows:
        return 0
    flipped = []
    for b in rows:
        # Compare-and-set like the hold sweep: the 30-min job and two admin tabs on the
        # bookings list can sweep at once, and only one may write the Activity.
        n = (db.query(models.Booking)
             .filter(models.Booking.id == b.id, models.Booking.status == "pending")
             .update({models.Booking.status: "no_show"}, synchronize_session=False))
        if not n:
            continue
        svc = db.get(models.Service, b.service_id) if b.service_id else None
        db.add(models.Activity(
            clinic_id=clinic_id, customer_id=b.customer_id, type="booking",
            summary=(f"No-show — {svc.name if svc else 'treatment'} "
                     f"on {b.slot_at:%d %b %H:%M} (auto-marked)"),
            ref_type="booking", ref_id=b.id,
        ))
        flipped.append(b)
    db.commit()
    for b in flipped:
        realtime.publish({"type": "booking", "booking_id": b.id, "clinic_id": clinic_id})
    return len(flipped)


def _to_minutes(hhmm, default: int) -> int:
    """'HH:MM' (or '24:00') -> minutes since midnight; `default` on bad input."""
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return default


def branch_days(branch) -> dict | None:
    """This branch's seven days as ``{day: {open, close, closed}}``, or None when it
    stores no schedule at all.

    Understands BOTH shapes the column holds: the current per-day JSON, and the legacy
    ``{"weekday": "10:00-20:00", "weekend": "10:00-19:00"}`` that every seeded clinic
    still carries. Only the Settings card ever read that legacy pair, so everything
    else silently fell through to the flat open_hour/close_hour — the AI answered
    "10:00-20:00 daily" for a branch that shuts at 19:00 on weekends, and availability
    offered a 19:30 Saturday slot at a closed clinic. One parser, so a schedule cannot
    mean two different things again.
    """
    raw = branch.hours
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw else {}
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        return None
    days = raw.get("days")
    if days:
        return {d: (days.get(d) or {}) for d in _DOW}

    weekday, weekend = raw.get("weekday"), raw.get("weekend")
    if not (weekday or weekend):
        return None
    flat = {"open": f"{branch.open_hour:02d}:00", "close": f"{branch.close_hour:02d}:00"}

    def _split(v):
        try:
            o, c = str(v).split("-")
            return {"open": o.strip(), "close": c.strip()}
        except Exception:
            return dict(flat)

    wk = _split(weekday) if weekday else dict(flat)
    we = _split(weekend) if weekend else dict(wk)
    return {d: dict(we if d in ("sat", "sun") else wk) for d in _DOW}


def _day_window(branch, day: datetime):
    """(open_min, close_min) for this weekday, or None when the branch is closed.

    Reads whatever schedule the branch stores (see ``branch_days``). Supports any time
    and a full 24-hour day (00:00 to 24:00), falling back to the flat
    open_hour / close_hour only when no schedule is stored at all.
    """
    days = branch_days(branch)
    if days:
        d = days.get(_DOW[day.weekday()])
        if d is not None:
            if d.get("closed"):
                return None
            o = _to_minutes(d.get("open"), branch.open_hour * 60)
            c = _to_minutes(d.get("close"), branch.close_hour * 60)
            return (o, c) if c > o else None
    o, c = branch.open_hour * 60, branch.close_hour * 60
    return (o, c) if c > o else None


def _add_months(dt: datetime, n: int) -> datetime:
    """``dt`` shifted ``n`` calendar months, clamping the day-of-month
    (Jan 31 + 1 month -> Feb 28/29) — used for course/bundle series."""
    total = (dt.year * 12 + dt.month - 1) + n
    year, month = divmod(total, 12)
    month += 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# Why a day has NO free slots — day_availability returns one of these so the AI can
# state the real reason instead of inventing one (it once told a customer 10:30 "had
# already passed" at 00:02 on the day itself; the branch was simply shut on Saturdays).
CLOSED = "closed"                  # the branch does not open at all that weekday
PAST = "past"                      # every slot of the day is already earlier than now
FULLY_BOOKED = "fully_booked"      # every slot is taken by another booking
BOOKED_OR_PAST = "booked_or_past"  # what is left is a mix of taken and already-gone


def _duration_of(db, booking) -> int:
    """How many minutes a booking actually occupies (its treatment's duration)."""
    svc = db.get(models.Service, booking.service_id) if booking.service_id else None
    return max(int(getattr(svc, "duration_min", 0) or 0), SLOT_MINUTES) if svc else SLOT_MINUTES


def day_availability(db, branch_id: int, day: datetime, service_id=None,
                     doctor_id=None, exclude_booking_id=None):
    """``(free_slots, reason, window)`` for one branch-day — see available_slots.

    ``reason`` is ``""`` while free slots remain, otherwise one of CLOSED / PAST /
    FULLY_BOOKED / BOOKED_OR_PAST. ``window`` is the day's (open_min, close_min), or
    None when the branch is shut. Callers that only need the slots use available_slots.
    """
    branch = db.get(models.Branch, branch_id)
    if not branch:
        return [], CLOSED, None
    window = _day_window(branch, day)
    if not window:
        return [], CLOSED, None
    open_min, close_min = window

    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    # ONE `now` for the whole function: the hold test below and the "already gone" test
    # further down must agree. Two _now_local() calls is two answers to what time it is,
    # and across a second boundary they disagree.
    now = _now_local()
    busy = (db.query(models.Booking)
            .filter(models.Booking.slot_at >= day_start,
                    models.Booking.slot_at < day_end,
                    models.Booking.status.in_(["pending", "confirmed"]),
                    # A hold that has LAPSED stops blocking here, at READ time, without
                    # waiting for sweep_expired_holds (a 60-second job plus lazy call
                    # sites). A customer asking 31 seconds after a hold ran out must see
                    # the slot, so availability cannot be a function of when a job last
                    # ran. This is the ONLY place that decision is made — every booking,
                    # reschedule, series session and AI tool funnels through here.
                    # NULL = no hold = still blocks (admin bookings, paid bookings, and
                    # every row written before the column existed).
                    (models.Booking.hold_expires_at.is_(None))
                    | (models.Booking.hold_expires_at > now)))
    if doctor_id:
        # branch capacity OR the chosen doctor busy anywhere in the clinic
        busy = busy.filter((models.Booking.branch_id == branch_id)
                           | ((models.Booking.doctor_id == doctor_id)
                              & (models.Booking.clinic_id == branch.clinic_id)))
    else:
        busy = busy.filter(models.Booking.branch_id == branch_id)
    if exclude_booking_id:
        busy = busy.filter(models.Booking.id != exclude_booking_id)
    # A booking occupies its treatment's whole DURATION, not just the minute it starts.
    # Blocking only the start time let a 50-minute treatment be booked into the middle
    # of a 40-minute one — same branch, sometimes the same customer, who would then have
    # had to be in two chairs at once.
    taken = [(b.slot_at.replace(second=0, microsecond=0), _duration_of(db, b))
             for b in busy.all()]
    if doctor_id:
        # Busy blocks synced from the doctor's OWN external calendar (leave, personal
        # appointments — anything not in our booking system). Pure local-DB read: the
        # ICS URL itself is fetched only by the background sync job
        # (app/services/calendar_sync.py), never here, so this adds no network I/O to
        # claim_slot's lock path. Same scope boundary as the doctor-conflict clause
        # above: only applies once a doctor IS pinned. Overlap, not "starts within the
        # day" — an external calendar can carry a multi-day all-day block (e.g. leave),
        # unlike a Booking whose duration is one treatment's length.
        ext = (scoped(db, models.ExternalBusyBlock, branch.clinic_id)
              .filter(models.ExternalBusyBlock.staff_id == doctor_id,
                      models.ExternalBusyBlock.starts_at < day_end,
                      models.ExternalBusyBlock.ends_at > day_start)
              .all())
        taken += [(e.starts_at, max(int((e.ends_at - e.starts_at).total_seconds() // 60), 1))
                 for e in ext]
    want = SLOT_MINUTES
    if service_id:
        svc = db.get(models.Service, service_id)
        want = max(int(getattr(svc, "duration_min", 0) or 0), SLOT_MINUTES) if svc else want

    slots, gone, booked = [], 0, 0
    t = open_min
    while t < close_min:
        slot = day_start + timedelta(minutes=t)
        ends = slot + timedelta(minutes=want)
        clashes = any(slot < start + timedelta(minutes=mins) and start < ends
                      for start, mins in taken)
        # The treatment must also FINISH before the branch closes — a 50-minute
        # treatment cannot start 20 minutes before the shutters come down.
        if clashes or (service_id and t + want > close_min):
            booked += 1
        elif slot <= now:
            gone += 1
        else:
            slots.append(slot)
        t += SLOT_MINUTES
    if slots:
        return slots, "", window
    if booked and gone:
        return [], BOOKED_OR_PAST, window
    if booked:
        return [], FULLY_BOOKED, window
    if gone:
        return [], PAST, window
    return [], CLOSED, window     # an empty grid: open/close leave no slot at all


def available_slots(db, branch_id: int, day: datetime, service_id=None,
                    doctor_id=None, exclude_booking_id=None) -> list[datetime]:
    """Free appointment slots for a branch on a day, honouring its open/close hours
    (per-day, minute-precise, up to 24h) and stepping every SLOT_MINUTES.

    ``doctor_id`` additionally blocks slots where that doctor already has a
    non-cancelled booking that day at ANY branch of the clinic. ``exclude_booking_id``
    ignores one booking (so a reschedule doesn't collide with its own slot)."""
    return day_availability(db, branch_id, day, service_id, doctor_id,
                            exclude_booking_id)[0]


# ---------------------------------------------------------------------------
#  Taking a slot: the check and the write, serialised
# ---------------------------------------------------------------------------
SLOT_TAKEN = "slot_taken"   # free when we looked, gone by the time we re-looked

# One re-entrant lock per CLINIC. Per clinic rather than per branch because the doctor
# conflict in day_availability spans every branch of a clinic — a per-branch lock would
# let one doctor be booked at two branches at the same minute. Per clinic rather than
# global so a busy tenant cannot stall another. Re-entrant so the course/bundle loop can
# hold it across several claims without deadlocking on itself.
_claim_locks: dict[int, threading.RLock] = {}
_claim_locks_guard = threading.Lock()
_claim_depth = threading.local()


def _claim_lock(clinic_id: int) -> threading.RLock:
    with _claim_locks_guard:
        lock = _claim_locks.get(clinic_id)
        if lock is None:
            lock = _claim_locks[clinic_id] = threading.RLock()
        return lock


@contextmanager
def claim_lock(clinic_id: int, db=None):
    """Hold one clinic's slot-claim lock across SEVERAL claims — a course/bundle series —
    so the whole series is decided against one view of the diary and committed once by the
    caller. Yields True when this is the outermost holder in this thread; ``claim_slot``
    uses that to know whether the commits are its own to make.

    **Pass ``db``.** Acquiring the lock commits the caller's session, which is about
    SQLite's locking, not tidiness. Measured on this setup: a SELECT-only session holds
    nothing (pysqlite's legacy isolation only emits BEGIN before DML, so reads are
    autocommitted and always see the latest committed row — no stale snapshot to worry
    about). But a session with UNCOMMITTED DML holds a write lock on the whole file, and
    every other connection that tries to commit while the claim runs gets `database is
    locked` rather than losing the race fairly. Ending the caller's transaction before
    the claim keeps that window shut.

    Consequence: only enter this where committing the caller's work so far is correct.
    """
    with _claim_lock(clinic_id):
        depth = getattr(_claim_depth, "n", 0)
        _claim_depth.n = depth + 1
        try:
            if depth == 0 and db is not None:
                db.commit()
            yield depth == 0
        finally:
            _claim_depth.n = depth


def claim_slot(db, *, clinic_id: int, branch_id: int, slot_at: datetime,
               service_id=None, doctor_id=None, exclude_booking_id=None,
               write) -> tuple[object | None, str]:
    """Serialise "is this slot free?" with the write that takes it. FIRST WRITER WINS.

    ``write`` is a zero-argument callable, run ONLY after a fresh availability check has
    confirmed the slot and only while this clinic's claim lock is held. It must NOT commit
    — claim_slot commits after it, so the winning row is visible to the next claimant
    before the lock is released (an uncommitted row is not). Inside a ``claim_lock`` block
    the outer caller owns the commit instead, which is what keeps a series atomic.

    Returns ``(write(), "")``, or ``(None, reason)`` when the slot went. ``reason`` is
    SLOT_TAKEN when the day still has other openings, otherwise day_availability's own
    CLOSED / PAST / FULLY_BOOKED / BOOKED_OR_PAST — the vocabulary the AI already knows how
    to explain, so a lost race gets a real sentence instead of a bare failure.

    **It commits the session on entry and again after the write** (the entry commit lives
    in ``claim_lock`` — read why there). Only call it where committing the caller's work
    so far is correct, and never expect to roll the claim back afterwards; both call sites
    qualify (the AI path's contact capture already commits itself, the admin route has
    nothing pending).

    What this protects: every booking THIS PROCESS writes. Two AI background threads, two
    admin requests, or one of each, cannot both take one slot — the loser's re-check sees
    the winner's committed row.

    What it does NOT protect, plainly: a SECOND PROCESS writing bookings (a second uvicorn
    worker, a seed script run alongside the server, a sqlite3 shell). This is a Python object, not a
    database lock. Running this app with >1 worker reintroduces the race — and breaks
    realtime delivery at the same time, which already assumes one process. Nor does it cover a booking written straight through the
    ORM without coming through here (the seeders do exactly that, deliberately, being the
    only writer at the time), or an admin editing slot_at in the database.

    It is a mechanism, not an invariant: nothing in the schema stops two rows sharing a
    slot, and no UNIQUE index could express one — a booking occupies its treatment's whole
    DURATION rather than the minute it starts, and the doctor conflict spans every branch
    of the clinic. The live database already holds two such pairs, from before this existed.
    """
    with claim_lock(clinic_id, db) as outermost:
        slots, reason, _window = day_availability(db, branch_id, slot_at, service_id,
                                                  doctor_id, exclude_booking_id)
        if slot_at not in slots:
            return None, (reason or SLOT_TAKEN)
        out = write()
        if outermost:
            db.commit()     # publish the claim before the lock is released
        return out, ""


def next_available(db, branch_id: int, service_id=None, days_ahead: int = 14,
                   limit: int = 12, per_day: int = 4, doctor_id=None) -> list[datetime]:
    """Upcoming slots over the next ``days_ahead`` days, starting with TODAY's remaining
    openings (available_slots already drops times earlier than now), spread across the day
    (so it isn't all morning of day one) and across days, up to ``limit`` total."""
    out: list[datetime] = []
    base = _now_local()
    for offset in range(0, days_ahead):  # offset 0 = today, so today's slots come first
        day = base + timedelta(days=offset)
        day_slots = available_slots(db, branch_id, day, service_id, doctor_id=doctor_id)
        if len(day_slots) > per_day:  # sample evenly across the day (morning..evening)
            step = len(day_slots) / per_day
            day_slots = [day_slots[int(i * step)] for i in range(per_day)]
        for slot in day_slots:
            out.append(slot)
            if len(out) >= limit:
                return out
    return out


def resolved_price_detail(db, clinic_id, service, branch_id):
    """(price, winning_promo_or_None) for ``service`` at ``branch_id``: the
    branch-specific price (falling back to the catalog base), then an active,
    in-date, quota-available promotion for that service applies if it is
    cheaper. This keeps the booked price (and its deposit) in step with what
    the AI quotes, and lets create_booking stamp WHICH promo won."""
    price = float(service.base_price or 0)
    if branch_id:
        sp = (db.query(models.ServicePrice)
              .filter_by(clinic_id=clinic_id, service_id=service.id, branch_id=branch_id).first())
        if sp and sp.price:
            price = float(sp.price)
    now = _now_local()
    candidates = (db.query(models.Promotion)
                  .filter(models.Promotion.clinic_id == clinic_id,
                          models.Promotion.service_id == service.id,
                          models.Promotion.active.is_(True),
                          models.Promotion.promo_price.isnot(None))
                  .filter((models.Promotion.valid_from.is_(None)) | (models.Promotion.valid_from <= now))
                  .filter((models.Promotion.valid_to.is_(None)) | (models.Promotion.valid_to >= now))
                  .order_by(models.Promotion.promo_price.asc()).all())
    # A promotion can now run at SEVERAL branches, which no longer fits a column
    # comparison — promo_branch_ids is the one reader the tool and the catalog block
    # use too, so a price quoted and a price booked cannot disagree.
    bmap = promo_branch_ids(db, clinic_id) if candidates else {}
    candidates = [c for c in candidates if promo_runs_at(bmap.get(c.id), branch_id)]
    promo = None
    if candidates:
        dead = exhausted_promo_ids(db, clinic_id)  # quota fully redeemed
        for p in candidates:
            if p.id in dead:
                continue
            if float(p.promo_price) < price:
                promo, price = p, float(p.promo_price)
            break  # cheapest eligible candidate; later ones can't be cheaper
    return price, promo


def resolved_price(db, clinic_id, service, branch_id) -> float:
    """The price the customer actually pays — see resolved_price_detail."""
    return resolved_price_detail(db, clinic_id, service, branch_id)[0]


def resolved_hold_minutes(db, clinic_id: int, service) -> int:
    """How long an AI booking of ``service`` should hold its slot, minutes.

    Service override, else clinic override, else the .env HOLD_MINUTES default — same
    sentinel convention as deposit_for (0 = unset, fall through to the next level). For
    example: general treatments hold for the clinic/global default, but a
    surgical procedure with a more involved payment step can be given its own, longer
    number without touching every other treatment or the .env file.

    Only the AI's own booking path (tools.py::book_appointment) calls this — it resolves
    the number ONCE, before create_booking, which keeps taking hold_minutes explicitly
    rather than inferring it (create_booking itself is unchanged)."""
    svc_override = int(getattr(service, "hold_minutes", 0) or 0)
    if svc_override > 0:
        return svc_override
    clinic = db.get(models.Clinic, clinic_id) if clinic_id else None
    clinic_override = int(getattr(clinic, "hold_minutes", 0) or 0) if clinic else 0
    if clinic_override > 0:
        return clinic_override
    return HOLD_MINUTES


def deposit_for(service, price: float) -> float:
    """The deposit owed for a booking at ``price``. Shared by create_booking and the
    AI's pre-booking summary so both quote the same figure.

    A per-service override is a FLAT ฿ amount, deliberately the SAME at every branch
    (clamped 0..base_price by catalog.py) — the clinic sets one deposit for the
    treatment regardless of branch-to-branch price differences. It's capped at
    ``price`` so a branch priced below the override is never asked for more than
    its own price. No override -> the auto 20% of ``price``, rounded to ฿100."""
    override = float(getattr(service, "deposit", 0) or 0)
    if override > 0:
        return min(override, price)
    return round(price * 0.2 / 100) * 100


def create_booking(db, *, customer, service, branch_id: int, slot_at: datetime,
                    doctor_id=None, conversation_id=None, created_by: str = "ai",
                    hold_minutes: int = 0) -> models.Booking:
    """Create a booking and log the activity (clinic derived from the customer).

    ``hold_minutes`` > 0 puts a DEADLINE on the slot: until the booking is paid for it
    blocks the slot as before, and after the deadline the slot is released (see
    day_availability) and the booking is swept to ``expired``. The caller passes it
    EXPLICITLY rather than having it inferred from ``created_by`` — inference would be a
    second reader of "does this booking still need paying for", and the admin UI creates
    its bookings already ``confirmed``. A booking with nothing to pay (price 0) is never
    held: there would be nothing for the deadline to be waiting on.
    """
    clinic_id = customer.clinic_id
    price, promo = resolved_price_detail(db, clinic_id, service, branch_id)
    hold_until = (_now_local() + timedelta(minutes=hold_minutes)
                  if hold_minutes and price > 0 else None)
    booking = models.Booking(
        clinic_id=clinic_id, customer_id=customer.id, branch_id=branch_id,
        service_id=service.id, doctor_id=doctor_id, conversation_id=conversation_id,
        promo_id=promo.id if promo else None,  # which promo priced this booking
        slot_at=slot_at, status="pending", price=price,
        hold_expires_at=hold_until,
        # 0 exactly when hold_until is None (no hold actually applied) — never a number
        # dangling with no matching deadline, which would misstate the booking later.
        hold_minutes=hold_minutes if hold_until else 0,
        deposit_required=deposit_for(service, price),
        created_by=created_by,
    )
    db.add(booking)
    db.flush()
    if branch_id and not customer.branch_id:
        # Web / AI leads are created before any branch is known; the first branch
        # they book at becomes their home branch so per-branch views find them.
        customer.branch_id = branch_id
    db.add(models.Activity(
        clinic_id=clinic_id, customer_id=customer.id, type="booking",
        summary=f"Booking created — {service.name} on {slot_at.strftime('%d %b %H:%M')}",
        ref_type="booking", ref_id=booking.id,
    ))
    return booking


def confirm_paid_booking(db, booking) -> str:
    """Settle a booking whose payment has just landed. Returns what actually happened:
    ``confirmed`` | ``reinstated`` | ``slot_gone`` | ``noop``.

    Lives here, beside day_availability, because the paid-after-expiry question is an
    availability question: money does not buy back a slot somebody else has taken. Does
    not commit — mark_paid's cascade owns the transaction.

    The test is the HOLD DEADLINE, not the status. Payment can land while the sweep has
    not run yet, so the row can still say ``pending`` at a moment when day_availability
    has already released the slot and another customer may hold it.

    **Precondition: the caller must hold THIS CLINIC'S claim_lock — the same lock
    claim_slot uses — for the ENTIRE call, and must not release it until its own commit
    has happened.** Once a hold has lapsed, its slot is open to anyone, so a late payment
    and a brand new booking can race for it exactly like two new bookings would: check,
    then write, with nothing between them otherwise. Holding the lock only across this
    function is NOT enough — if the caller released it before committing, a rival could
    acquire the lock right after, read our still-uncommitted (so invisible to them) write,
    and reach the same "it's free" conclusion we did. The lock has to bracket the decision
    AND its durable write, same as claim_slot itself (commit BEFORE the lock releases).
    This is exactly what mark_paid does — see it for the actual `with claim_lock(...):`.
    This function does not take the lock itself: the caller already holds it, and it needs
    to still be held long after this function returns.
    """
    if not booking:
        return "noop"
    if booking.status in ("confirmed", "completed"):
        booking.hold_expires_at = None
        return "noop"
    if booking.status not in ("pending", EXPIRED):
        return "noop"          # never resurrect a cancelled or no-show booking
    lapsed = bool(booking.hold_expires_at and booking.hold_expires_at <= _now_local())
    if not lapsed:
        # Safe even without the caller's lock mattering here: while the hold still
        # stands, day_availability itself keeps blocking this slot for everyone else, so
        # nothing could have taken it meanwhile.
        booking.status, booking.hold_expires_at = "confirmed", None
        return "confirmed"

    # The hold ran out before the money arrived, and the slot has been open to anyone
    # since the moment it did — this is the actual race the caller's lock protects.
    # available_slots also drops a time that has simply gone past, which is the same
    # answer for the customer: they paid for an appointment that already happened.
    free = available_slots(db, booking.branch_id, booking.slot_at,
                           service_id=booking.service_id, doctor_id=booking.doctor_id,
                           exclude_booking_id=booking.id)
    svc = db.get(models.Service, booking.service_id) if booking.service_id else None
    sname = svc.name if svc else "treatment"
    if booking.slot_at in free:
        booking.status, booking.hold_expires_at = "confirmed", None
        # The expiry sweep cancelled this booking's reminders; generate_reminders will not
        # make new ones because _has_booking_reminder sees the cancelled rows and counts
        # them. Put the still-future ones back rather than leaving a confirmed appointment
        # with nothing to remind anyone about.
        (db.query(models.Reminder)
         .filter(models.Reminder.booking_id == booking.id,
                 models.Reminder.status == "cancelled",
                 models.Reminder.due_at > _now_local())
         .update({models.Reminder.status: "scheduled"}, synchronize_session=False))
        db.add(models.Activity(
            clinic_id=booking.clinic_id, customer_id=booking.customer_id, type="booking",
            summary=(f"Reinstated after payment — {sname} on {booking.slot_at:%d %b %H:%M} "
                     "(hold had expired, slot was still free)"),
            ref_type="booking", ref_id=booking.id))
        return "reinstated"

    booking.status = EXPIRED
    db.add(models.Activity(
        clinic_id=booking.clinic_id, customer_id=booking.customer_id, type="booking",
        summary=(f"PAID AFTER HOLD EXPIRED — {sname} on {booking.slot_at:%d %b %H:%M}; that "
                 "time is no longer free. Contact the customer to rebook. Money received, "
                 "NOT refunded."),
        ref_type="booking", ref_id=booking.id))
    return "slot_gone"
