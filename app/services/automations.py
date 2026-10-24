"""Retention automation engine — reminder generation and processing.

Generates reminders from each clinic's automation rules (treatment-due,
win-back, lead-nurture, birthday, package-expiry) and processes any that are
due. Runs on a schedule and on demand. Every clinic is handled independently.
"""
from datetime import datetime, timedelta

from app import models
from app.database import SessionLocal
from app.scope import scoped
from app.services.booking import _now_local, sweep_expired_holds, sweep_no_shows

# personalised cross-sell — what to recommend next based on the last treatment
CROSS_SELL = {
    "botox": "Skin Booster เพื่อผิวฉ่ำวาว", "ฟิลเลอร์": "Skin Booster",
    "filler": "Skin Booster หรือ HIFU", "skin booster": "Pico Laser ผิวกระจ่างใส",
    "hifu": "Filler เติมเต็มรูปหน้า", "thread": "Filler เก็บรายละเอียด",
    "pico": "Signature Facial ดูแลต่อเนื่อง", "laser": "Signature Facial",
    "facial": "แพ็กเกจสมาชิกดูแลผิวรายเดือน", "meso": "Skin Booster",
    "acne": "Pico Laser ลดรอยสิว",
}


def _cross_sell(service_name: str) -> str | None:
    name = (service_name or "").lower()
    for key, rec in CROSS_SELL.items():
        if key in name:
            return rec
    return None


def _has_recent_reminder(db, clinic_id, customer_id: int, rtype: str, within_days: int) -> bool:
    cutoff = datetime.utcnow() - timedelta(days=within_days)
    return scoped(db, models.Reminder, clinic_id).filter(
        models.Reminder.customer_id == customer_id,
        models.Reminder.type == rtype,
        models.Reminder.created_at >= cutoff,
    ).first() is not None


def _has_booking_reminder(db, clinic_id, booking_id: int, rtype: str) -> bool:
    """True if a reminder of this type already exists for a specific booking
    (so re-runs never duplicate appointment / aftercare reminders)."""
    return scoped(db, models.Reminder, clinic_id).filter(
        models.Reminder.booking_id == booking_id,
        models.Reminder.type == rtype,
    ).first() is not None


