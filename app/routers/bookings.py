"""Booking routes — list, create, reschedule, availability."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, realtime
from app.database import get_db
from app.deps import active_clinic_id, current_user, effective_branch
from app.scope import scoped
from app.services.booking import (BOOKING_STATUSES, available_slots, claim_lock,
                                  claim_slot, create_booking, next_available,
                                  sweep_expired_holds, sweep_no_shows, _add_months,
                                  _now_local)
from app.services.emailer import send_booking_email_async

router = APIRouter(prefix="/api", tags=["bookings"])


def booking_dict(db: Session, b: models.Booking, cid: int) -> dict:
    cust = scoped(db, models.Customer, cid).filter(models.Customer.id == b.customer_id).first()
    svc = scoped(db, models.Service, cid).filter(models.Service.id == b.service_id).first()
    branch = scoped(db, models.Branch, cid).filter(models.Branch.id == b.branch_id).first()
    doctor = (scoped(db, models.StaffMember, cid).filter(models.StaffMember.id == b.doctor_id).first()
              if b.doctor_id else None)
    paid = (scoped(db, models.Payment, cid)
            .filter_by(booking_id=b.id, customer_id=b.customer_id, status="paid").first())
    return {
        "id": b.id, "customer_id": b.customer_id,
        "customer_name": cust.name if cust else "—",
        "service_id": b.service_id, "service_name": svc.name if svc else "—",
        "service_category": svc.category if svc else "",
        "branch_id": b.branch_id, "branch_name": branch.name if branch else "—",
        "doctor_id": b.doctor_id, "doctor_name": doctor.name if doctor else None,
        "slot_at": b.slot_at.isoformat(), "status": b.status,
        # An operator looking at a 'pending' row otherwise has no way to see that it is
        # a held slot about to be released rather than a settled appointment.
        "hold_expires_at": b.hold_expires_at.isoformat() if b.hold_expires_at else None,
        "price": b.price, "deposit_required": b.deposit_required,
        "deposit_paid": bool(paid), "created_by": b.created_by,
        "notes": b.notes,
    }


_SLOT_UNAVAILABLE = ("That time slot is not available (past, outside opening hours, "
                     "or already booked for this branch/doctor)")


def _valid_status(status: str) -> str:
    """A booking status the rest of the app can actually read. This was unvalidated —
    any string at all became the status — which with 'expired' in play would let a typo
    or a stale client park a booking in a state no reader handles."""
    if status not in BOOKING_STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"Invalid status (expected one of: "
                                   f"{', '.join(BOOKING_STATUSES)})")
    return status


def _get_doctor(db: Session, cid: int, doctor_id) -> models.StaffMember | None:
    """Resolve an optional doctor_id to the clinic's StaffMember roster (404 on miss)."""
    if not doctor_id:
        return None
    doctor = (scoped(db, models.StaffMember, cid)
              .filter(models.StaffMember.id == doctor_id).first())
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


def _day_bounds(date_from: str, date_to: str):
    """(start, end) datetimes for an inclusive YYYY-MM-DD range, or None per side.

    ``end`` is the START of the day AFTER date_to, so the whole of the last day is
    inside the window — slot_at carries a time, and a plain ``<= date_to`` would drop
    every booking after midnight on it.
    """
    def _parse(s):
        try:
            return datetime.fromisoformat(s).replace(hour=0, minute=0, second=0,
                                                     microsecond=0)
        except Exception:
            return None

    start = _parse(date_from)
    end = _parse(date_to)
    return start, (end + timedelta(days=1)) if end else None


