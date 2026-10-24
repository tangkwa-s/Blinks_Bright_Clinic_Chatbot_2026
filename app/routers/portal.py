"""Customer portal — the public, customer-facing side of the clinic.

Three groups of routes, all under ``/api/portal``:

* **public** (no session): ``/home`` feeds the marketing landing page — clinic,
  branches, treatments, promotions, doctors. Anyone may read it; it is exactly
  the information the clinic publishes anyway.
* **auth**: register / login / logout with **phone + password**. Customers are a
  different population from staff (``User``), so they get their own table, their
  own cookie and their own signing salt — a staff session can never be replayed
  as a customer one, or the reverse.
* **account** (customer session required): profile, bookings, payments, and the
  chat token for this customer's own conversation.

Everything here is scoped to one customer id taken from the signed cookie. No
route accepts a customer id from the client: that is the whole reason the
"don't reveal another customer's data" rule can be enforced structurally here
rather than hoped for.
"""
import re
from datetime import datetime, timedelta

from fastapi import (APIRouter, BackgroundTasks, Body, Cookie, Depends,
                     HTTPException, Response)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models, realtime
from app.database import get_db
from app.scope import scoped
from app.security import (CUSTOMER_COOKIE, SESSION_MAX_AGE, hash_password,
                          make_chat_token, make_customer_session,
                          read_customer_session, verify_password)
from app.services.booking import branch_days, deposit_for, resolved_price
from app.services.inbox import conv_summary, phone_key

router = APIRouter(prefix="/api/portal", tags=["portal"])

MIN_PASSWORD = 8


# --------------------------------------------------------------------------
#  clinic resolution
# --------------------------------------------------------------------------
def portal_clinic(db: Session, slug: str | None = None) -> models.Clinic:
    """The clinic this portal is serving. Mirrors channels.py::_resolve_clinic so
    the landing page, the widget and the webhooks all land on the same tenant."""
    if slug:
        c = db.query(models.Clinic).filter_by(slug=str(slug), status="active").first()
        if c:
            return c
    c = (db.query(models.Clinic).filter_by(status="active")
         .order_by(models.Clinic.id).first())
    if not c:
        raise HTTPException(status_code=404, detail="No clinic is available")
    return c


# --------------------------------------------------------------------------
#  session
# --------------------------------------------------------------------------
def current_customer(db: Session = Depends(get_db),
                     cust_session: str | None = Cookie(default=None)) -> models.Customer:
    """The signed-in customer, or 401. Follows a merge so someone whose record was
    consolidated into a golden record keeps reaching their own (merged) data."""
    cid = read_customer_session(cust_session)
    cust = db.get(models.Customer, cid) if cid else None
    while cust and cust.merged_into_id:
        nxt = db.get(models.Customer, cust.merged_into_id)
        if not nxt or nxt.id == cust.id:
            break
        cust = nxt
    if not cust:
        raise HTTPException(status_code=401, detail="Please sign in")
    return cust


def customer_public(db: Session, c: models.Customer) -> dict:
    branch = db.get(models.Branch, c.branch_id) if c.branch_id else None
    return {
        "id": c.id, "name": c.name, "nickname": c.nickname, "phone": c.phone,
        "email": c.email, "avatar": c.avatar,
        "branch_id": c.branch_id, "branch_name": branch.name if branch else None,
        "member_since": c.created_at.isoformat() if c.created_at else None,
        "clinic_id": c.clinic_id,
    }