def generate_reminders(db, clinic, now: datetime | None = None) -> int:
    """Create new reminders from one clinic's enabled automation rules."""
    # Booking.slot_at and the Reminder.due_at derived from it are naive Bangkok
    # wall-clock, so 'now' must be Bangkok local too (a UTC now is 7h off and
    # marks past bookings as upcoming / fires reminders at the wrong time).
    now = now or _now_local()
    cid = clinic.id
    rules = {r.type: r for r in
             scoped(db, models.AutomationRule, cid).filter_by(enabled=True).all()}
    customers = scoped(db, models.Customer, cid).filter(models.Customer.merged_into_id.is_(None)).all()
    services = {s.id: s for s in scoped(db, models.Service, cid).all()}
    branches = {b.id: b for b in scoped(db, models.Branch, cid).all()}
    created = 0

    # appointment reminders — 24h AND 3h before each upcoming booking
    if "pre_appointment" in rules:
        upcoming = (scoped(db, models.Booking, cid)
                    .filter(models.Booking.status.in_(["pending", "confirmed"]),
                            models.Booking.slot_at > now).all())
        for bk in upcoming:
            if _has_booking_reminder(db, cid, bk.id, "pre_appointment"):
                continue
            c = db.get(models.Customer, bk.customer_id)
            svc = services.get(bk.service_id)
            br = branches.get(bk.branch_id)
            sname = svc.name if svc else "ทรีตเมนต์"
            fname = c.name.split()[0] if c and c.name else "ลูกค้า"
            when = bk.slot_at.strftime("%d %b %H:%M")
            at_branch = f" ที่ {br.name}" if br else ""
            for hours, lead in ((24, "พรุ่งนี้"), (3, "อีก 3 ชั่วโมง")):
                due = bk.slot_at - timedelta(hours=hours)
                if due <= now:
                    continue  # appointment is sooner than this lead time — skip it
                db.add(models.Reminder(
                    clinic_id=cid, customer_id=bk.customer_id, type="pre_appointment",
                    channel=(c.channel if c else "web"), booking_id=bk.id,
                    title=f"เตือนนัด ({hours} ชม. ก่อนถึงคิว)",
                    body=f"คุณ{fname} ค่ะ {lead}คุณมีนัด {sname} วันที่ {when}{at_branch} นะคะ 🌿 "
                         f"แล้วเจอกันค่ะ (ตอบกลับได้หากต้องการเลื่อนนัด)",
                    due_at=due, status="scheduled", created_at=now))
                created += 1

    # aftercare follow-ups — day 1 / 7 / 14 after a completed treatment
    aftercare = [("followup_d1", 1, "ดูแลหลังทำ — วันที่ 1"),
                 ("followup_d7", 7, "ติดตามผล — วันที่ 7"),
                 ("followup_d14", 14, "ติดตามผล + แนะนำต่อ — วันที่ 14")]
    if any(rt in rules for rt, _, _ in aftercare):
        # only recently-completed treatments — older ones' windows have passed
        done = (scoped(db, models.Booking, cid)
                .filter(models.Booking.status == "completed",
                        models.Booking.slot_at >= now - timedelta(days=21)).all())
        for bk in done:
            c = db.get(models.Customer, bk.customer_id)
            svc = services.get(bk.service_id)
            sname = svc.name if svc else "ทรีตเมนต์"
            fname = c.name.split()[0] if c and c.name else "ลูกค้า"
            care = (svc.aftercare_notes or "").strip() if svc else ""
            for rtype, days, title in aftercare:
                if rtype not in rules or _has_booking_reminder(db, cid, bk.id, rtype):
                    continue
                if rtype == "followup_d1":
                    body = (f"คุณ{fname} ค่ะ เป็นยังไงบ้างหลังทำ {sname} คะ? "
                            + (f"วิธีดูแล: {care[:170]}" if care else "มีอะไรสอบถามได้เลยนะคะ 😊"))
                elif rtype == "followup_d7":
                    body = (f"คุณ{fname} ค่ะ ครบ 1 สัปดาห์หลังทำ {sname} แล้ว ผิวเป็นยังไงบ้างคะ? "
                            "ถ้ามีข้อสงสัยปรึกษาได้เลยนะคะ")
                else:
                    rec = _cross_sell(sname)
                    nxt = f" ครั้งหน้าลองต่อยอดด้วย {rec} ดูไหมคะ" if rec else ""
                    body = (f"คุณ{fname} ค่ะ ครบ 2 สัปดาห์แล้ว ผลลัพธ์ {sname} เป็นที่พอใจไหมคะ?"
                            f"{nxt} 🌿")
                db.add(models.Reminder(
                    clinic_id=cid, customer_id=bk.customer_id, type=rtype,
                    channel=(c.channel if c else "web"), booking_id=bk.id,
                    title=title, body=body,
                    due_at=bk.slot_at + timedelta(days=days), status="scheduled", created_at=now))
                created += 1

    # treatment-due — based on the recommended interval of the last completed booking
    if "treatment_due" in rules:
        for c in customers:
            if not c.last_treatment_at:
                continue
            last = (scoped(db, models.Booking, cid)
                    .filter_by(customer_id=c.id, status="completed")
                    .order_by(models.Booking.slot_at.desc()).first())
            svc = services.get(last.service_id) if last else None
            if not svc or not svc.recommended_interval_days:
                continue
            due = last.slot_at + timedelta(days=svc.recommended_interval_days)
            if due <= now + timedelta(days=7) and not _has_recent_reminder(db, cid, c.id, "treatment_due", 60):
                db.add(models.Reminder(
                    clinic_id=cid, customer_id=c.id, type="treatment_due", channel=c.channel,
                    title=f"{svc.name} is due again",
                    body=f"คุณ{c.name.split()[0]} ค่ะ {svc.name} ครบกำหนดดูแลต่อเนื่องแล้วนะคะ "
                         f"จองคิวเลยไหมคะ 🌿",
                    due_at=max(due, now), status="scheduled", created_at=now))
                created += 1

    # win-back — inactive customers, with a personalised recommendation
    if "winback" in rules:
        inactive_days = rules["winback"].config.get("inactive_days", 120)
        for c in customers:
            if not c.last_treatment_at:
                continue
            if ((now - c.last_treatment_at).days >= inactive_days
                    and not _has_recent_reminder(db, cid, c.id, "winback", 90)):
                last = (scoped(db, models.Booking, cid)
                        .filter_by(customer_id=c.id, status="completed")
                        .order_by(models.Booking.slot_at.desc()).first())
                svc = services.get(last.service_id) if last else None
                rec = _cross_sell(svc.name) if svc else None
                tip = (f" คราวนี้ลอง {rec} ดูไหมคะ ต่อยอดจาก {svc.name} ที่เคยทำค่ะ"
                       if rec and svc else "")
                db.add(models.Reminder(
                    clinic_id=cid, customer_id=c.id, type="winback", channel=c.channel,
                    title="We miss you",
                    body=f"คุณ{c.name.split()[0]} ไม่ได้เจอกันนานเลยค่ะ 💚 "
                         f"ตอนนี้มีโปรพิเศษสำหรับลูกค้าเก่านะคะ{tip}",
                    due_at=now, status="scheduled", created_at=now))
                created += 1

    # unbooked-lead nurture — interested leads who have gone quiet
    if "lead_nurture" in rules:
        quiet = rules["lead_nurture"].config.get("quiet_days", 3)
        for c in customers:
            if c.pipeline_stage != "interested" or not c.last_activity_at:
                continue
            if ((now - c.last_activity_at).days >= quiet
                    and not _has_recent_reminder(db, cid, c.id, "lead_nurture", 14)):
                topic = c.interested or "บริการที่สนใจ"
                db.add(models.Reminder(
                    clinic_id=cid, customer_id=c.id, type="lead_nurture", channel=c.channel,
                    title="Following up on your enquiry",
                    body=f"คุณ{c.name.split()[0]} ค่ะ เกี่ยวกับ {topic} ที่คุยกันไว้ "
                         f"มีอะไรให้ช่วยเพิ่มเติมไหมคะ ดิฉันจองคิวหรือแนะนำโปรให้ได้เลยนะคะ 😊",
                    due_at=now, status="scheduled", created_at=now))
                created += 1

    # birthday
    if "birthday" in rules:
        for c in customers:
            if (c.birthday and c.birthday.month == now.month
                    and c.birthday.day == now.day
                    and not _has_recent_reminder(db, cid, c.id, "birthday", 300)):
                db.add(models.Reminder(
                    clinic_id=cid, customer_id=c.id, type="birthday", channel=c.channel,
                    title="Happy birthday!",
                    body=f"สุขสันต์วันเกิดค่ะคุณ{c.name.split()[0]} 🎂 "
                         f"รับของขวัญวันเกิดพิเศษจากคลินิกได้เลยนะคะ",
                    due_at=now, status="scheduled", created_at=now))
                created += 1

    # package expiring soon
    if "package_expiry" in rules:
        for p in scoped(db, models.Package, cid).all():
            if not p.expires_at or p.used_sessions >= p.total_sessions:
                continue
            if (now <= p.expires_at <= now + timedelta(days=14)
                    and not _has_recent_reminder(db, cid, p.customer_id, "package_expiry", 30)):
                c = db.get(models.Customer, p.customer_id)
                remaining = p.total_sessions - p.used_sessions
                db.add(models.Reminder(
                    clinic_id=cid, customer_id=p.customer_id, type="package_expiry",
                    channel=c.channel if c else "web",
                    title="Package expiring soon",
                    body=f"แพ็กเกจ {p.name} ใกล้หมดอายุแล้วค่ะ ยังเหลือ {remaining} ครั้ง "
                         f"รีบใช้สิทธิ์นะคะ",
                    due_at=now, status="scheduled", created_at=now))
                created += 1

    db.commit()
    return created


