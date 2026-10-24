"""Regression tests for app/ai/memory.py::customer_memory — specifically the
upcoming-booking payment line the AI relies on to know what is already paid and
what remaining balance (if any) to quote."""
from datetime import datetime, timedelta

from app import models
from app.ai.memory import customer_memory
from app.services import billing
from app.services.booking import create_booking


def _customer(db, clinic, name="Cust"):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    c = models.Customer(clinic_id=clinic.id, name=name, branch_id=branch.id if branch else None)
    db.add(c)
    db.commit()
    return c


def _service(db, clinic, base_price=10000.0):
    s = models.Service(clinic_id=clinic.id, name="Test Treatment",
                       category="test", base_price=base_price, active=True)
    db.add(s)
    db.commit()
    return s


def _booking(db, clinic, customer, service):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    bk = create_booking(db, customer=customer, service=service, branch_id=branch.id,
                        slot_at=datetime.utcnow() + timedelta(days=2), created_by="admin")
    db.commit()
    return bk


def test_memory_reports_unpaid_deposit(db, clinic):
    cust = _customer(db, clinic, name="Nina")
    svc = _service(db, clinic, base_price=10000.0)
    _booking(db, clinic, cust, svc)

    mem = customer_memory(db, cust)
    assert "deposit ฿2,000 is NOT yet paid" in mem
    assert "ALREADY PAID" not in mem


def test_memory_reports_deposit_paid_with_exact_remaining_balance(db, clinic):
    """After only the deposit is paid, the memory must quote the deposit as paid
    (not silently mislabel a full payment) AND the exact remaining balance, so the
    AI can state it verbatim instead of calculating it itself."""
    cust = _customer(db, clinic, name="Omar")
    svc = _service(db, clinic, base_price=10000.0)
    booking = _booking(db, clinic, cust, svc)

    deposit = billing.create_payment(db, booking=booking, ptype="deposit")
    assert billing.mark_paid(db, deposit) is True

    mem = customer_memory(db, cust)
    assert "฿2,000 of this booking's ฿10,000 total is ALREADY PAID" in mem
    assert "remaining balance of ฿8,000 is NOT yet paid" in mem
    assert "ALREADY PAID IN FULL" not in mem


def test_memory_reports_fully_paid_after_deposit_plus_remaining_balance(db, clinic):
    """Once the deposit AND the later remaining-balance top-up are both paid (two
    separate paid Payment rows for the same booking), the memory must sum them and
    report the booking as fully paid — not just echo the first paid row it finds."""
    cust = _customer(db, clinic, name="Pia")
    svc = _service(db, clinic, base_price=10000.0)
    booking = _booking(db, clinic, cust, svc)

    deposit = billing.create_payment(db, booking=booking, ptype="deposit")
    billing.mark_paid(db, deposit)
    remainder = billing.create_payment(db, booking=booking, ptype="full")
    assert remainder.amount == 8000.0
    billing.mark_paid(db, remainder)

    mem = customer_memory(db, cust)
    assert "฿10,000 for THIS booking is ALREADY PAID IN FULL" in mem
    assert "remaining balance" not in mem
