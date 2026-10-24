"""Booking-confirmation email via Resend, with an .ics calendar attachment.

Degrades gracefully like the channel adapters: no RESEND_API_KEY, no customer
email, or an API failure -> logged and skipped, never raised. Runs on a daemon
thread and MUST be called after the caller's db.commit() — it opens its own
session to read the booking.
"""
import base64
import threading

import httpx

from app import models
from app.config import settings
from app.database import SessionLocal
from app.scope import scoped
from app.services.ics import booking_vevent, build_calendar

RESEND_URL = "https://api.resend.com/emails"
# Resend's shared test sender — works without a verified domain, but then only
# delivers to the Resend account owner's own address.
_FALLBACK_FROM = "onboarding@resend.dev"

_COPY = {
    "confirmation": {
        "subject": "ยืนยันการนัดหมาย — {clinic}",
        "head_th": "การนัดหมายของคุณได้รับการยืนยันแล้ว",
        "head_en": "Your appointment is booked",
    },
    "reschedule": {
        "subject": "เลื่อนนัดหมายเรียบร้อย — {clinic}",
        "head_th": "การนัดหมายของคุณถูกเลื่อนเรียบร้อยแล้ว",
        "head_en": "Your appointment has been rescheduled",
    },
}


def _row(label: str, value: str) -> str:
    return (f'<tr><td style="padding:6px 12px 6px 0;color:#666;white-space:nowrap">{label}</td>'
            f'<td style="padding:6px 0">{value}</td></tr>')


def send_booking_email(booking_id: int, kind: str = "confirmation") -> None:
    """Send the confirmation/reschedule email for one booking (blocking)."""
    if not settings.resend_api_key:
        return
    db = SessionLocal()
    try:
        booking = db.get(models.Booking, booking_id)
        # 'expired' too: a released hold has no appointment to confirm or reschedule.
        if (not booking or booking.status in ("cancelled", "expired")
                or not booking.clinic_id):
            return
        cid = booking.clinic_id
        customer = (scoped(db, models.Customer, cid)
                    .filter(models.Customer.id == booking.customer_id).first())
        email = (customer.email or "").strip() if customer else ""
        if not email:
            return
        clinic = db.get(models.Clinic, cid)
        service = (scoped(db, models.Service, cid)
                   .filter(models.Service.id == booking.service_id).first())
        branch = (scoped(db, models.Branch, cid)
                  .filter(models.Branch.id == booking.branch_id).first())
        doctor = (scoped(db, models.StaffMember, cid)
                  .filter(models.StaffMember.id == booking.doctor_id).first()
                  if booking.doctor_id else None)

        copy = _COPY.get(kind, _COPY["confirmation"])
        clinic_name = clinic.name if clinic else "Clinic"
        # slot_at is already Bangkok wall-clock — format directly, no conversion
        when = booking.slot_at.strftime("%d/%m/%Y %H:%M")
        rows = [_row("ทรีตเมนต์ (Treatment)",
                     service.name if service else "-"),
                _row("วันและเวลา (Date &amp; time)", f"{when} น.")]
        if branch:
            rows.append(_row("สาขา (Branch)",
                             ", ".join(x for x in [branch.name, branch.address] if x)))
        if doctor:
            rows.append(_row("แพทย์ (Doctor)", doctor.name))
        if booking.deposit_required:
            rows.append(_row("มัดจำ (Deposit)", f"฿{int(booking.deposit_required):,}"))
        html = (f'<div style="font-family:sans-serif;max-width:520px;color:#222">'
                f'<h2 style="margin:0 0 4px">{clinic_name}</h2>'
                f'<p style="margin:0 0 16px">{copy["head_th"]}<br>'
                f'<span style="color:#666">{copy["head_en"]}</span></p>'
                f'<table style="border-collapse:collapse">{"".join(rows)}</table>'
                f'<p style="color:#666;margin-top:16px">เพิ่มลงปฏิทินได้จากไฟล์แนบ '
                f'(Add to your calendar with the attached .ics file.)</p></div>')

        ics = build_calendar(
            [booking_vevent(booking, service, customer, branch, clinic, doctor)],
            f"{clinic_name} - Booking")
        r = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from or _FALLBACK_FROM,
                  "to": [email],
                  "subject": copy["subject"].format(clinic=clinic_name),
                  "html": html,
                  "attachments": [{
                      "filename": "booking.ics",
                      "content": base64.b64encode(ics.encode("utf-8")).decode(),
                      "content_type": "text/calendar",
                  }]},
            timeout=10)
        if r.status_code >= 300:
            print("[email] send failed:", r.status_code, r.text[:200])
    except Exception as exc:
        print("[email] error:", exc)
    finally:
        db.close()


def send_booking_email_async(booking_id: int, kind: str = "confirmation") -> None:
    """Fire-and-forget on a daemon thread. Cheap no-op when Resend isn't
    configured, so tests/dev never spawn a thread at all."""
    if not settings.resend_api_key:
        return
    threading.Thread(target=send_booking_email, args=(booking_id, kind),
                     daemon=True).start()
