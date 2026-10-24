"""Demo data seeding for Blinks Bright — multi-clinic.

``seed_if_empty`` runs on startup and builds **three** demo clinics, each a
separate business with its own branches, staff, catalog, knowledge base,
customers, conversations, bookings, payments and automations.

``provision_clinic`` builds one immediately-usable clinic (clinic + branches +
starter catalog/KB/automations/channels) and is reused by the "add clinic" API.
"""
import json
import random
import re
from datetime import datetime, timedelta

from app import models
from app.database import SessionLocal
from app.security import hash_password

RND = random.Random(42)          # deterministic seed for reproducible demos
NOW = datetime.utcnow().replace(microsecond=0)  # anchor the dataset to real "today"
# The per-day shape Settings writes and everything reads. It used to be the legacy
# {"weekday": ..., "weekend": ...} pair, which only the Settings card ever parsed — so
# every clinic seeded from here started life with hours the AI and the availability
# engine could not see properly.
HOURS_JSON = json.dumps({"days": {
    **{d: {"open": "10:00", "close": "20:00"} for d in
       ("mon", "tue", "wed", "thu", "fri")},
    "sat": {"open": "10:00", "close": "19:00"},
    "sun": {"open": "10:00", "close": "19:00"},
}})

FIRST = ["Ploy", "Mint", "Fah", "Nan", "Bee", "Aof", "Mook", "Praew", "Tan", "Nut",
         "Jin", "May", "Fern", "Earn", "Bow", "Gift", "Pim", "Got", "Beam", "Aim",
         "View", "Net", "Toey", "Som", "Ying", "Noon", "Ice", "Mild", "Belle", "Petch",
         "Proud", "Maprang", "Nink", "Cherry", "Namo", "Title", "Khao", "Mhee", "Care", "Pun"]
LAST = ["Suwannarat", "Chaiyaphat", "Wongchai", "Srisuk", "Phongphan", "Rattana",
        "Boonmee", "Thanarat", "Intra", "Saetang", "Kittisak", "Mahachai", "Charoensuk",
        "Areerat", "Phitak", "Sombat", "Nakarin", "Veerasak"]

STAGES = (["new_lead"] * 45 + ["interested"] * 38 + ["booked"] * 22
          + ["paid"] * 25 + ["followup"] * 15 + ["lost"] * 5)
CHANNELS = ["web"]


# ============================================================
#  Catalog / KB templates (shared by every provisioned clinic)
# ============================================================
SERVICE_DATA = [
    ("Botox — Jaw Slimming", "Injectables", 8900, 45, 120, "treatment-botox",
     "Relaxes the masseter muscle for a slimmer, softer jawline. Results settle in 2 weeks.",
     "Avoid alcohol and blood thinners 24h before. Come with a clean face.",
     "No lying down or exercise for 4 hours. Avoid facials for 1 week.",
     "Not suitable while pregnant or breastfeeding, or with neuromuscular disorders."),
    ("Botox — Wrinkle Relax", "Injectables", 7500, 30, 120, "treatment-botox",
     "Softens forehead lines, frown lines and crow's feet for a refreshed look.",
     "Avoid alcohol 24h before. Inform staff of any recent fillers.",
     "Stay upright 4 hours. Avoid heat treatments for 1 week.",
     "Not suitable while pregnant or breastfeeding."),
    ("Dermal Filler — Cheek & Chin", "Injectables", 12500, 45, 300, "treatment-filler",
     "Hyaluronic-acid filler restores volume and refines facial contour.",
     "Avoid alcohol and blood thinners 24h before.",
     "Mild swelling for 2-3 days is normal. Avoid pressure on the area.",
     "Not suitable with active skin infection or autoimmune flare-ups."),
    ("Skin Booster", "Injectables", 9500, 40, 30, "treatment-skinbooster",
     "Micro-injections of hyaluronic acid for deep hydration and natural glow.",
     "Arrive with a clean face. Avoid retinol 3 days before.",
     "Tiny bumps may last 24h. Use gentle skincare for 3 days.",
     "Not suitable with active acne breakout in the area."),
    ("HIFU Lifting", "Lifting", 25000, 60, 365, "treatment-room",
     "High-intensity focused ultrasound lifts and tightens without downtime.",
     "Remove makeup. Inform staff of metal implants.",
     "Mild redness for a few hours. Results build over 8-12 weeks.",
     "Not suitable while pregnant or with metal implants in the area."),
    ("Pico Laser — Brightening", "Laser", 4500, 30, 30, "treatment-laser",
     "Picosecond laser fades dark spots, melasma and dullness.",
     "Avoid sun exposure and retinol 3 days before.",
     "Apply SPF50 daily. Avoid scrubs for 5 days.",
     "Not suitable with active sunburn or photosensitive medication."),
    ("Signature Facial", "Facial", 2800, 60, 30, "treatment-facial",
     "Deep-cleansing signature facial with extraction and hydration.",
     "No special preparation needed.",
     "Skin may be slightly pink for an hour. Use SPF.",
     "Let staff know about any active skin allergies."),
    ("Mesotherapy — Glow", "Injectables", 6500, 40, 30, "treatment-skinbooster",
     "Nutrient cocktail micro-injected for brightening and firmness.",
     "Arrive with a clean face.",
     "Avoid makeup for 12 hours.",
     "Not suitable while pregnant or breastfeeding."),
    ("Thread Lift", "Lifting", 35000, 75, 540, "treatment-room",
     "Absorbable threads lift sagging skin and stimulate collagen.",
     "Avoid blood thinners 5 days before. Arrange a rest day after.",
     "Avoid wide mouth movements and facials for 2 weeks.",
     "Not suitable with active infection or autoimmune disorders."),
    ("Acne Clear Program", "Facial", 3500, 50, 21, "treatment-facial",
     "Targeted acne treatment with extraction, blue light and care plan.",
     "Avoid harsh exfoliants 2 days before.",
     "Follow the home-care routine. Avoid picking.",
     "Inform staff if on oral acne medication."),
]