@router.get("/bookings")
def list_bookings(status: str = "", branch_id: str = "", scope: str = "",
                  date_from: str = "", date_to: str = "",
                  db: Session = Depends(get_db), user: models.User = Depends(current_user),
                  cid: int = Depends(active_clinic_id)):
    # Lazy sweeps so the list is truthful between background runs (cheap indexed
    # queries; each commits only when a booking actually transitions). Holds first: a
    # lapsed hold that is also past its slot is an expiry, not a no-show.
    sweep_expired_holds(db, cid)
    sweep_no_shows(db, cid)
    query = scoped(db, models.Booking, cid)
    if status:
        query = query.filter(models.Booking.status == status)
    bid = effective_branch(user, branch_id)
    if bid:
        query = query.filter(models.Booking.branch_id == bid)
    if scope == "upcoming":
        # slot_at is naive Bangkok wall-clock, so compare against Bangkok now (not UTC)
        query = query.filter(models.Booking.slot_at >= _now_local())
    # Same wall-clock basis as `scope` above: the dates come from the operator's
    # calendar, not from UTC.
    start, end = _day_bounds(date_from, date_to)
    if start:
        query = query.filter(models.Booking.slot_at >= start)
    if end:
        query = query.filter(models.Booking.slot_at < end)
    rows = query.order_by(models.Booking.slot_at).limit(400).all()
    return [booking_dict(db, b, cid) for b in rows]