def _set_session(response: Response, customer_id: int) -> None:
    response.set_cookie(CUSTOMER_COOKIE, make_customer_session(customer_id),
                        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")


# --------------------------------------------------------------------------
#  public: the landing page's data
# --------------------------------------------------------------------------
@router.get("/home")
def home(slug: str = "", db: Session = Depends(get_db)) -> dict:
    """Everything the marketing page shows. Public on purpose, but it publishes
    ONLY catalog content — never a customer, a booking or a conversation."""
    clinic = portal_clinic(db, slug)
    cid = clinic.id

    branches = scoped(db, models.Branch, cid).order_by(models.Branch.id).all()
    services = (scoped(db, models.Service, cid).filter_by(active=True)
                .order_by(models.Service.category, models.Service.base_price).all())
    doctors = (scoped(db, models.StaffMember, cid)
               .filter_by(active=True, role="doctor").order_by(models.StaffMember.id).all())
    now = datetime.utcnow()
    promos = [p for p in scoped(db, models.Promotion, cid).all()
              if (p.valid_from is None or p.valid_from <= now)
              and (p.valid_to is None or p.valid_to >= now)]
    svc_by_id = {s.id: s for s in services}

    return {
        "clinic": {"name": clinic.name, "slug": clinic.slug, "tagline": clinic.tagline,
                   "logo": clinic.logo, "cover": clinic.cover, "accent": clinic.accent},
        "branches": [{"id": b.id, "name": b.name, "phone": b.phone, "address": b.address,
                      "hours": branch_days(b)} for b in branches],
        "categories": sorted({s.category for s in services if s.category}),
        "services": [{"id": s.id, "name": s.name, "category": s.category,
                      "price": s.base_price, "duration_min": s.duration_min,
                      "image": s.image, "description": s.description}
                     for s in services],
        "promotions": [{"id": p.id, "title": p.title, "detail": p.detail,
                        "label": p.discount_label, "promo_price": p.promo_price,
                        "service_name": (svc_by_id[p.service_id].name
                                         if p.service_id in svc_by_id else None),
                        "valid_to": p.valid_to.isoformat() if p.valid_to else None}
                       for p in promos],
        "doctors": [{"id": d.id, "name": d.name, "title": d.title, "bio": d.bio,
                     "avatar": d.avatar} for d in doctors],
    }


# --------------------------------------------------------------------------
#  auth
# --------------------------------------------------------------------------
class RegisterIn(BaseModel):
    name: str
    phone: str
    password: str
    email: str = ""
    clinic: str = ""


class LoginIn(BaseModel):
    phone: str
    password: str
    clinic: str = ""


def _clean_phone(raw: str) -> str:
    """A Thai mobile number, normalised to 0XXXXXXXXX, or '' if it isn't one.

    Deliberately strict rather than clever: the phone IS the login identifier, so
    'close enough' matching here would let two people resolve to one account."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("66") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if len(digits) == 10 and digits.startswith("0") else ""


def _find_by_phone(db: Session, clinic_id: int, phone: str) -> list[models.Customer]:
    """Live (non-merged) customers in this clinic whose number matches, compared on
    ``inbox.phone_key`` so 081.../+6681... are one person — the same key the
    duplicate finder and the AI's identity check use."""
    key = phone_key(phone)
    if not key:
        return []
    return [c for c in scoped(db, models.Customer, clinic_id).all()
            if c.merged_into_id is None and phone_key(c.phone) == key]


@router.post("/register")
def register(data: RegisterIn, response: Response, db: Session = Depends(get_db)):
    """Create a portal login, or claim the CRM record that already holds this phone.

    **Claiming is the security-sensitive half.** A customer who has chatted with
    the AI already exists here, with their bookings and payments — so a new
    registration that ignored that record would show them an empty account, while
    one that attaches to it hands over whatever that record holds. We attach only
    when the number matches EXACTLY ONE live record that has no password yet, and
    refuse (409) when it matches several, which is the ambiguous case a human must
    resolve.

    This still trusts that whoever typed the number owns it. That is acceptable
    only because there is no SMS/OTP provider wired up: **a production deployment
    must verify the number with a one-time code before this route attaches an
    existing record**, otherwise knowing someone's phone number is enough to read
    their visit history. Flagged here rather than in a ticket because the fix
    belongs exactly at this line.
    """
    clinic = portal_clinic(db, data.clinic)
    name = (data.name or "").strip()[:120]
    phone = _clean_phone(data.phone)
    if not name:
        raise HTTPException(status_code=400, detail="กรุณากรอกชื่อ")
    if not phone:
        raise HTTPException(status_code=400, detail="เบอร์โทรไม่ถูกต้อง (ตัวอย่าง 0812345678)")
    if len(data.password or "") < MIN_PASSWORD:
        raise HTTPException(status_code=400,
                            detail=f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD} ตัวอักษร")

    matches = _find_by_phone(db, clinic.id, phone)
    if any(c.password_hash for c in matches):
        raise HTTPException(status_code=409, detail="เบอร์นี้มีบัญชีอยู่แล้ว กรุณาเข้าสู่ระบบ")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="พบข้อมูลลูกค้าซ้ำกันสำหรับเบอร์นี้ กรุณาติดต่อทีมงานเพื่อยืนยันตัวตนค่ะ")

    if matches:                      # claim the existing CRM record (see docstring)
        cust = matches[0]
        if name:
            cust.name = name
    else:
        cust = models.Customer(
            clinic_id=clinic.id, name=name, phone=phone, channel="web",
            channel_user_id="portal_" + phone, pipeline_stage="new_lead",
            temperature="warm", lead_score=20)
        db.add(cust)
        db.flush()
        db.add(models.Activity(clinic_id=clinic.id, customer_id=cust.id, type="system",
                               summary="New lead registered on the customer portal"))
    cust.phone = phone
    if (data.email or "").strip():
        cust.email = data.email.strip()[:160]
    cust.password_hash = hash_password(data.password)
    db.commit()

    _set_session(response, cust.id)
    return customer_public(db, cust)


