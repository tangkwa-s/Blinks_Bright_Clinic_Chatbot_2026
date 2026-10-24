"""SQLAlchemy engine, session factory, and declarative Base for SQLite."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Imports models so they register on the metadata."""
    import app.models  # noqa: F401  (registers ORM models)

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """Add columns introduced after a database was first created.

    ``create_all`` only ever adds whole new *tables* — never a new *column* on an
    existing table — and there is no migration framework here, so patch known
    column additions in place. Idempotent: only adds what's missing.
    """
    from sqlalchemy import text

    additions = {
        "customers": [("merged_into_id", "INTEGER"),
                      ("phone_declined", "BOOLEAN NOT NULL DEFAULT 0"),
                      ("password_hash", "VARCHAR(255) NOT NULL DEFAULT ''")],
        "services": [("deposit", "FLOAT NOT NULL DEFAULT 0"),
                    ("hold_minutes", "INTEGER NOT NULL DEFAULT 0")],
        "messages": [("sender_name", "VARCHAR(120) NOT NULL DEFAULT ''")],
        "promotions": [("quota", "INTEGER NOT NULL DEFAULT 0")],
        "payments": [("slip_image", "VARCHAR(255) NOT NULL DEFAULT ''"),
                     ("slip_received_at", "DATETIME"), ("slip_amount", "FLOAT")],
        "bookings": [("promo_id", "INTEGER"), ("hold_expires_at", "DATETIME"),
                    ("hold_reminder_sent_at", "DATETIME"),
                    ("hold_minutes", "INTEGER NOT NULL DEFAULT 0")],
        "clinics": [("cover", "VARCHAR(255) NOT NULL DEFAULT ''"),
                    ("ai_name", "VARCHAR(60) NOT NULL DEFAULT ''"),
                    ("ai_instructions", "TEXT NOT NULL DEFAULT ''"),
                    ("hold_minutes", "INTEGER NOT NULL DEFAULT 0")],
        "staff_members": [("ics_url", "VARCHAR(500) NOT NULL DEFAULT ''"),
                          ("ics_last_synced_at", "DATETIME"),
                          ("ics_last_error", "VARCHAR(255) NOT NULL DEFAULT ''"),
                          ("ics_last_error_at", "DATETIME")],
    }
    # Indexes introduced after first creation — ``create_all`` never adds an index
    # to an existing table either. Names match the SQLAlchemy defaults so a fresh
    # DB and a patched DB end up identical.
    indexes = [
        ("ix_activities_customer_id", "activities", "customer_id"),
        # day_availability filters bookings by slot_at on every availability check, every
        # booking, every reschedule and both lazy sweeps; the table carried an index on
        # clinic_id alone. Non-unique on purpose — a UNIQUE index on (branch_id, slot_at)
        # could not express the invariant anyway (a booking occupies its treatment's whole
        # duration, and the doctor conflict spans branches) and would abort startup here:
        # a database can already hold two confirmed bookings sharing a branch and slot.
        ("ix_bookings_slot_at", "bookings", "slot_at"),
        # sweep_expired_holds/sweep_hold_reminders filter on this every 10 seconds, per
        # clinic, forever — without an index that scan grows with a clinic's entire
        # booking history, not with how often the sweep runs. Same reasoning as
        # ix_bookings_slot_at above; see models.py's own comment on the column.
        ("ix_bookings_hold_expires_at", "bookings", "hold_expires_at"),
    ]
    with engine.begin() as conn:
        for table, cols in additions.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, decl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {decl}"))
        for name, table, col in indexes:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})"))
