"""Eval harness — provision a clinic once, then run each case through the real AI.

IMPORTANT: this module sets DB_PATH to a throwaway file BEFORE importing the app
(so the real clinic.db is never touched),
but leaves OpenAI ON — the eval needs the real model.
"""
import os
import tempfile

# Throwaway DB before the engine is built. Never touch the real clinic.db.
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="bb-eval-"), "eval.db"))

from datetime import datetime  # noqa: E402

from app.config import settings  # noqa: E402

# No real charges during evals; OpenAI stays as configured in .env.

from app import models  # noqa: E402,F401
from evals import checks  # noqa: E402
from app.ai import rag  # noqa: E402
from app.ai.chat import respond  # noqa: E402
from app.ai.client import is_configured as ai_configured  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.seed import provision_clinic  # noqa: E402

_EVAL_SLUG = "eval-clinic"
# customer-owned tables wiped between cases (catalog + KB are kept)
_PER_CASE_TABLES = (models.Message, models.Activity, models.Reminder, models.Payment,
                    models.Booking, models.Note, models.Membership, models.Package,
                    models.Conversation, models.Customer)


class EvalContext:
    """What a check sees: the final AI reply, its meta, and the resulting DB state."""

    def __init__(self, db, clinic, customer, conversation, result, turns):
        self.db = db
        self.clinic = clinic
        self.customer = customer
        self.conversation = conversation
        self.result = result or {"text": "", "meta": {}}
        self.turns = turns

    @property
    def text(self) -> str:
        return self.result.get("text", "") or ""

    @property
    def meta(self) -> dict:
        return self.result.get("meta", {}) or {}

    @property
    def tools(self) -> list:
        return self.meta.get("tools", []) or []

    @property
    def bookings(self) -> list:
        return self.db.query(models.Booking).filter_by(customer_id=self.customer.id).all()

    @property
    def escalated(self) -> bool:
        self.db.refresh(self.conversation)
        return (bool((self.conversation.escalation_reason or "").strip())
                or "request_human_help" in self.tools)


def setup_clinic(index_kb: bool = True) -> int:
    """Provision the eval clinic once (idempotent) and return its id."""
    # Hard stop if the engine somehow bound to anything but the throwaway eval DB
    # (an import-order regression once pointed this at the LIVE clinic.db).
    if "bb-eval-" not in str(engine.url):
        raise RuntimeError(
            f"Eval harness refuses to run: engine is bound to {engine.url}, not a "
            "throwaway bb-eval DB. Check that evals/__init__.py set DB_PATH "
            "before any app.* import.")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        clinic = db.query(models.Clinic).filter_by(slug=_EVAL_SLUG).first()
        if not clinic:
            clinic = provision_clinic(db, "Eval Clinic", slug=_EVAL_SLUG)
            db.commit()
            if index_kb and ai_configured():
                try:
                    rag.reindex(db, clinic.id)
                except Exception as exc:  # pragma: no cover
                    print(f"[eval] KB index skipped: {exc}")
        return clinic.id
    finally:
        db.close()


def run_case(case, cid: int):
    """Run one case end-to-end and return a list of CheckResult."""
    db = SessionLocal()
    try:
        for model in _PER_CASE_TABLES:                  # fresh slate, keep catalog/KB
            db.query(model).filter_by(clinic_id=cid).delete()
        db.commit()

        branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
        # a portal member: web booking is members-only (tools.booking_requires_signup),
        # and the cases measure the booking conversation itself
        cust = models.Customer(clinic_id=cid, name="Eval Customer", channel="web",
                               password_hash="eval-member",
                               channel_user_id="eval", branch_id=branch.id if branch else None,
                               pipeline_stage="new_lead", temperature="warm", lead_score=20)
        db.add(cust)
        db.flush()
        conv = models.Conversation(clinic_id=cid, customer_id=cust.id, channel="web",
                                   branch_id=cust.branch_id, status="new_lead",
                                   sales_stage="greeting")
        db.add(conv)
        db.commit()

        result = None
        for turn in case.turns:
            db.add(models.Message(clinic_id=cid, conversation_id=conv.id,
                                  sender="customer", text=turn))
            db.commit()
            result = respond(db, conv)
            db.add(models.Message(clinic_id=cid, conversation_id=conv.id, sender="ai",
                                  text=result["text"], meta=result.get("meta", {})))
            conv.last_message_at = datetime.utcnow()
            db.commit()

        ctx = EvalContext(db, db.get(models.Clinic, cid), cust, conv, result, case.turns)
        # ALWAYS_ON holds properties every reply must have regardless of the case, so
        # they cannot be forgotten when a case is added (see checks.ALWAYS_ON).
        return [chk(ctx) for chk in list(case.checks) + list(checks.ALWAYS_ON)]
    finally:
        db.close()