KB_DATA = [
    ("faq", "How do I book an appointment?",
     "You can book directly in chat — tell us the treatment and your preferred date, "
     "and our assistant will offer available time slots. A deposit confirms the booking."),
    ("faq", "What payment methods do you accept?",
     "We accept credit/debit card and PromptPay QR through a secure payment link. "
     "A deposit is required to confirm a booking; the balance is paid at the clinic."),
    # Deliberately NO times here: every branch's real hours already reach the AI in the
    # BRANCHES block, and a second copy in the KB goes stale the first time a clinic
    # edits its schedule — which is exactly how the assistant ended up quoting hours
    # nobody had set.
    ("faq", "What are your opening hours?",
     "Opening hours differ by branch, and each branch's exact days and times are listed "
     "with its name and address. Check the branch the customer asks about."),
    ("faq", "Do you have parking?",
     "Yes — every branch has complimentary customer parking."),
    ("policy", "Deposit & cancellation policy",
     "A deposit (generally about 20% of the treatment price, and specific to the exact "
     "treatment and branch) confirms each booking. Rescheduling is free with 24 hours "
     "notice. Cancellations within 24 hours forfeit the deposit."),
    ("policy", "Refund policy",
     "Deposits are transferable to another date or treatment. Unused package sessions "
     "are refundable within 30 days of purchase."),
    ("prep", "General preparation before treatment",
     "Arrive with a clean face where possible. Avoid alcohol and blood thinners 24 "
     "hours before injectable treatments. Tell staff about medication and allergies."),
    ("aftercare", "General aftercare advice",
     "Apply SPF50 daily, avoid heat treatments (sauna, hot yoga) for one week, and "
     "keep the treated area clean. Contact the clinic if you have unusual swelling."),
    ("aftercare", "Aftercare for injectables",
     "Stay upright for 4 hours, avoid exercise for 24 hours, and do not massage the "
     "treated area. Mild bruising can be covered with makeup after 24 hours."),
    ("general", "Are treatments safe?",
     "All treatments are performed by board-certified physicians using approved "
     "products. A consultation assesses suitability before any procedure."),
    ("general", "Consultation",
     "A consultation with our physician is complimentary and recommended before a "
     "first treatment. It can be combined with your first appointment."),
    ("faq", "Do you offer memberships?",
     "Yes — members earn points on every visit, unlock tier pricing, and receive "
     "birthday rewards. Ask our assistant to explain the current tiers."),
]

AUTOMATION_DATA = [
    ("pre_appointment", "Appointment reminder",
     "Remind customers 1 day before their appointment.", {"offset_days": -1}),
    ("followup_d1", "Day 1 check-in",
     "Check on the customer 1 day after treatment.", {"offset_days": 1}),
    ("followup_d7", "Day 7 feedback",
     "Ask for feedback 7 days after treatment.", {"offset_days": 7}),
    ("followup_d14", "Day 14 next step",
     "Recommend aftercare or next treatment on day 14.", {"offset_days": 14}),
    ("treatment_due", "Treatment-due reminder",
     "Remind customers when a treatment is due again.", {"use_service_interval": True}),
    ("winback", "Win-back campaign",
     "Re-engage customers inactive for 120 days.", {"inactive_days": 120}),
    ("lead_nurture", "Unbooked lead nudge",
     "Nudge interested leads who haven't booked after 3 quiet days.", {"quiet_days": 3}),
    ("birthday", "Birthday reward",
     "Send a birthday offer on the customer's birthday.", {"offset_days": 0}),
    ("package_expiry", "Package expiring soon",
     "Alert customers 14 days before a package expires.", {"offset_days": -14}),
]

INTENT_QUESTIONS = {
    "pricing": ["Pico Laser ราคาเท่าไหร่คะ", "Botox กรามกี่บาทคะ",
                "Skin Booster เริ่มต้นเท่าไหร่", "HIFU ราคาประมาณเท่าไหร่คะ",
                "Signature Facial ราคาเท่าไหร่คะ", "ร้อยไหมแพงไหมคะ"],
    "booking": ["ขอจองคิววันเสาร์ได้ไหมคะ", "พรุ่งนี้บ่ายว่างไหมคะ",
                "อยากจองคิวทำเลเซอร์ค่ะ", "จองคิวปรึกษาคุณหมอได้ไหมคะ"],
    "service_info": ["Botox กรามอยู่ได้นานแค่ไหนคะ", "ฟิลเลอร์เจ็บไหมคะ",
                     "HIFU คืออะไรคะ", "Skin Booster ช่วยเรื่องอะไรบ้าง"],
    "promotion": ["ตอนนี้มีโปรอะไรบ้างคะ", "มีส่วนลดสำหรับลูกค้าใหม่ไหมคะ",
                  "โปรเดือนนี้มีอะไรบ้างคะ"],
    "prep_aftercare": ["ก่อนทำ Botox ต้องเตรียมตัวยังไงคะ",
                       "หลังทำฟิลเลอร์ห้ามทำอะไรบ้าง", "ดูแลผิวหลังเลเซอร์ยังไงคะ"],
    "greeting": ["สวัสดีค่ะ สนใจบริการค่ะ", "หวัดดีค่ะ"],
    "other": ["คลินิกอยู่ตรงไหนคะ", "เปิดกี่โมงคะ", "มีที่จอดรถไหมคะ"],
    "unknown": ["ทำแล้วหน้าจะเด้งทันทีเลยไหมคะ", "อันนี้ต่างกับของอีกที่ยังไง",
                "ผ่อน 0% ได้ไหมคะ", "ใช้ประกันได้ไหม", "ขอคุยกับคนที่เคยทำหน่อยค่ะ"],
}


