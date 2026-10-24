"""Calendar feed — a signed-token ICS subscription URL for a clinic's bookings.

The token is the auth: ``/api/calendar/{token}.ics`` is fetched by Google/Apple
Calendar with no session, so it must work unauthenticated. Treat the URL like a
password — anyone holding it can read the clinic's upcoming bookings.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import active_clinic, current_user
from app.scope import scoped
from app.security import make_calendar_token, read_calendar_token
from app.services.booking import _now_local
from app.services.ics import booking_vevent, build_calendar

router = APIRouter(prefix="/api", tags=["calendar"])


@router.get("/calendar/feed-url")
def feed_url(request: Request, branch_id: int = 0,
             clinic: models.Clinic = Depends(active_clinic),
             _u: models.User = Depends(current_user)):
    """The subscribe URL for the active clinic (optionally one branch)."""
    base = str(request.base_url).rstrip("/")
    token = make_calendar_token(clinic.id, branch_id or None)
    return {"url": f"{base}/api/calendar/{token}.ics"}


@router.get("/calendar/{token}.ics")
def calendar_feed(token: str, db: Session = Depends(get_db)):
    data = read_calendar_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Not Found")
    clinic = db.get(models.Clinic, data.get("clid") or 0)
    if not clinic or clinic.status != "active":
        raise HTTPException(status_code=404, detail="Not Found")
    # slot_at is naive Bangkok wall-clock — compare against Bangkok now;
    # keep yesterday too so an in-progress appointment doesn't vanish mid-day.
    q = (scoped(db, models.Booking, clinic.id)
         # 'expired' as well as 'cancelled': a hold whose clock ran out released its slot,
         # so it must not sit on the clinic's calendar as an appointment.
         .filter(models.Booking.status.notin_(["cancelled", "expired"]),
                 models.Booking.slot_at >= _now_local() - timedelta(days=1)))
    if data.get("bid"):
        q = q.filter(models.Booking.branch_id == data["bid"])
    bookings = q.order_by(models.Booking.slot_at).limit(500).all()

    def by_id(model, ids):
        ids = {i for i in ids if i}
        if not ids:
            return {}
        return {r.id: r for r in
                scoped(db, model, clinic.id).filter(model.id.in_(ids)).all()}

    customers = by_id(models.Customer, (b.customer_id for b in bookings))
    services = by_id(models.Service, (b.service_id for b in bookings))
    branches = by_id(models.Branch, (b.branch_id for b in bookings))
    doctors = by_id(models.StaffMember, (b.doctor_id for b in bookings))
    events = [booking_vevent(b, services.get(b.service_id),
                             customers.get(b.customer_id),
                             branches.get(b.branch_id), clinic,
                             doctors.get(b.doctor_id))
              for b in bookings]
    ics = build_calendar(events, f"{clinic.name} - Bookings")
    return Response(content=ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="bookings.ics"'})