@router.get("/bookings/availability")
def availability(branch_id: int, date: str = "", doctor_id: int = 0,
                 exclude_booking_id: int = 0, service_id: int = 0,
                 db: Session = Depends(get_db), _u: models.User = Depends(current_user),
                 cid: int = Depends(active_clinic_id)):
    branch = scoped(db, models.Branch, cid).filter(models.Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    doctor = _get_doctor(db, cid, doctor_id)
    did = doctor.id if doctor else None
    if date:
        try:
            # service_id is optional but worth passing: without it a slot only has to be
            # free for SLOT_MINUTES, so a long treatment can be offered a time it cannot
            # actually finish in.
            slots = available_slots(db, branch_id, datetime.fromisoformat(date),
                                    service_id=service_id or None, doctor_id=did,
                                    exclude_booking_id=exclude_booking_id or None)
        except Exception:
            slots = []
    else:
        slots = next_available(db, branch_id, service_id=service_id or None, doctor_id=did)
    return {"slots": [s.isoformat() for s in slots]}


def _series_slot(db, branch_id: int, target: datetime,
                 doctor_id) -> tuple[datetime | None, bool]:
    """The slot a follow-on course session actually gets: the target itself when it
    is free, else the nearest free slot that day, else the nearest slot on the first
    open day within the next 14 days. Returns ``(slot, adjusted)``; ``(None, True)``
    when nothing is free in that window (the session is skipped and reported)."""
    for offset in range(0, 15):
        day = target + timedelta(days=offset)
        slots = available_slots(db, branch_id, day, doctor_id=doctor_id)
        if not slots:
            continue
        if offset == 0 and target in slots:
            return target, False
        want = day.replace(hour=target.hour, minute=target.minute,
                           second=0, microsecond=0)
        return min(slots, key=lambda s: abs(s - want)), True
    return None, True


@router.post("/bookings")
def create(data: dict = Body(...), db: Session = Depends(get_db),
           _u: models.User = Depends(current_user),
           cid: int = Depends(active_clinic_id)):
    cust = (scoped(db, models.Customer, cid)
            .filter(models.Customer.id == data.get("customer_id")).first())
    svc = (scoped(db, models.Service, cid)
           .filter(models.Service.id == data.get("service_id")).first())
    if not cust or not svc:
        raise HTTPException(status_code=400, detail="customer_id and service_id are required")
    try:
        slot = datetime.fromisoformat(data["slot_at"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid slot_at (use ISO datetime)")
    branch_id = data.get("branch_id") or cust.branch_id or 1
    svc_branches = {row.branch_id for row in
                    scoped(db, models.ServiceBranch, cid).filter_by(service_id=svc.id).all()}
    if svc_branches and branch_id not in svc_branches:
        raise HTTPException(status_code=400,
                            detail="This treatment is not offered at the selected branch")
    doctor = _get_doctor(db, cid, data.get("doctor_id"))
    did = doctor.id if doctor else None
    # One check covers past times, out-of-hours, branch-taken slots and doctor conflicts.
    # The service travels with it so the check knows how long the chair is needed for.
    # This is the friendly, early answer; claim_slot below re-checks under the clinic's
    # claim lock and is what actually guarantees no two writers take the same slot.
    if slot not in available_slots(db, branch_id, slot, service_id=svc.id, doctor_id=did):
        raise HTTPException(status_code=409, detail=_SLOT_UNAVAILABLE)
    # Course/bundle series: N sessions, every M calendar months (session 1 = the chosen slot)
    try:
        sessions = min(max(int(data.get("bundle_sessions") or 1), 1), 12)
        interval = min(max(int(data.get("bundle_interval_months") or 1), 1), 12)
    except Exception:
        sessions, interval = 1, 1
    bookings = []
    adjusted = 0
    # ONE claim lock for the whole series, so every session is decided against one view of
    # the diary and the route keeps its single commit (a course must not half-exist).
    # claim_slot re-enters this lock without re-acquiring or committing.
    with claim_lock(cid, db):
        for i in range(sessions):
            s_at = slot
            if i > 0:
                # Follow-on sessions must pass the SAME availability check as session 1
                # (branch capacity, opening hours, doctor conflicts) — otherwise a course
                # silently double-books a taken slot or lands on a closed day.
                s_at, moved = _series_slot(db, branch_id, _add_months(slot, i * interval), did)
                if s_at is None:
                    adjusted += 1
                    continue        # nothing free within 14 days of the target — skip
                if moved:
                    adjusted += 1

            def _write(s_at=s_at):     # bind per iteration, or every session claims the last
                b = create_booking(db, customer=cust, service=svc, branch_id=branch_id,
                                   slot_at=s_at, doctor_id=did, created_by="admin")
                b.clinic_id = cid
                if data.get("status"):
                    b.status = _valid_status(data["status"])
                return b

            b, lost = claim_slot(db, clinic_id=cid, branch_id=branch_id, slot_at=s_at,
                                 service_id=svc.id, doctor_id=did, write=_write)
            if b is None:
                if i == 0:
                    raise HTTPException(status_code=409, detail=_SLOT_UNAVAILABLE)
                adjusted += 1       # a follow-on session lost the race — skip and report
                continue
            bookings.append(b)
        if sessions > 1:
            # Re-normalise the ครั้งที่ i/N labels to the ACTUAL created count — when a
            # follow-on session was skipped (nothing free within 14 days) the requested
            # denominator would otherwise overstate the course (e.g. 1/3, 2/3 with no 3/3).
            for idx, b in enumerate(bookings):
                b.notes = f"ครั้งที่ {idx + 1}/{len(bookings)}"
    db.commit()
    realtime.publish({"type": "booking", "booking_id": bookings[0].id, "clinic_id": cid})
    send_booking_email_async(bookings[0].id)  # after commit — the emailer opens its own session
    return {**booking_dict(db, bookings[0], cid),
            "series_count": len(bookings),
            "series_adjusted": adjusted,
            "series_slots": [b.slot_at.isoformat() for b in bookings]}


@router.patch("/bookings/{bid}")
def update(bid: int, data: dict = Body(...), db: Session = Depends(get_db),
           _u: models.User = Depends(current_user),
           cid: int = Depends(active_clinic_id)):
    booking = scoped(db, models.Booking, cid).filter(models.Booking.id == bid).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    # Validated here, applied AFTER the slot work: claim_slot commits on entry, so a status
    # written before it would survive a 409 that used to discard the whole request.
    new_status = _valid_status(data["status"]) if "status" in data else None
    new_doctor_id = booking.doctor_id
    if "doctor_id" in data:
        doctor = _get_doctor(db, cid, data["doctor_id"])
        new_doctor_id = doctor.id if doctor else None
    new_slot = None
    if "slot_at" in data:
        try:
            new_slot = datetime.fromisoformat(data["slot_at"])
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid slot_at (use ISO datetime)")
    rescheduled = False
    if new_slot and new_slot != booking.slot_at:
        # exclude this booking so it can move within its own day / keep its doctor.
        # service_id travels with the check, or a 90-minute treatment moves into a
        # 30-minute gap — the check only knows how long the chair is needed when told.
        if new_slot not in available_slots(db, booking.branch_id, new_slot,
                                           service_id=booking.service_id,
                                           doctor_id=new_doctor_id,
                                           exclude_booking_id=booking.id):
            raise HTTPException(status_code=409, detail=_SLOT_UNAVAILABLE)
        svc = scoped(db, models.Service, cid).filter(models.Service.id == booking.service_id).first()
        old = booking.slot_at

        def _move():
            booking.slot_at = new_slot
            booking.doctor_id = new_doctor_id
            db.add(models.Activity(
                clinic_id=cid, customer_id=booking.customer_id, type="booking",
                summary=f"Rescheduled {svc.name if svc else 'treatment'} "
                        f"from {old:%d %b %H:%M} to {new_slot:%d %b %H:%M}",
                ref_type="booking", ref_id=booking.id))
            return booking

        moved, _lost = claim_slot(db, clinic_id=cid, branch_id=booking.branch_id,
                                  slot_at=new_slot, service_id=booking.service_id,
                                  doctor_id=new_doctor_id,
                                  exclude_booking_id=booking.id, write=_move)
        if moved is None:
            raise HTTPException(status_code=409, detail=_SLOT_UNAVAILABLE)
        rescheduled = True
    elif (new_doctor_id != booking.doctor_id and new_doctor_id
          and booking.slot_at > _now_local()):
        # doctor changed with the slot unchanged — the new doctor must be free then
        # (past bookings are record-keeping edits, no conflict check)
        def _assign():
            booking.doctor_id = new_doctor_id
            return booking

        assigned, _lost = claim_slot(db, clinic_id=cid, branch_id=booking.branch_id,
                                     slot_at=booking.slot_at,
                                     service_id=booking.service_id,
                                     doctor_id=new_doctor_id,
                                     exclude_booking_id=booking.id, write=_assign)
        if assigned is None:
            raise HTTPException(status_code=409,
                                detail="That doctor already has a booking at this time")
    else:
        booking.doctor_id = new_doctor_id
    if new_status:
        booking.status = new_status
        if new_status in ("confirmed", "completed"):
            # Staff settling a booking by hand takes the clock off it. A stale deadline
            # left on a confirmed row would make day_availability read the slot as free.
            booking.hold_expires_at = None
    db.commit()
    realtime.publish({"type": "booking", "booking_id": booking.id, "clinic_id": cid})
    # only a real slot change notifies the customer — status/doctor edits don't
    if rescheduled and booking.status not in ("cancelled", "expired"):
        send_booking_email_async(booking.id, kind="reschedule")
    return booking_dict(db, booking, cid)


@router.delete("/bookings/{bid}")
def delete_booking(bid: int, db: Session = Depends(get_db),
                   _u: models.User = Depends(current_user),
                   cid: int = Depends(active_clinic_id)):
    """Remove a booking. With a paid payment it is cancelled-but-kept (history must
    survive); otherwise the booking and its still-pending payments are deleted."""
    booking = scoped(db, models.Booking, cid).filter(models.Booking.id == bid).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    has_paid = (scoped(db, models.Payment, cid)
                .filter(models.Payment.booking_id == bid,
                        models.Payment.status == "paid").first() is not None)
    if has_paid:
        booking.status = "cancelled"
        db.commit()
        realtime.publish({"type": "booking", "booking_id": bid, "clinic_id": cid})
        return {"ok": True, "cancelled": True}
    (scoped(db, models.Payment, cid)
     .filter(models.Payment.booking_id == bid, models.Payment.status != "paid")
     .delete(synchronize_session=False))
    db.delete(booking)
    db.commit()
    realtime.publish({"type": "booking", "booking_id": bid, "clinic_id": cid})
    return {"ok": True, "cancelled": False}