# ============================================================
#  Entry point
# ============================================================
def seed_if_empty() -> None:
    """On a fresh database, create this project's own clinic (app/seed_main.py)."""
    db = SessionLocal()
    try:
        if db.query(models.Clinic).first():
            return
        from app.seed_main import ensure_main
        ensure_main(db)
        db.commit()
        print("[seed] Blinks Bright demo dataset created")
    except Exception as exc:  # pragma: no cover
        db.rollback()
        print("[seed] error:", exc)
        raise
    finally:
        db.close()


# ============================================================
#  provision_clinic — a complete, usable clinic
# ============================================================
def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s or "clinic")[:60]


def _unique_slug(db, name: str) -> str:
    base = _slugify(name)
    slug, i = base, 2
    while db.query(models.Clinic).filter_by(slug=slug).first():
        slug = f"{base}-{i}"
        i += 1
    return slug


def provision_clinic(db, name, *, slug=None, tagline="", logo="", accent="",
                     branches=None, services=None, kb=None, promos=None,
                     doctors=None, starter=True) -> models.Clinic:
    """Create a clinic with a default branch + channels, plus optional content.

    Returns the clinic; the caller commits. Used by both the demo seed and the
    "add clinic" API.

    The catalog/KB default to the shared starter templates, but callers can pass
    real, clinic-specific data (``services``/``kb``/``promos``/``doctors``) — same
    row shapes as the templates — to provision a real clinic with real content.

    ``starter`` controls whether the demo template content (treatments,
    promotions, KB, automations) is filled in. A console-created clinic passes
    ``starter=False`` to **begin empty** — only a default branch and channels —
    so the owner builds their own menu from scratch.
    """
    clinic = models.Clinic(
        name=name, slug=slug or _unique_slug(db, name), tagline=tagline,
        logo=logo, accent=accent, status="active",
    )
    db.add(clinic)
    db.flush()

    specs = branches or [("Main Branch", "MAIN", "", "")]
    branch_rows = [
        models.Branch(clinic_id=clinic.id, name=bn, code=bc, phone=bp,
                      address=ba, hours=HOURS_JSON)
        for (bn, bc, bp, ba) in specs
    ]
    db.add_all(branch_rows)
    db.flush()

    # Explicit data always provisions; the starter templates only fill in when
    # `starter` is on, so a console-created clinic (starter=False) begins empty.
    if services is not None or starter:
        service_rows = _services(db, clinic, services)
        _service_prices(db, clinic, service_rows, branch_rows)
    else:
        service_rows = []
    if promos is not None or starter:
        _promotions(db, clinic, service_rows, specs=promos)
    if kb is not None or starter:
        _kb_articles(db, clinic, kb)
    # Every clinic gets the default automation rule set — there is no create UI
    # (only GET/PATCH toggles), so a clinic provisioned without rules could never
    # enable reminders / follow-ups / win-back at all.
    _automation_rules(db, clinic)
    _channels(db, clinic)
    if doctors:
        _doctors(db, clinic, branch_rows, doctors)
    return clinic