def process_due(db, clinic, now: datetime | None = None) -> dict:
    """Deliver one clinic's due reminders to the customer in their chat
    (via the same path broadcasts use), then mark them sent.
    Returns {'sent': delivered, 'failed': undeliverable} so callers can surface
    failures instead of silently swallowing them."""
    from app.services.inbox import broadcast_to_customer

    now = now or _now_local()  # Reminder.due_at is naive Bangkok wall-clock, not UTC
    due = (scoped(db, models.Reminder, clinic.id)
           .filter(models.Reminder.status == "scheduled",
                   models.Reminder.due_at <= now).all())
    sent_n = failed_n = 0
    for r in due:
        cust = db.get(models.Customer, r.customer_id)
        delivered = False
        if cust and (r.body or "").strip():
            try:
                # tagged so the inbox shows this was an automation, not a human reply
                delivered = bool(broadcast_to_customer(db, cust, r.body,
                                                       sender_name="Automation"))
            except Exception as exc:  # pragma: no cover
                print("[reminders] send error:", exc)
        r.status = "sent" if delivered else "failed"
        r.sent_at = now
        if delivered:
            sent_n += 1
        else:
            failed_n += 1
        db.add(models.Activity(
            clinic_id=clinic.id, customer_id=r.customer_id, type="reminder",
            summary=(f"Reminder sent — {r.title}" if delivered
                     else f"Reminder could not be delivered — {r.title}"),
            ref_type="reminder", ref_id=r.id))
    db.commit()
    return {"sent": sent_n, "failed": failed_n}


