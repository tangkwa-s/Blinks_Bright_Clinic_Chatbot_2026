"""ORM models for Blinks Bright — the full data model.

``init_db`` imports this module so every model registers on ``Base.metadata``.
JSON columns hold structured data (config, metadata, embeddings, audience).

Multi-tenancy: ``Clinic`` is the top-level tenant. Every other table carries an
indexed ``clinic_id`` so all data is isolated per clinic.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


# ============================================================
#  Clinic — the top-level tenant
# ============================================================
class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(140))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    tagline: Mapped[str] = mapped_column(String(200), default="")
    logo: Mapped[str] = mapped_column(String(255), default="")
    cover: Mapped[str] = mapped_column(String(255), default="")        # picker card cover photo
    accent: Mapped[str] = mapped_column(String(16), default="")        # brand accent hex
    ai_name: Mapped[str] = mapped_column(String(60), default="")       # AI assistant display name
    ai_instructions: Mapped[str] = mapped_column(Text, default="")     # clinic-editable extra AI guidance
    # Booking hold timeout override, minutes. 0 = use the .env HOLD_MINUTES default (see
    # booking.py::resolved_hold_minutes). A Service.hold_minutes override, if set, wins
    # over this.
    hold_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ============================================================
#  Branches & staff
# ============================================================
class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(16), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    hours: Mapped[str] = mapped_column(Text, default="")          # JSON string
    open_hour: Mapped[int] = mapped_column(Integer, default=10)   # for slot generation
    close_hour: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="sales")
    title: Mapped[str] = mapped_column(String(80), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    avatar: Mapped[str] = mapped_column(String(255), default="")
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StaffMember(Base):
    """Clinical staff (doctors / therapists) — the team roster shown in Doctors &
    Staff and assignable to bookings. SEPARATE from ``User``: these are NOT login
    accounts (no email / password). A person who logs in is a ``User``; the
    clinical roster is ``StaffMember`` — the two are independent."""
    __tablename__ = "staff_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(32), default="doctor")  # doctor|nurse|therapist|staff
    title: Mapped[str] = mapped_column(String(80), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    avatar: Mapped[str] = mapped_column(String(255), default="")
    # External calendar (ICS/webcal) sync — see ExternalBusyBlock below. These four are
    # UTC bookkeeping timestamps like every other datetime in this file, NOT the naive-
    # Bangkok convention ExternalBusyBlock.starts_at/ends_at use.
    ics_url: Mapped[str] = mapped_column(String(500), default="")
    ics_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ics_last_error: Mapped[str] = mapped_column(String(255), default="")
    ics_last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExternalBusyBlock(Base):
    """One busy interval pulled from a doctor's own external calendar (a pasted
    Google/Outlook/Apple 'secret ICS' URL) — personal appointments, leave, anything
    NOT in our own booking system. Populated ONLY by the background sync job
    (``app/services/calendar_sync.py``); ``booking.day_availability`` reads this as a
    plain local-DB query — the ICS URL itself is never fetched from inside
    ``claim_slot``'s lock (see booking.py's 'Holding a slot' notes for why that lock
    must never gain a network call).

    ``starts_at``/``ends_at`` are naive Bangkok wall-clock, matching ``Booking.slot_at``
    / ``hold_expires_at`` — NOT UTC, unlike every other datetime in this file. They sit
    in the same overlap arithmetic as Booking-derived busy intervals inside
    day_availability; storing them as UTC would silently offset every comparison by 7
    hours. The source ICS's DTSTART/DTEND (UTC, tz-aware, or an all-day DATE) is
    converted to this convention once, at sync time — never at query time.

    Replaced wholesale per staff member on every SUCCESSFUL sync (delete + reinsert); a
    failed fetch/parse leaves the previous rows untouched (last-known-good) — see
    calendar_sync.py::sync_staff_calendar.
    """
    __tablename__ = "external_busy_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_members.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    uid: Mapped[str] = mapped_column(String(255), default="")   # source VEVENT UID, debugging only
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ============================================================
#  Channels
# ============================================================
class ChannelIntegration(Base):
    __tablename__ = "channel_integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    channel: Mapped[str] = mapped_column(String(20))              # web
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)      # tokens / secrets
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(20))               # web
    event_type: Mapped[str] = mapped_column(String(60), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    processed: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ============================================================
#  Customers & CRM
# ============================================================
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    nickname: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    # Set once the customer has been ASKED for a phone number and explicitly said they
    # have none (see app/ai/tools.py::_no_phone_confirmed_by_customer) — lets a booking
    # proceed with phone shown as "-" instead of blocking forever.
    phone_declined: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str] = mapped_column(String(160), default="")
    # Customer-portal login (app/routers/portal.py). Empty = this CRM record has no
    # portal account; the record still exists and works exactly as before, so every
    # customer the AI creates from a chat stays loginless until they register.
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    channel: Mapped[str] = mapped_column(String(20), default="web")     # origin channel
    channel_user_id: Mapped[str] = mapped_column(String(120), default="")
    avatar: Mapped[str] = mapped_column(String(512), default="")        # profile picture URL
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    pipeline_stage: Mapped[str] = mapped_column(String(20), default="new_lead")
    temperature: Mapped[str] = mapped_column(String(10), default="cold")  # hot|warm|cold
    lead_score: Mapped[int] = mapped_column(Integer, default=0)
    budget: Mapped[str] = mapped_column(String(60), default="")
    concern: Mapped[str] = mapped_column(Text, default="")
    interested: Mapped[str] = mapped_column(Text, default="")            # interested services
    tags: Mapped[list] = mapped_column(JSON, default=list)
    birthday: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ltv: Mapped[float] = mapped_column(Float, default=0.0)               # lifetime value
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_treatment_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Identity resolution: when this record is merged into a golden record, this
    # points at the surviving customer. Merged records are hidden from lists, and
    # inbound from their channel identity is redirected to the golden record.
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(20), default="web")
    status: Mapped[str] = mapped_column(String(20), default="new_lead")
    sales_stage: Mapped[str] = mapped_column(String(24), default="greeting")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    escalation_reason: Mapped[str] = mapped_column(String(255), default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    unread: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    sender: Mapped[str] = mapped_column(String(12))               # customer|ai|admin|system
    sender_name: Mapped[str] = mapped_column(String(120), default="")  # admin display name / automation label
    text: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str] = mapped_column(String(48), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    type: Mapped[str] = mapped_column(String(24))                 # message|status|booking|payment|note|reminder|campaign|campaign_reply
    summary: Mapped[str] = mapped_column(String(255))
    ref_type: Mapped[str] = mapped_column(String(24), default="")
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ============================================================
#  Catalog & knowledge base
# ============================================================
class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    base_price: Mapped[float] = mapped_column(Float, default=0.0)
    duration_min: Mapped[int] = mapped_column(Integer, default=45)
    recommended_interval_days: Mapped[int] = mapped_column(Integer, default=0)
    prep_notes: Mapped[str] = mapped_column(Text, default="")
    aftercare_notes: Mapped[str] = mapped_column(Text, default="")
    contraindications: Mapped[str] = mapped_column(Text, default="")
    image: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    deposit: Mapped[float] = mapped_column(Float, default=0.0)   # flat ฿ override, same at every branch (see deposit_for); 0 = auto 20%
    # Booking hold timeout override, minutes (see booking.py::resolved_hold_minutes).
    # 0 = use the clinic's own hold_minutes, which may itself be 0 = the .env default.
    hold_minutes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ServiceBranch(Base):
    """Which branches offer a treatment. No rows for a service = every branch
    (the common/default case); one or more rows = restricted to just those
    branches — a service selecting every branch is normalised back to "no
    rows" (see catalog.py), so this table only ever holds real subsets."""
    __tablename__ = "service_branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)