def _services(db, clinic, data=None):
    rows = [
        models.Service(
            clinic_id=clinic.id, name=name, category=cat, base_price=price,
            duration_min=dur, recommended_interval_days=interval,
            image=f"/assets/images/{img}.png", description=desc, prep_notes=prep,
            aftercare_notes=after, contraindications=contra, active=True,
        )
        for (name, cat, price, dur, interval, img, desc, prep, after, contra)
        in (data or SERVICE_DATA)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def _doctors(db, clinic, branches, data):
    """Create clinical StaffMember doctors (the Doctors & Staff roster, surfaced in
    the KB + assignable to bookings) from ``(name, title, bio)`` specs. These are
    NOT login accounts — separate from ``User``."""
    rows = [
        models.StaffMember(
            clinic_id=clinic.id, name=dname, role="doctor", title=dtitle, bio=dbio,
            branch_id=branches[i % len(branches)].id, active=True,
        )
        for i, (dname, dtitle, dbio) in enumerate(data)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def _staff_members(db, clinic, branches):
    """A clinical roster (a doctor + a therapist per branch) for demo clinics —
    shown in Doctors & Staff and assigned to bookings."""
    rows = []
    for b in branches:
        rows.append(models.StaffMember(
            clinic_id=clinic.id, name=f"Dr. {RND.choice(FIRST)} {RND.choice(LAST)}",
            role="doctor", title="Aesthetic Physician", branch_id=b.id, active=True))
        rows.append(models.StaffMember(
            clinic_id=clinic.id, name=f"{RND.choice(FIRST)} {RND.choice(LAST)}",
            role="therapist", title="Aesthetic Therapist", branch_id=b.id, active=True))
    db.add_all(rows)
    db.flush()
    return rows


def _service_prices(db, clinic, services, branches):
    factors = [1.0, 1.08, 0.94]
    rows = []
    for s in services:
        for idx, b in enumerate(branches):
            rows.append(models.ServicePrice(
                clinic_id=clinic.id, service_id=s.id, branch_id=b.id,
                price=round(s.base_price * factors[idx % 3] / 100) * 100,
            ))
    db.add_all(rows)
    db.flush()


DEFAULT_PROMOS = [
    {"title": "Glow Season — 20% off Pico Laser",
     "detail": "Brighten up for the season. 20% off all Pico Laser sessions.",
     "service": "Pico Laser — Brightening", "discount_label": "20% off",
     "promo_price": 3600, "from_days": 10, "to_days": 20},
    {"title": "Botox + Filler Bundle",
     "detail": "Book Jaw Botox with Cheek Filler and save ฿3,000.",
     "discount_label": "Save ฿3,000", "from_days": 5, "to_days": 40},
    {"title": "First Skin Booster ฿7,900",
     "detail": "New customers: first Skin Booster session at ฿7,900.",
     "service": "Skin Booster", "discount_label": "New customer",
     "promo_price": 7900, "from_days": 20, "to_days": 30},
    {"title": "HIFU Intro Offer ฿19,900",
     "detail": "Experience HIFU Lifting at a special introductory price.",
     "service": "HIFU Lifting", "discount_label": "Intro offer",
     "promo_price": 19900, "from_days": 8, "to_days": 22},
    {"title": "Facial Membership Month",
     "detail": "Sign up for a 6-session Signature Facial package and get 1 free.",
     "service": "Signature Facial", "discount_label": "6 + 1 free",
     "from_days": 3, "to_days": 27},
]


def _promotions(db, clinic, services, specs=None):
    """Create promotions from specs (defaults to the starter template). Each spec:
    {title, detail, service?(name), discount_label, promo_price?, from_days, to_days}."""
    by_name = {s.name: s for s in services}
    rows = []
    for sp in (DEFAULT_PROMOS if specs is None else specs):
        svc = by_name.get(sp.get("service"))
        rows.append(models.Promotion(
            clinic_id=clinic.id, title=sp["title"], detail=sp.get("detail", ""),
            service_id=svc.id if svc else None,
            discount_label=sp.get("discount_label", ""),
            promo_price=sp.get("promo_price"),
            valid_from=NOW - timedelta(days=sp.get("from_days", 5)),
            valid_to=NOW + timedelta(days=sp.get("to_days", 30)),
        ))
    db.add_all(rows)
    db.flush()


def _kb_articles(db, clinic, data=None):
    rows = [models.KBArticle(clinic_id=clinic.id, type=t, title=ti, content=c)
            for t, ti, c in (data or KB_DATA)]
    db.add_all(rows)
    db.flush()


def _automation_rules(db, clinic):
    rows = [models.AutomationRule(clinic_id=clinic.id, type=t, name=n,
                                  description=d, config=cfg)
            for t, n, d, cfg in AUTOMATION_DATA]
    db.add_all(rows)
    db.flush()


def _channels(db, clinic):
    rows = [
        models.ChannelIntegration(clinic_id=clinic.id, channel="web", enabled=True,
                                  config={"widget_title": "Chat with us"}),
    ]
    db.add_all(rows)
    db.flush()


# ============================================================
#  Staff
# ============================================================
def _staff(db, clinic, demo_logins: bool):
    """Clinic staff. ``demo_logins`` → the documented demo accounts; otherwise
    generated per-branch staff with clinic-prefixed emails."""
    pw = hash_password("demo1234")
    branches = db.query(models.Branch).filter_by(clinic_id=clinic.id).all()
    rows = []
    if demo_logins:
        rows = [
            models.User(clinic_id=clinic.id, name="Jamsai Chonikarn", email=OWNER_EMAIL,
                        password_hash=pw, role="owner", title="Clinic Owner"),
            models.User(clinic_id=clinic.id, name="System Admin", email="admin@clinic.co",
                        password_hash=pw, role="super_admin", title="Super Admin"),
            models.User(clinic_id=clinic.id, name="Mei Lin", email="manager@clinic.co",
                        password_hash=pw, role="branch_manager", title="Branch Manager",
                        branch_id=branches[0].id),
            models.User(clinic_id=clinic.id, name="Ploy Suwan", email="sales@clinic.co",
                        password_hash=pw, role="sales", title="Senior Sales Consultant",
                        branch_id=branches[0].id),
            models.User(clinic_id=clinic.id, name="Dr. Anan Veera", email="doctor@clinic.co",
                        password_hash=pw, role="doctor", title="Aesthetic Physician",
                        bio="Board-certified, 12 years in injectables and laser.",
                        branch_id=branches[0].id),
            models.User(clinic_id=clinic.id, name="Tar Wong", email="marketing@clinic.co",
                        password_hash=pw, role="marketing", title="Marketing Lead"),
            models.User(clinic_id=clinic.id, name="Nok Aree", email="sales2@clinic.co",
                        password_hash=pw, role="sales", title="Sales Consultant",
                        branch_id=branches[1 % len(branches)].id),
            models.User(clinic_id=clinic.id, name="Dr. Siri Pong", email="doctor2@clinic.co",
                        password_hash=pw, role="doctor", title="Aesthetic Physician",
                        bio="Specialist in thread lifts and HIFU.",
                        branch_id=branches[1 % len(branches)].id),
            models.User(clinic_id=clinic.id, name="Fah Mali", email="sales3@clinic.co",
                        password_hash=pw, role="sales", title="Sales Consultant",
                        branch_id=branches[2 % len(branches)].id),
            models.User(clinic_id=clinic.id, name="Dr. Ploy Narin", email="doctor3@clinic.co",
                        password_hash=pw, role="doctor", title="Aesthetic Physician",
                        bio="Skin and laser specialist.",
                        branch_id=branches[2 % len(branches)].id),
        ]
    else:
        for i, b in enumerate(branches):
            rows += [
                models.User(clinic_id=clinic.id, name=f"{RND.choice(FIRST)} {RND.choice(LAST)}",
                            email=f"{clinic.slug}.manager{i}@clinic.co", password_hash=pw,
                            role="branch_manager", title="Branch Manager", branch_id=b.id),
                models.User(clinic_id=clinic.id, name=f"{RND.choice(FIRST)} {RND.choice(LAST)}",
                            email=f"{clinic.slug}.sales{i}@clinic.co", password_hash=pw,
                            role="sales", title="Sales Consultant", branch_id=b.id),
                models.User(clinic_id=clinic.id, name=f"Dr. {RND.choice(FIRST)} {RND.choice(LAST)}",
                            email=f"{clinic.slug}.doctor{i}@clinic.co", password_hash=pw,
                            role="doctor", title="Aesthetic Physician", branch_id=b.id),
            ]
    db.add_all(rows)
    db.flush()
    return rows


# ============================================================
#  Per-clinic demo data
# ============================================================
def _seed_clinic_demo(db, clinic, staff, scale: float) -> None:
    branches = db.query(models.Branch).filter_by(clinic_id=clinic.id).all()
    services = db.query(models.Service).filter_by(clinic_id=clinic.id).all()
    # clinical roster (StaffMembers) — separate from the login Users in `staff`
    team = (db.query(models.StaffMember).filter_by(clinic_id=clinic.id).all()
            or _staff_members(db, clinic, branches))
    doctors = [m for m in team if m.role == "doctor"]
    n = max(int(round(150 * scale)), 14)
    customers = _customers(db, clinic, branches, staff, n)
    _conversations(db, clinic, customers)
    _intent_logs(db, clinic, scale)
    bookings = _bookings(db, clinic, customers, services, branches, doctors)
    _payments(db, clinic, bookings, customers)
    _memberships_packages(db, clinic, customers, services)
    _reminders(db, clinic, customers, bookings, services)
    _activities(db, clinic, customers)


def _customers(db, clinic, branches, staff, n):
    sales = [u for u in staff if u.role in ("sales", "branch_manager")]
    rows = []
    used_names = set()
    for i in range(n):
        while True:
            name = f"{RND.choice(FIRST)} {RND.choice(LAST)}"
            if name not in used_names:
                used_names.add(name)
                break
        stage = RND.choice(STAGES)
        channel = RND.choice(CHANNELS)
        branch = RND.choice(branches)
        created = NOW - timedelta(days=RND.randint(0, 75), hours=RND.randint(0, 12))
        temp = ("hot" if stage in ("booked", "paid") else
                "warm" if stage in ("interested", "followup") else
                RND.choice(["cold", "warm"]))
        score = {"new_lead": (15, 40), "interested": (40, 68), "booked": (68, 88),
                 "paid": (78, 97), "followup": (60, 85), "lost": (5, 22)}[stage]
        budget = RND.choice(["5,000-15,000", "15,000-30,000", "30,000-60,000", "60,000+", ""])
        if i in (3, 4):
            bday = NOW.replace(year=NOW.year - RND.randint(24, 46))
        else:
            bday = NOW - timedelta(days=RND.randint(8000, 19000))
        treated = stage in ("paid", "followup", "lost") or RND.random() < 0.3
        last_treat = NOW - timedelta(days=RND.randint(6, 330)) if treated else None
        rows.append(models.Customer(
            clinic_id=clinic.id, name=name, phone=f"08{RND.randint(10000000, 99999999)}",
            email=f"{name.split()[0].lower()}{RND.randint(1, 99)}@email.com",
            channel=channel, channel_user_id=f"{channel}_{clinic.id}_{1000 + i}",
            branch_id=branch.id, pipeline_stage=stage, temperature=temp,
            lead_score=RND.randint(*score), budget=budget, birthday=bday,
            assigned_user_id=RND.choice(sales).id if sales else None,
            last_treatment_at=last_treat,
            last_activity_at=created + timedelta(days=RND.randint(0, 6)),
            created_at=created,
        ))
    db.add_all(rows)
    db.flush()
    return rows


def _msg_templates(stage, svc):
    cust, ai = "customer", "ai"
    base = [
        (cust, f"สวัสดีค่ะ สนใจ {svc} ค่ะ ขอทราบรายละเอียดหน่อยได้ไหมคะ"),
        (ai, f"สวัสดีค่ะ ยินดีให้ข้อมูล {svc} เลยค่ะ 😊 "
             f"ทรีตเมนต์นี้ช่วยดูแลผิวและรูปหน้าให้ดูสดใสขึ้น "
             f"ไม่ทราบว่าคุณลูกค้ามี concern เรื่องไหนเป็นพิเศษไหมคะ"),
    ]
    if stage in ("interested", "booked", "paid", "followup"):
        base += [
            (cust, "ราคาประมาณเท่าไหร่คะ แล้วมีโปรอะไรบ้าง"),
            (ai, "ตอนนี้มีโปรโมชั่นพิเศษสำหรับลูกค้าใหม่อยู่ค่ะ "
                 "ขอแนะนำให้เข้ามาปรึกษาคุณหมอเพื่อประเมินผิวก่อนนะคะ สะดวกช่วงไหนคะ"),
        ]
    if stage in ("booked", "paid", "followup"):
        base += [
            (cust, "สนใจจองคิวค่ะ ขอเป็นช่วงเสาร์-อาทิตย์ได้ไหมคะ"),
            (ai, "ได้เลยค่ะ ดิฉันจองคิวให้เรียบร้อยแล้วนะคะ "
                 "และส่งลิงก์ชำระมัดจำให้ทางแชทเลยค่ะ 🌿"),
        ]
    if stage == "followup":
        base += [
            (ai, "หลังทำทรีตเมนต์เป็นอย่างไรบ้างคะ? ดิฉันมีโปรต่อเนื่องแนะนำให้ด้วยนะคะ"),
        ]
    return base


def _conversations(db, clinic, customers):
    convos, msgs = [], []
    status_map = {"new_lead": "new_lead", "interested": "interested",
                  "booked": "booked", "paid": "paid", "followup": "followup",
                  "lost": "new_lead"}
    stage_sales = {"new_lead": "qualifying", "interested": "recommending",
                   "booked": "booking", "paid": "payment",
                   "followup": "aftercare", "lost": "qualifying"}
    for c in customers:
        svc_name = RND.choice(["Botox กราม", "ฟิลเลอร์", "Skin Booster", "HIFU",
                               "Pico Laser", "Signature Facial"])
        conv = models.Conversation(
            clinic_id=clinic.id, customer_id=c.id, channel=c.channel,
            status=status_map[c.pipeline_stage], branch_id=c.branch_id, ai_enabled=True,
            sales_stage=stage_sales[c.pipeline_stage],
            unread=(c.pipeline_stage in ("new_lead", "interested") and RND.random() < 0.5),
            last_message_at=c.last_activity_at, created_at=c.created_at,
        )
        db.add(conv)
        db.flush()
        convos.append(conv)
        t = c.created_at
        for sender, text in _msg_templates(c.pipeline_stage, svc_name):
            t = t + timedelta(minutes=RND.randint(2, 90))
            msgs.append(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                                       sender=sender, text=text, created_at=t))
        conv.last_message_at = t
    db.add_all(msgs)
    db.flush()
    return convos


def _bookings(db, clinic, customers, services, branches, doctors):
    doc_by_branch = {}
    for d in doctors:
        doc_by_branch.setdefault(d.branch_id, []).append(d)
    rows = []
    booked = [c for c in customers if c.pipeline_stage in ("booked", "paid", "followup")]
    for c in booked:
        svc = RND.choice(services)
        future = c.pipeline_stage == "booked"
        if c.pipeline_stage == "followup":
            slot = NOW - timedelta(days=RND.randint(3, 40))
            status = "completed"
        elif future:
            slot = NOW + timedelta(days=RND.randint(1, 21), hours=RND.randint(0, 8))
            status = RND.choice(["pending", "confirmed", "confirmed"])
        else:
            slot = NOW + timedelta(days=RND.randint(-6, 14), hours=RND.randint(0, 8))
            status = "completed" if slot < NOW else "confirmed"
        docs = doc_by_branch.get(c.branch_id) or doctors
        slot = slot.replace(hour=RND.randint(10, 18), minute=RND.choice([0, 30]))
        rows.append(models.Booking(
            clinic_id=clinic.id, customer_id=c.id, branch_id=c.branch_id,
            service_id=svc.id, doctor_id=RND.choice(docs).id if docs else None,
            slot_at=slot, status=status,
            deposit_required=round(svc.base_price * 0.2 / 100) * 100,
            price=svc.base_price, created_by=RND.choice(["ai", "admin"]),
            created_at=c.created_at + timedelta(days=RND.randint(0, 3)),
        ))
        if status == "completed" and (not c.last_treatment_at or slot > c.last_treatment_at):
            c.last_treatment_at = slot

    for c in customers:
        if c.pipeline_stage not in ("paid", "followup"):
            continue
        for _ in range(RND.randint(0, 2)):
            svc = RND.choice(services)
            past = NOW - timedelta(days=RND.randint(45, 360))
            docs = doc_by_branch.get(c.branch_id) or doctors
            rows.append(models.Booking(
                clinic_id=clinic.id, customer_id=c.id, branch_id=c.branch_id,
                service_id=svc.id, doctor_id=RND.choice(docs).id if docs else None,
                slot_at=past.replace(hour=RND.randint(10, 18), minute=0),
                status="completed", price=svc.base_price,
                deposit_required=round(svc.base_price * 0.2 / 100) * 100,
                created_by="admin", created_at=past))
    db.add_all(rows)
    db.flush()
    return rows


def _payments(db, clinic, bookings, customers):
    rows = []
    cust_by_id = {c.id: c for c in customers}
    for bk in bookings:
        cust = cust_by_id.get(bk.customer_id)
        stage = cust.pipeline_stage if cust else "booked"
        if stage in ("paid", "followup"):
            full = RND.random() < 0.55
            amount = bk.price if full else bk.deposit_required
            rows.append(models.Payment(
                clinic_id=clinic.id, customer_id=bk.customer_id, booking_id=bk.id,
                type="full" if full else "deposit", amount=amount, currency="thb",
                status="paid", method="promptpay",
                description=f"{'Payment' if full else 'Deposit'} for booking #{bk.id}",
                paid_at=bk.created_at + timedelta(hours=RND.randint(1, 30)),
                created_at=bk.created_at + timedelta(hours=1),
            ))
            if cust:
                cust.ltv = round(cust.ltv + amount, 2)
        elif stage == "booked" and RND.random() < 0.4:
            rows.append(models.Payment(
                clinic_id=clinic.id, customer_id=bk.customer_id, booking_id=bk.id,
                type="deposit", amount=bk.deposit_required, currency="thb",
                status="pending", description=f"Deposit for booking #{bk.id}",
                created_at=bk.created_at + timedelta(hours=1),
            ))
    db.add_all(rows)
    db.flush()
    return rows


def _memberships_packages(db, clinic, customers, services):
    mems, packs = [], []
    repeat = [c for c in customers if c.pipeline_stage in ("paid", "followup")]
    for c in repeat:
        tier = ("platinum" if c.ltv > 40000 else "gold" if c.ltv > 15000 else "silver")
        mems.append(models.Membership(clinic_id=clinic.id, customer_id=c.id, tier=tier,
                                      points=int(c.ltv // 100), joined_at=c.created_at))
        if RND.random() < 0.5:
            svc = RND.choice(services)
            total = RND.choice([4, 6, 10])
            packs.append(models.Package(
                clinic_id=clinic.id, customer_id=c.id, service_id=svc.id,
                name=f"{svc.name} ×{total}", total_sessions=total,
                used_sessions=RND.randint(0, total - 1), purchased_at=c.created_at,
                expires_at=c.created_at + timedelta(days=365),
            ))
    db.add_all(mems + packs)
    db.flush()


def _reminders(db, clinic, customers, bookings, services):
    rows = []
    for bk in bookings:
        if bk.status in ("pending", "confirmed") and bk.slot_at > NOW:
            rows.append(models.Reminder(
                clinic_id=clinic.id, customer_id=bk.customer_id, type="pre_appointment",
                channel="web", title="Appointment reminder",
                body="Your appointment is tomorrow. We look forward to seeing you!",
                due_at=bk.slot_at - timedelta(days=1), status="scheduled",
                booking_id=bk.id, created_at=NOW,
            ))
        if bk.status == "completed":
            for typ, days in (("followup_d1", 1), ("followup_d7", 7), ("followup_d14", 14)):
                due = bk.slot_at + timedelta(days=days)
                rows.append(models.Reminder(
                    clinic_id=clinic.id, customer_id=bk.customer_id, type=typ,
                    channel="web", title="Post-treatment follow-up",
                    body="Checking in after your recent treatment — how are you feeling?",
                    due_at=due, status="sent" if due < NOW else "scheduled",
                    booking_id=bk.id, sent_at=due if due < NOW else None,
                    created_at=bk.slot_at,
                ))
    for c in customers:
        if c.last_treatment_at and RND.random() < 0.5:
            svc = RND.choice(services)
            due = c.last_treatment_at + timedelta(days=svc.recommended_interval_days or 90)
            rows.append(models.Reminder(
                clinic_id=clinic.id, customer_id=c.id, type="treatment_due", channel="web",
                title=f"{svc.name} is due",
                body=f"It's time for your next {svc.name}. Shall we book you in?",
                due_at=due, status="scheduled" if due > NOW else "sent", created_at=NOW,
            ))
    db.add_all(rows)
    db.flush()


def _activities(db, clinic, customers):
    rows = []
    for c in customers:
        rows.append(models.Activity(clinic_id=clinic.id, customer_id=c.id, type="system",
                                    summary=f"Lead created from {c.channel} channel",
                                    created_at=c.created_at))
        if c.pipeline_stage != "new_lead":
            rows.append(models.Activity(clinic_id=clinic.id, customer_id=c.id, type="status",
                                        summary=f"Moved to {c.pipeline_stage.replace('_', ' ')}",
                                        created_at=c.last_activity_at))
    db.add_all(rows)
    db.flush()


def _intent_logs(db, clinic, scale: float):
    spread = (["pricing"] * 24 + ["booking"] * 17 + ["service_info"] * 15
              + ["promotion"] * 12 + ["prep_aftercare"] * 9 + ["greeting"] * 6
              + ["other"] * 6 + ["unknown"] * 8)
    n = max(int(round(len(spread) * scale)), 16)
    rows = []
    for _ in range(n):
        intent = RND.choice(spread)
        unknown = intent in ("unknown", "other")
        conf = RND.uniform(0.16, 0.44) if unknown else RND.uniform(0.74, 0.97)
        rows.append(models.IntentLog(
            clinic_id=clinic.id, question=RND.choice(INTENT_QUESTIONS[intent]),
            predicted_intent=intent, confidence=round(conf, 2), resolved=not unknown,
            created_at=NOW - timedelta(days=RND.randint(0, 32))))
    db.add_all(rows)
    db.flush()


# ============================================================
#  Migration: split clinical staff out of the User table
# ============================================================
def backfill_staff_members(db) -> int:
    """One-time, idempotent migration for databases seeded before the split:
    for each clinic that has doctor *Users* but no StaffMembers yet, mirror those
    doctor Users into the StaffMember roster and remap ``Booking.doctor_id`` (which
    now references staff_members) from the old User ids to the new StaffMember ids.
    The doctor Users are left intact as login accounts; the clinic owner can prune
    them from Settings if they no longer log in.
    """
    created = 0
    for clinic in db.query(models.Clinic).all():
        if db.query(models.StaffMember).filter_by(clinic_id=clinic.id).first():
            continue  # already has a roster — skip
        doctor_users = (db.query(models.User)
                        .filter_by(clinic_id=clinic.id, role="doctor").all())
        if not doctor_users:
            continue
        id_map = {}
        for u in doctor_users:
            sm = models.StaffMember(
                clinic_id=clinic.id, name=u.name, role="doctor",
                title=u.title or "Aesthetic Physician", bio=u.bio or "",
                phone=u.phone or "", avatar=u.avatar or "",
                branch_id=u.branch_id, active=u.active)
            db.add(sm)
            db.flush()
            id_map[u.id] = sm.id
            created += 1
        for bk in db.query(models.Booking).filter_by(clinic_id=clinic.id).all():
            if bk.doctor_id in id_map:
                bk.doctor_id = id_map[bk.doctor_id]
    if created:
        db.commit()
    return created


def backfill_automation_rules(db) -> int:
    """Idempotent startup repair: console-created clinics (``starter=False``) used
    to get NO AutomationRule rows — and the retention API has no create endpoint,
    only toggles — so their Automations tab was blank forever. Give any clinic that
    has none the default rule set (same rows ``provision_clinic`` now creates)."""
    created = 0
    for clinic in db.query(models.Clinic).all():
        if db.query(models.AutomationRule).filter_by(clinic_id=clinic.id).first():
            continue  # already has rules — never duplicate or reset toggles
        _automation_rules(db, clinic)
        created += len(AUTOMATION_DATA)
    if created:
        db.commit()
    return created


def cleanup_orphan_payments(db) -> int:
    """Delete payments whose customer no longer exists (orphaned by customer/clinic
    deletes during testing). They are already unreachable from every tenant view,
    but a stale *paid* one whose booking rowid got reused by SQLite used to poison a
    new booking's idempotency check and wrongly report it as already paid. Idempotent."""
    cust_ids = {cid for (cid,) in db.query(models.Customer.id).all()}
    orphans = [p for p in
               db.query(models.Payment).filter(models.Payment.customer_id.isnot(None)).all()
               if p.customer_id not in cust_ids]
    for p in orphans:
        db.delete(p)
    if orphans:
        db.commit()
    return len(orphans)


# The opening-hours sentence the starter KB used to carry. It duplicated data the
# branch record already owns, so it went stale the moment a clinic edited its
# schedule — and the assistant then had two answers to choose between.
_STALE_HOURS_FAQ = ("All branches open daily 10:00-20:00 on weekdays and "
                    "10:00-19:00 on weekends.")


def backfill_branch_hours(db) -> dict:
    """Idempotent repair for the two ways opening hours used to go wrong.

    1. Branches seeded before the per-day schedule existed still store the legacy
       ``{"weekday": ..., "weekend": ...}`` pair. Only the Settings card ever parsed
       it, so the AI was told "10:00-20:00 daily" and availability offered a 19:30
       Saturday slot at a branch that shuts at 19:00. ``branch_days`` reads both
       shapes now, but rewriting them leaves ONE shape in the database.
    2. The starter KB's opening-hours FAQ stated times of its own. Only the exact
       seeded sentence is replaced — an article the clinic wrote itself is their
       content and is left alone, and reported instead.

    Returns counts so startup can log whether it actually did anything.
    """
    from app.services.booking import _DOW, branch_days

    moved = 0
    for b in db.query(models.Branch).all():
        raw = b.hours
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw else {}
            except Exception:
                raw = {}
        if not isinstance(raw, dict) or raw.get("days"):
            continue                      # already per-day, or nothing stored
        days = branch_days(b)             # same reader, so the schedule cannot shift
        if not days:
            continue
        b.hours = json.dumps({"days": {d: days[d] for d in _DOW}})
        moved += 1

    rewritten = 0
    for a in db.query(models.KBArticle).all():
        if (a.content or "").strip() == _STALE_HOURS_FAQ:
            a.content = ("Opening hours differ by branch, and each branch's exact days "
                         "and times are listed with its name and address. Check the "
                         "branch the customer asks about.")
            rewritten += 1

    if moved or rewritten:
        db.commit()
    return {"branches": moved, "articles": rewritten}


# The two seeded Blinks Bright FAQs that described paying through a card link. Matched
# exactly, so an article the clinic has edited is left alone.
_PAYMENT_FAQ_REWRITES = {
    "จองได้ในแชทนี้โดยบอกบริการ สาขา วัน-เวลาที่สะดวก ชื่อ และเบอร์โทร ระบบจะตรวจคิวว่างให้ และส่งลิงก์ชำระมัดจำเพื่อยืนยันการจอง":
        "จองได้ในแชทนี้โดยบอกบริการ สาขา วัน-เวลาที่สะดวก ชื่อ และเบอร์โทร ระบบจะตรวจคิวว่างให้ และส่ง QR สำหรับโอนมัดจำเพื่อยืนยันการจอง",
    "การจองยืนยันด้วยเงินมัดจำประมาณ 20% ของราคาบริการ (ยอดจริงขึ้นกับบริการและสาขา ระบบจะแจ้งก่อนชำระ) ชำระผ่านลิงก์ปลอดภัยด้วยบัตรเครดิต/เดบิตหรือพร้อมเพย์ ส่วนที่เหลือชำระที่คลินิก":
        "การจองยืนยันด้วยเงินมัดจำประมาณ 20% ของราคาบริการ (ยอดจริงขึ้นกับบริการและสาขา ระบบจะแจ้งก่อนชำระ) ชำระโดยสแกน QR พร้อมเพย์ในแชทแล้วส่งสลิป ทีมงานจะตรวจสอบและยืนยันการจอง ส่วนที่เหลือชำระที่คลินิก",
}


def backfill_payment_faq(db) -> list[int]:
    """Rewrite the seeded FAQs that still say "pay through a secure card link".

    Payment moved to a PromptPay QR; the AI answers "how do I pay?" from these articles,
    so an old database would keep promising a card link that no longer exists. Returns
    the clinic ids whose articles changed (their KB index needs a rebuild). Idempotent.
    """
    changed = set()
    for a in db.query(models.KBArticle).all():
        new = _PAYMENT_FAQ_REWRITES.get((a.content or "").strip())
        if new:
            a.content = new
            changed.add(a.clinic_id)
    if changed:
        db.commit()
    return sorted(changed)


OLD_SEED_LOGO = "/assets/images/favicon.png"
NEW_SEED_LOGO = "/assets/images/logo_b.png"


OWNER_EMAIL = "owner@blinksb.co"
OLD_OWNER_EMAIL = "owner@clinic.co"


def backfill_owner_email(db) -> int:
    """Move the seeded owner login from owner@clinic.co to OWNER_EMAIL.

    Same reason as backfill_clinic_logo: the seed only runs on an empty database, so
    a clinic seeded earlier keeps the old address while the login page shows the new
    one. Only the exact old seeded address of an ``owner`` is renamed, and only when
    nobody holds the new one yet (email is unique). Password and everything else stay
    as they are. Idempotent.
    """
    if db.query(models.User).filter(models.User.email == OWNER_EMAIL).first():
        return 0
    u = (db.query(models.User)
         .filter(models.User.email == OLD_OWNER_EMAIL, models.User.role == "owner").first())
    if u is None:
        return 0
    u.email = OWNER_EMAIL
    db.commit()
    return 1


def backfill_clinic_logo(db) -> int:
    """Point clinics still on the old seeded logo at the new Blinks Bright mark.

    The seed writes the logo path into ``Clinic.logo``, so changing the seed alone
    never reaches a database that was seeded earlier: the deployed clinic kept the
    old mark in its sidebar while a fresh local DB showed the new one. Only the
    exact old seeded path is rewritten, so a logo a clinic uploaded itself is never
    touched. Idempotent.
    """
    rows = db.query(models.Clinic).filter(models.Clinic.logo == OLD_SEED_LOGO).all()
    for c in rows:
        c.logo = NEW_SEED_LOGO
    if rows:
        db.commit()
    return len(rows)


def backfill_promotion_branches(db) -> int:
    """Move promotions off the single ``branch_id`` column onto PromotionBranch.

    Promotions became multi-branch (like treatments) and the old column can only
    hold one. Every reader goes through ``promotions.promo_branch_ids``, which folds
    the legacy column in, so an un-migrated row is never *wrong* — but leaving two
    places that can each answer "which branches?" is how the opening-hours mess
    started. This makes the join table the only one. Idempotent: a promotion that
    already has rows is skipped.
    """
    moved = 0
    existing = {r.promotion_id for r in db.query(models.PromotionBranch).all()}
    for p in db.query(models.Promotion).filter(models.Promotion.branch_id.isnot(None)).all():
        if p.id not in existing:
            db.add(models.PromotionBranch(clinic_id=p.clinic_id, promotion_id=p.id,
                                          branch_id=p.branch_id))
        p.branch_id = None
        moved += 1
    if moved:
        db.commit()
    return moved
