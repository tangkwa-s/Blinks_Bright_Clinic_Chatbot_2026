"""RFC 5545 (.ics) building — shared by the calendar feed and booking emails.

``Booking.slot_at`` is stored as NAIVE Bangkok wall-clock (see booking.py), so
timestamps are localised to the clinic timezone first and then emitted in UTC
'Z' form. Thailand has no DST, so no VTIMEZONE block is needed.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

try:
    _LOCAL_TZ = ZoneInfo(settings.timezone)
except Exception:  # pragma: no cover
    _LOCAL_TZ = ZoneInfo("Asia/Bangkok")


def ics_escape(value) -> str:
    """Escape a TEXT value per RFC 5545 (backslash, ';', ',', newlines)."""
    s = str(value or "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line: str) -> str:
    """Fold a content line at 75 octets with CRLF + single-space continuation.

    Folds on UTF-8 BYTE length (Thai text is 3 bytes/char) and never splits a
    character — Apple Calendar/Outlook are strict about this.
    """
    if len(line.encode("utf-8")) <= 75:
        return line
    parts: list[str] = []
    chunk = b""
    for ch in line:
        b = ch.encode("utf-8")
        # continuation lines carry a leading space, so they get one octet less
        limit = 75 if not parts else 74
        if len(chunk) + len(b) > limit:
            parts.append(chunk.decode("utf-8"))
            chunk = b
        else:
            chunk += b
    if chunk:
        parts.append(chunk.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc_stamp(local_naive: datetime) -> str:
    """Naive clinic-local datetime -> 'YYYYMMDDTHHMMSSZ' (UTC)."""
    return (local_naive.replace(tzinfo=_LOCAL_TZ)
            .astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))


def booking_vevent(booking, service=None, customer=None, branch=None,
                   clinic=None, doctor=None) -> list[str]:
    """One booking as VEVENT content lines (unfolded — build_calendar folds)."""
    duration = (service.duration_min if service and service.duration_min else 45)
    start = booking.slot_at
    end = start + timedelta(minutes=duration)
    slug = clinic.slug if clinic else "clinic"
    summary = " - ".join(x for x in [
        service.name if service else "Appointment",
        customer.name if customer else ""] if x)
    desc = [f"Status: {booking.status}"]
    if doctor:
        desc.append(f"Doctor: {doctor.name}")
    if booking.deposit_required:
        desc.append(f"Deposit: THB {int(booking.deposit_required):,}")
    if booking.notes:
        desc.append(booking.notes)
    location = ", ".join(x for x in [
        branch.name if branch else "",
        branch.address if branch else ""] if x)
    lines = [
        "BEGIN:VEVENT",
        # stable UID: a rescheduled booking replaces its event on the next poll
        f"UID:booking-{booking.id}@{slug}.blinksbright",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{_utc_stamp(start)}",
        f"DTEND:{_utc_stamp(end)}",
        f"SUMMARY:{ics_escape(summary)}",
        # A different question from the router's (which events at all): how firm each one
        # is. An 'expired' booking reaching here would otherwise export as CONFIRMED.
        f"STATUS:{'TENTATIVE' if booking.status in ('pending', 'expired') else 'CONFIRMED'}",
    ]
    if location:
        lines.append(f"LOCATION:{ics_escape(location)}")
    lines.append(f"DESCRIPTION:{ics_escape(chr(10).join(desc))}")
    lines.append("END:VEVENT")
    return lines


def build_calendar(vevents: list[list[str]], name: str) -> str:
    """Wrap VEVENT line blocks into a complete VCALENDAR (CRLF line endings)."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Blinks Bright//Bookings//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(name)}",
        f"X-WR-TIMEZONE:{settings.timezone}",
    ]
    for ev in vevents:
        lines.extend(ev)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