class ServicePrice(Base):
    __tablename__ = "service_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    price: Mapped[float] = mapped_column(Float, default=0.0)


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str] = mapped_column(Text, default="")
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    discount_label: Mapped[str] = mapped_column(String(60), default="")
    promo_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quota: Mapped[int] = mapped_column(Integer, default=0)  # max redemptions; 0 = unlimited
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PromotionBranch(Base):
    """Which branches a promotion runs at — the same shape as ServiceBranch, and read
    the same way: no rows = every branch (the common case), one or more rows = just
    those. A promotion ticking every branch is normalised back to "no rows" in
    catalog.py, so this table only ever holds real subsets.

    The older single ``Promotion.branch_id`` column is still on the model for rows
    written before this table existed; ``seed.py::backfill_promotion_branches``
    migrates them on startup, and every reader goes through
    ``promotions.py::promo_branch_ids`` so the two can never be read differently.
    """
    __tablename__ = "promotion_branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    promotion_id: Mapped[int] = mapped_column(ForeignKey("promotions.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)


class KBArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(24), default="general")  # faq|policy|prep|aftercare|general
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class KBChunk(Base):
    """Unified retrieval store — every KB source chunked + embedded."""
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    source_type: Mapped[str] = mapped_column(String(24))          # service|promotion|article|branch
    source_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ============================================================
