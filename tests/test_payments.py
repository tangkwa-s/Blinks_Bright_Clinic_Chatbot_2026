"""Regression tests for the payment service (app/services/billing.py) and
the orphan-payment cleanup (app/seed.py::cleanup_orphan_payments).

External Stripe is disabled in the test settings, so create_payment writes a
Payment row and returns url=None (no network); the AI is never called.
"""
from datetime import datetime, timedelta

from app import models
from app.seed import cleanup_orphan_payments
from app.services import billing
from app.services.booking import create_booking


def _customer(db, clinic, name="Cust", **kw):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    c = models.Customer(clinic_id=clinic.id, name=name,
                        branch_id=branch.id if branch else None, **kw)
    db.add(c)
    db.commit()
    return c


def _service(db, clinic, base_price=10000.0):
    """A fresh service with a known base_price and NO branch override / promo, so
    resolved_price == base_price (deterministic deposit)."""
    s = models.Service(clinic_id=clinic.id, name="Test Treatment",
                       category="test", base_price=base_price, active=True)
    db.add(s)
    db.commit()
    return s


def _booking(db, clinic, customer, service, conversation_id=None):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    bk = create_booking(db, customer=customer, service=service, branch_id=branch.id,
                        slot_at=datetime.utcnow() + timedelta(days=2), created_by="admin",
                        conversation_id=conversation_id)
    db.commit()
    return bk


def _conversation(db, clinic, customer, status="interested"):
    conv = models.Conversation(clinic_id=clinic.id, customer_id=customer.id,
                               channel="web", status=status)
    db.add(conv)
    db.commit()
    return conv


# ---------------------------------------------------------------------------
# CROSS-CLINIC IDEMPOTENCY BUG
# ---------------------------------------------------------------------------
def test_create_payment_ignores_paid_payment_from_another_clinic(db, make_clinic):
    """A stale *paid* deposit in clinic B that happens to carry the SAME booking_id
    as clinic A's new booking (SQLite rowid reuse) must NOT poison clinic A's
    idempotency check. create_payment for clinic A's booking must produce a fresh
    PENDING payment for clinic A's customer — never report 'already paid'."""
    clinic_a = make_clinic("Clinic A Pay", slug="clinic-a-pay")
    clinic_b = make_clinic("Clinic B Pay", slug="clinic-b-pay")

    cust_a = _customer(db, clinic_a, name="Alice A")
    svc_a = _service(db, clinic_a)
    booking_a = _booking(db, clinic_a, cust_a, svc_a)

    # Clinic B: a PAID deposit payment whose booking_id collides with clinic A's
    # booking id (simulating SQLite reusing the rowid of a since-deleted booking).
    cust_b = _customer(db, clinic_b, name="Bob B")
    poison = models.Payment(
        clinic_id=clinic_b.id, customer_id=cust_b.id, booking_id=booking_a.id,
        type="deposit", amount=999.0, currency="thb", status="paid",
        paid_at=datetime.utcnow(),
    )
    db.add(poison)
    db.commit()
    poison_id = poison.id

    payment = billing.create_payment(db, booking=booking_a, ptype="deposit")

    # It must NOT have returned the clinic-B paid payment.
    assert payment.id != poison_id
    # A fresh, unpaid payment for clinic A's own customer.
    assert payment.status == "pending"
    assert payment.clinic_id == clinic_a.id
    assert payment.customer_id == cust_a.id
    assert payment.booking_id == booking_a.id
    # The poison row is untouched and still paid.
    db.refresh(poison)
    assert poison.status == "paid"


def test_create_payment_same_clinic_paid_is_idempotent(db, clinic):
    """Sanity: within the SAME clinic+customer+booking, an already-paid deposit IS
    returned as-is (the real idempotency guarantee — never charge twice)."""
    cust = _customer(db, clinic, name="Carla")
    svc = _service(db, clinic)
    booking = _booking(db, clinic, cust, svc)

    p1 = billing.create_payment(db, booking=booking, ptype="deposit")
    billing.mark_paid(db, p1)

    p2 = billing.create_payment(db, booking=booking, ptype="deposit")
    assert p2.id == p1.id
    assert p2.status == "paid"