def process_scheduled_campaigns(db, clinic, now: datetime | None = None) -> int:
    """Send any of a clinic's campaigns whose scheduled time has arrived."""
    now = now or datetime.utcnow()
    due = (scoped(db, models.Campaign, clinic.id)
           .filter(models.Campaign.status == "scheduled",
                   models.Campaign.scheduled_at.isnot(None),
                   models.Campaign.scheduled_at <= now).all())
    if not due:
        return 0
    from app.routers.broadcast import deliver_campaign

    n = 0
    for camp in due:
        try:
            deliver_campaign(db, camp, clinic.id)
            n += 1
        except Exception as exc:  # pragma: no cover
            print("[campaigns] scheduled send error:", exc)
            db.rollback()
    return n


def run_automations(now: datetime | None = None, clinic_id: int | None = None) -> dict:
    """Generate and process reminders. With ``clinic_id`` → one clinic; else all."""
    db = SessionLocal()
    try:
        if clinic_id is not None:
            clinics = [c for c in [db.get(models.Clinic, clinic_id)] if c]
        else:
            clinics = db.query(models.Clinic).filter_by(status="active").all()
        generated = sent = failed = campaigns = no_shows = expired_holds = 0
        for clinic in clinics:
            # Holds first: a hold that lapsed and is ALSO hours past its slot is an
            # expiry, not a no-show — the customer never had an appointment to miss.
            expired_holds += sweep_expired_holds(db, clinic.id, now)
            no_shows += sweep_no_shows(db, clinic.id, now)
            generated += generate_reminders(db, clinic, now)
            processed = process_due(db, clinic, now)
            sent += processed["sent"]
            failed += processed["failed"]
            campaigns += process_scheduled_campaigns(db, clinic, now)
        result = {"generated": generated, "sent": sent, "failed": failed,
                  "campaigns_sent": campaigns, "no_shows": no_shows,
                  "expired_holds": expired_holds}
        print(f"[automations] {result}")
        return result
    except Exception as exc:  # pragma: no cover
        print("[automations] error:", exc)
        return {"generated": 0, "sent": 0, "failed": 0, "error": str(exc)}
    finally:
        db.close()


def sweep_all_expired_holds(now: datetime | None = None) -> int:
    """Expire lapsed unpaid holds across every active clinic — the fast loop.

    run_automations also sweeps, but only every 30 minutes; a 10-minute hold whose
    cancel + customer notice can lag half an hour is not a 10-minute promise. This
    carries ONLY the hold sweep so the scheduler can run it every 60 seconds: per
    clinic it is one indexed query, and an all-quiet minute writes nothing at all.
    (The SLOT itself is released at read time by day_availability either way — this
    is about flipping the status and telling the customer on time.)
    """
    db = SessionLocal()
    try:
        total = 0
        for clinic in db.query(models.Clinic).filter_by(status="active").all():
            try:
                total += sweep_expired_holds(db, clinic.id, now)
            except Exception as exc:  # pragma: no cover
                print("[holds] sweep error:", exc)
                db.rollback()
        if total:
            print(f"[holds] released {total} lapsed unpaid hold(s)")
        return total
    finally:
        db.close()


def sweep_all_hold_reminders(now: datetime | None = None) -> int:
    """Warn customers across every active clinic whose unpaid hold is about to lapse —
    same fast-loop shape as sweep_all_expired_holds, run right before it (a booking
    already past its deadline needs the expiry notice, not a redundant reminder)."""
    from app.services.booking import sweep_hold_reminders

    db = SessionLocal()
    try:
        total = 0
        for clinic in db.query(models.Clinic).filter_by(status="active").all():
            try:
                total += sweep_hold_reminders(db, clinic.id, now)
            except Exception as exc:  # pragma: no cover
                print("[holds] reminder sweep error:", exc)
                db.rollback()
        if total:
            print(f"[holds] sent {total} hold-expiry reminder(s)")
        return total
    finally:
        db.close()


def sweep_all_stale_takeovers(now: datetime | None = None) -> int:
    """Auto-return stale human takeovers to the AI across every active clinic — same
    fast-loop shape as sweep_all_expired_holds, for the same reason: a 15-minute
    promise ("the AI will pick this back up if nobody answers") can't ride the
    30-minute run_automations tick.
    """
    from app.services.inbox import sweep_stale_takeovers

    db = SessionLocal()
    try:
        total = 0
        for clinic in db.query(models.Clinic).filter_by(status="active").all():
            try:
                total += sweep_stale_takeovers(db, clinic.id, now)
            except Exception as exc:  # pragma: no cover
                print("[takeover] sweep error:", exc)
                db.rollback()
        if total:
            print(f"[takeover] auto-returned {total} stale takeover(s) to the AI")
        return total
    finally:
        db.close()