#  Bookings & payments
# ============================================================
class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    # the promotion whose price won at booking time — powers promo quota usage counts
    promo_id: Mapped[int | None] = mapped_column(ForeignKey("promotions.id"), nullable=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("staff_members.id"), nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    slot_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Deadline of the UNPAID HOLD on this slot, in naive Bangkok WALL-CLOCK — the same
    # clock as slot_at, NOT the UTC every other datetime in this file uses. It is compared
    # against booking._now_local() in exactly two places (the availability reader and the
    # expiry sweep); against utcnow() it reads 7 hours out and a hold would never lapse.
    # NULL = no hold: the booking blocks its slot until it is cancelled or swept, which is
    # every admin booking, every paid booking, and every row predating this column.
    # Indexed for the same reason slot_at is: sweep_expired_holds and sweep_hold_reminders
    # filter on this every 10 seconds, per clinic, forever — without an index that scan
    # grows with a clinic's ENTIRE booking history (not just its live holds), not with how
    # often the sweep runs. See database.py::_ensure_columns for the migration path onto
    # an existing clinic.db (create_all alone only ever creates whole new tables).
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # UTC bookkeeping (unlike hold_expires_at above) — set once sweep_hold_reminders has
    # sent the "running out soon" nudge, so a booking sitting inside the reminder window
    # across several 60-second sweep ticks gets nudged exactly once, not once per tick.
    hold_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # A plain audit copy of whatever create_booking's own hold_minutes PARAMETER was for
    # THIS booking (0 = no hold applied, e.g. an admin booking) — not a new sentinel or a
    # resolution of its own. Lets a later message (the hold-expired notice, sent after the
    # fact) state the number this specific booking was actually held for, rather than
    # whatever the clinic/service settings say NOW (see booking.py::resolved_hold_minutes,
    # which computes the number BEFORE create_booking is ever called).
    hold_minutes: Mapped[int] = mapped_column(Integer, default=0)
    # pending|confirmed|completed|cancelled|no_show|expired  ('expired' = the unpaid hold
    # ran out and the slot was released — NOT the same as no_show, where they had a real
    # appointment and did not turn up)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    deposit_required: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(12), default="admin")  # ai|admin
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(12), default="deposit")   # deposit|full
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="thb")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|paid|failed|refunded
    method: Mapped[str] = mapped_column(String(20), default="")          # promptpay (card = legacy rows)
    description: Mapped[str] = mapped_column(String(200), default="")
    stripe_session_id: Mapped[str] = mapped_column(String(255), default="")
    stripe_payment_intent_id: Mapped[str] = mapped_column(String(255), default="")
    # The customer's transfer slip, while staff check it (app/services/slips.py). Set =
    # "slip received, waiting for a person"; the booking's hold is paused meanwhile.
    slip_image: Mapped[str] = mapped_column(String(255), default="")
    slip_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The amount the vision model read off that slip (None = could not read one). When it
    # differs from `amount` the slip is flagged and the hold is NOT paused for a short one.
    slip_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ============================================================
#  Memberships, packages, loyalty
# ============================================================
class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    tier: Mapped[str] = mapped_column(String(20), default="silver")    # silver|gold|platinum
    points: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    total_sessions: Mapped[int] = mapped_column(Integer, default=1)
    used_sessions: Mapped[int] = mapped_column(Integer, default=0)
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ============================================================
#  Automation & analytics
# ============================================================
class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    type: Mapped[str] = mapped_column(String(32))   # pre_appointment|treatment_due|followup_d1...|winback|birthday|package_expiry
    channel: Mapped[str] = mapped_column(String(20), default="web")
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), default="scheduled")  # scheduled|sent|cancelled|skipped
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IntentLog(Base):
    __tablename__ = "intent_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    predicted_intent: Mapped[str] = mapped_column(String(48), default="unknown")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    audience: Mapped[dict] = mapped_column(JSON, default=dict)     # filter spec
    channel: Mapped[str] = mapped_column(String(20), default="web")
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft|scheduled|sent
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    audience_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TokenUsage(Base):
    """One row per LLM call — powers the dashboard's AI token + cost summary."""
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="chat")   # chat|analyze|embedding
    model: Mapped[str] = mapped_column(String(60), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