# ---------------------------------------------------------------------------
# mark_paid cascade
# ---------------------------------------------------------------------------
def test_mark_paid_cascades_to_booking_and_customer(db, clinic):
    """mark_paid flips Payment->paid, Booking->confirmed, and adds amount to LTV."""
    cust = _customer(db, clinic, name="Dana")
    assert cust.ltv == 0.0
    svc = _service(db, clinic, base_price=10000.0)
    booking = _booking(db, clinic, cust, svc)
    assert booking.status == "pending"

    payment = billing.create_payment(db, booking=booking, ptype="deposit")
    assert payment.status == "pending"
    assert payment.amount > 0          # base 10000 -> deposit 2000

    ok = billing.mark_paid(db, payment)
    assert ok is True

    db.refresh(payment)
    db.refresh(booking)
    db.refresh(cust)
    assert payment.status == "paid"
    assert payment.paid_at is not None
    assert booking.status == "confirmed"
    assert cust.ltv == round(payment.amount, 2)


def test_create_payment_full_after_deposit_charges_only_remaining_balance(db, clinic):
    """Deposit first (฿2,000 on a ฿10,000 service), then "pay in full" later must
    only charge the REMAINING balance (฿8,000) — never the full ฿10,000 again on
    top of the deposit already paid."""
    cust = _customer(db, clinic, name="Kim")
    svc = _service(db, clinic, base_price=10000.0)
    booking = _booking(db, clinic, cust, svc)

    deposit = billing.create_payment(db, booking=booking, ptype="deposit")
    assert deposit.amount == 2000.0          # auto 20% of 10,000
    assert billing.mark_paid(db, deposit) is True

    full = billing.create_payment(db, booking=booking, ptype="full")
    assert full.amount == 8000.0             # 10,000 - 2,000 already paid
    assert full.id != deposit.id


def test_mark_paid_remaining_balance_flips_conversation_paid_and_sums_ltv(db, clinic):
    """After the deposit (-> booked) and then the remaining-balance top-up
    (-> paid), the conversation ends at 'paid' and LTV equals the full price
    exactly once (no double count from the two partial payments)."""
    cust = _customer(db, clinic, name="Leo")
    svc = _service(db, clinic, base_price=10000.0)
    conv = _conversation(db, clinic, cust, status="interested")
    booking = _booking(db, clinic, cust, svc, conversation_id=conv.id)

    deposit = billing.create_payment(db, booking=booking, ptype="deposit")
    assert billing.mark_paid(db, deposit) is True
    db.refresh(conv)
    assert conv.status == "booked"

    remainder = billing.create_payment(db, booking=booking, ptype="full")
    assert remainder.amount == 8000.0
    assert billing.mark_paid(db, remainder) is True

    db.refresh(conv)
    db.refresh(cust)
    assert conv.status == "paid"
    assert cust.ltv == 10000.0               # 2,000 + 8,000, not 2,000 + 10,000


def test_create_payment_full_when_deposit_covers_full_price_is_already_paid(db, clinic):
    """A service configured with a 100%-of-price deposit override: once that
    deposit is paid, asking to "pay in full" has nothing left to collect and
    must report the existing payment as already paid rather than opening a
    ฿0 checkout session."""
    cust = _customer(db, clinic, name="Mia")
    svc = _service(db, clinic, base_price=5000.0)
    svc.deposit = 5000.0                     # 100% deposit override
    db.commit()
    booking = _booking(db, clinic, cust, svc)
    assert booking.deposit_required == 5000.0

    deposit = billing.create_payment(db, booking=booking, ptype="deposit")
    assert billing.mark_paid(db, deposit) is True

    full = billing.create_payment(db, booking=booking, ptype="full")
    assert full.status == "paid"
    assert full.id == deposit.id


def test_mark_paid_deposit_flips_conversation_to_booked(db, clinic):
    """A paid DEPOSIT only secures the slot — the linked conversation's pipeline
    status moves to 'booked', not 'paid', so it surfaces under the Conversations
    page's Booked filter rather than Paid."""
    cust = _customer(db, clinic, name="Hana")
    svc = _service(db, clinic)
    conv = _conversation(db, clinic, cust, status="interested")
    booking = _booking(db, clinic, cust, svc, conversation_id=conv.id)

    payment = billing.create_payment(db, booking=booking, ptype="deposit")
    assert billing.mark_paid(db, payment) is True

    db.refresh(conv)
    assert conv.status == "booked"