@router.post("/login")
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    clinic = portal_clinic(db, data.clinic)
    phone = _clean_phone(data.phone)
    cust = next((c for c in _find_by_phone(db, clinic.id, phone) if c.password_hash), None)
    if not cust or not verify_password(data.password, cust.password_hash):
        # One message for both cases: saying "no such number" would turn this route
        # into a way to test which phone numbers are the clinic's customers.
        raise HTTPException(status_code=401, detail="เบอร์โทรหรือรหัสผ่านไม่ถูกต้อง")
    _set_session(response, cust.id)
    return customer_public(db, cust)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(CUSTOMER_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(db: Session = Depends(get_db), cust: models.Customer = Depends(current_customer)):
    return customer_public(db, cust)


class ProfileIn(BaseModel):
    name: str | None = None
    nickname: str | None = None
    email: str | None = None


@router.patch("/me")
def update_me(data: ProfileIn, db: Session = Depends(get_db),
              cust: models.Customer = Depends(current_customer)):
    """Profile edits a customer may make themselves. The phone is NOT editable here:
    it is the login identifier and the key every other record is matched on, so
    changing it is a staff action after verifying who is asking."""
    if data.name is not None and data.name.strip():
        cust.name = data.name.strip()[:120]
    if data.nickname is not None:
        cust.nickname = data.nickname.strip()[:120]
    if data.email is not None:
        cust.email = data.email.strip()[:160]
    db.commit()
    return customer_public(db, cust)


# --------------------------------------------------------------------------
#  account data
# --------------------------------------------------------------------------
@router.get("/bookings")
def my_bookings(db: Session = Depends(get_db),
                cust: models.Customer = Depends(current_customer)) -> dict:
    """This customer's own appointments, newest first.

    Filtered by ``customer_id`` AND clinic, never by anything the client sends.
    """
    rows = (scoped(db, models.Booking, cust.clinic_id)
            .filter_by(customer_id=cust.id)
            .order_by(models.Booking.slot_at.desc()).all())
    svc = {s.id: s for s in scoped(db, models.Service, cust.clinic_id).all()}
    br = {b.id: b for b in scoped(db, models.Branch, cust.clinic_id).all()}
    docs = {d.id: d for d in scoped(db, models.StaffMember, cust.clinic_id).all()}
    paid_ids = {p.booking_id for p in scoped(db, models.Payment, cust.clinic_id)
                .filter_by(customer_id=cust.id, status="paid").all()}
    now = datetime.utcnow() + timedelta(hours=7)   # clinic wall clock, like slot_at

    out = []
    for b in rows:
        s, brow = svc.get(b.service_id), br.get(b.branch_id)
        out.append({
            "id": b.id,
            "service_name": s.name if s else "—",
            "service_image": s.image if s else "",
            "branch_name": brow.name if brow else "—",
            "branch_address": brow.address if brow else "",
            "doctor_name": docs[b.doctor_id].name if b.doctor_id in docs else None,
            "slot_at": b.slot_at.isoformat() if b.slot_at else None,
            "status": b.status,
            "price": b.price, "deposit_required": b.deposit_required,
            "deposit_paid": b.id in paid_ids,
            "hold_expires_at": b.hold_expires_at.isoformat() if b.hold_expires_at else None,
            "upcoming": bool(b.slot_at and b.slot_at >= now
                             and b.status in ("pending", "confirmed")),
        })
    return {"bookings": out}


@router.get("/payments")
def my_payments(db: Session = Depends(get_db),
                cust: models.Customer = Depends(current_customer)) -> dict:
    rows = (scoped(db, models.Payment, cust.clinic_id)
            .filter_by(customer_id=cust.id)
            .order_by(models.Payment.id.desc()).limit(50).all())
    svc = {s.id: s for s in scoped(db, models.Service, cust.clinic_id).all()}
    bk = {b.id: b for b in scoped(db, models.Booking, cust.clinic_id)
          .filter_by(customer_id=cust.id).all()}
    out = []
    for p in rows:
        b = bk.get(p.booking_id)
        s = svc.get(b.service_id) if b else None
        # No payment QR here: an unpaid balance is shown as a status, and the customer
        # pays from the QR in chat, where the assistant states the amount owed.
        out.append({"id": p.id, "amount": p.amount, "status": p.status,
                    "type": p.type, "service_name": s.name if s else None,
                    "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                    "created_at": p.created_at.isoformat() if p.created_at else None})
    return {"payments": out, "ltv": cust.ltv}


@router.get("/treatments")
def my_treatment_prices(db: Session = Depends(get_db),
                        cust: models.Customer = Depends(current_customer)) -> dict:
    """The catalog priced for THIS customer's branch, so the portal never shows a
    figure the booking flow would then contradict. Resolution goes through
    ``booking.resolved_price``/``deposit_for`` — the same readers the AI's tools
    use — rather than reading ``base_price`` directly."""
    services = (scoped(db, models.Service, cust.clinic_id).filter_by(active=True)
                .order_by(models.Service.category).all())
    out = []
    for s in services:
        price = resolved_price(db, cust.clinic_id, s, cust.branch_id)
        out.append({"id": s.id, "name": s.name, "category": s.category,
                    "image": s.image, "duration_min": s.duration_min,
                    "price": price, "deposit": deposit_for(s, price)})
    return {"treatments": out}


@router.post("/chat")
def my_chat(background_tasks: BackgroundTasks, data: dict = Body(default={}),
            db: Session = Depends(get_db),
            cust: models.Customer = Depends(current_customer)) -> dict:
    """Open (or resume) this customer's own web conversation and hand back a chat
    token for the existing widget transport.

    The token is minted from the conversation we just resolved from the SESSION, so
    a signed-in customer cannot ask for someone else's thread.

    ``{"new": true}`` is the widget's "start a new chat" button: it opens a fresh
    conversation for the SAME customer instead of resuming. The old thread is kept
    (the clinic's inbox still holds it); because resuming takes the newest web
    conversation, the fresh one is also what the next visit comes back to.
    """
    conv = None
    if not data.get("new"):
        conv = (scoped(db, models.Conversation, cust.clinic_id)
                .filter_by(customer_id=cust.id, channel="web")
                .order_by(models.Conversation.id.desc()).first())
    created = False
    if not conv:
        conv = models.Conversation(clinic_id=cust.clinic_id, customer_id=cust.id,
                                   channel="web", status="new_lead",
                                   sales_stage="greeting",
                                   last_message_at=datetime.utcnow())
        db.add(conv)
        db.flush()
        greeting = models.Message(
            clinic_id=cust.clinic_id, conversation_id=conv.id, sender="ai",
            text=f"สวัสดีค่ะคุณ{cust.nickname or cust.name} 🌿 "
                 "ยินดีต้อนรับกลับมานะคะ สนใจบริการไหนเป็นพิเศษ หรือต้องการจองคิวแจ้งได้เลยค่ะ")
        db.add(greeting)
        created = True
    db.commit()
    if created:
        realtime.publish({"type": "conversation", "conversation_id": conv.id,
                          "clinic_id": cust.clinic_id,
                          "summary": conv_summary(db, conv)})
    return {"token": make_chat_token(conv.id), "conversation_id": conv.id}