def test_mark_paid_full_flips_conversation_to_paid(db, clinic):
    """A paid FULL payment fully settles the sale — the linked conversation's
    pipeline status moves straight to 'paid'."""
    cust = _customer(db, clinic, name="Ivy")
    svc = _service(db, clinic)
    conv = _conversation(db, clinic, cust, status="booked")
    booking = _booking(db, clinic, cust, svc, conversation_id=conv.id)

    payment = billing.create_payment(db, booking=booking, ptype="full")
    assert billing.mark_paid(db, payment) is True

    db.refresh(conv)
    assert conv.status == "paid"


def test_mark_paid_custom_charge_with_no_booking_flips_latest_conversation(db, clinic):
    """A custom, admin-initiated charge (POST /conversations/{id}/charge) has no
    booking at all. Before this fix mark_paid's conversation-status cascade was
    gated on `booking.conversation_id`, so a fully-paid custom charge never moved
    the conversation out of its pre-payment stage. It should now fall back to the
    customer's latest conversation (same resolution notify_payment_paid uses) and
    mark it 'paid' — matching customer.pipeline_stage."""
    cust = _customer(db, clinic, name="Jay")
    conv = _conversation(db, clinic, cust, status="interested")

    payment = billing.create_payment(db, customer=cust, amount=1500.0, ptype="custom")
    assert payment.booking_id is None
    assert billing.mark_paid(db, payment) is True

    db.refresh(conv)
    db.refresh(cust)
    assert conv.status == "paid"
    assert cust.pipeline_stage == "paid"


def test_mark_paid_is_won_only_once(db, clinic):
    """The compare-and-set means a second mark_paid on an already-paid payment
    returns False and does NOT double-count the LTV."""
    cust = _customer(db, clinic, name="Evan")
    svc = _service(db, clinic)
    booking = _booking(db, clinic, cust, svc)
    payment = billing.create_payment(db, booking=booking, ptype="deposit")

    assert billing.mark_paid(db, payment) is True
    db.refresh(cust)
    ltv_after_first = cust.ltv

    assert billing.mark_paid(db, payment) is False
    db.refresh(cust)
    assert cust.ltv == ltv_after_first   # no double cascade


# ---------------------------------------------------------------------------
# cleanup_orphan_payments
# ---------------------------------------------------------------------------
def test_cleanup_orphan_payments_removes_only_orphans(db, clinic):
    """A payment whose customer no longer exists is deleted; a valid one is kept;
    a second run is a no-op (idempotent)."""
    cust = _customer(db, clinic, name="Fiona")

    # Valid payment — kept.
    keep = models.Payment(clinic_id=clinic.id, customer_id=cust.id, type="deposit",
                          amount=500.0, currency="thb", status="pending")
    # Orphan — customer_id points at a customer that was never created.
    missing_id = 999999
    assert db.get(models.Customer, missing_id) is None
    orphan = models.Payment(clinic_id=clinic.id, customer_id=missing_id, type="deposit",
                            amount=700.0, currency="thb", status="paid")
    db.add_all([keep, orphan])
    db.commit()
    keep_id, orphan_id = keep.id, orphan.id

    removed = cleanup_orphan_payments(db)
    assert removed == 1
    assert db.get(models.Payment, orphan_id) is None
    assert db.get(models.Payment, keep_id) is not None

    # Idempotent: nothing left to remove.
    assert cleanup_orphan_payments(db) == 0
    assert db.get(models.Payment, keep_id) is not None


def test_cleanup_orphan_payments_after_customer_delete(db, clinic):
    """Deleting a customer with an existing paid payment makes that payment an
    orphan that cleanup removes."""
    cust = _customer(db, clinic, name="Gabe")
    pay = models.Payment(clinic_id=clinic.id, customer_id=cust.id, type="deposit",
                         amount=300.0, currency="thb", status="paid")
    db.add(pay)
    db.commit()
    pay_id = pay.id

    db.delete(cust)
    db.commit()

    assert cleanup_orphan_payments(db) == 1
    assert db.get(models.Payment, pay_id) is None
    assert cleanup_orphan_payments(db) == 0
