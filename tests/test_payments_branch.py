"""Payments page per-branch filtering (GET /api/payments, /api/payments/summary).

Payment has no branch_id of its own — its branch is attributed the same way
dashboard.py does: the booking's branch, else the customer's own branch (for a
standalone/custom charge with no booking).
"""
from datetime import datetime, timedelta

from app import models


def _customer(db, cid, branch_id, name="Cust"):
    c = models.Customer(clinic_id=cid, name=name, channel="web",
                        channel_user_id=f"cu-{name}-{branch_id}", branch_id=branch_id)
    db.add(c)
    db.commit()
    return c


def _booking_payment(db, cid, customer, branch_id, amount, ptype="deposit"):
    svc = db.query(models.Service).filter_by(clinic_id=cid).first()
    bk = models.Booking(clinic_id=cid, customer_id=customer.id, branch_id=branch_id,
                        service_id=svc.id, slot_at=datetime.utcnow(), status="confirmed")
    db.add(bk)
    db.flush()
    pay = models.Payment(clinic_id=cid, customer_id=customer.id, booking_id=bk.id,
                         type=ptype, amount=amount, status="paid", paid_at=datetime.utcnow())
    db.add(pay)
    db.commit()
    return bk, pay


def _standalone_payment(db, cid, customer, amount):
    """A custom charge — no booking at all, so its branch can only come from
    the customer's own branch_id."""
    pay = models.Payment(clinic_id=cid, customer_id=customer.id, booking_id=None,
                         type="custom", amount=amount, status="paid", paid_at=datetime.utcnow())
    db.add(pay)
    db.commit()
    return pay


def test_payments_list_filters_by_booking_branch(db, auth_client):
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Second Branch")
    db.add(b2)
    db.commit()

    cust1 = _customer(db, cid, None, name="Ann")   # branch-less customer, booked at b1
    cust2 = _customer(db, cid, None, name="Bea")
    _booking_payment(db, cid, cust1, b1.id, 1000)
    _booking_payment(db, cid, cust2, b2.id, 2000)

    r1 = auth_client.get(f"/api/payments?branch_id={b1.id}").json()
    r2 = auth_client.get(f"/api/payments?branch_id={b2.id}").json()
    rall = auth_client.get("/api/payments").json()

    assert [p["amount"] for p in r1] == [1000]
    assert [p["amount"] for p in r2] == [2000]
    assert len(rall) == 2


def test_payments_list_filters_standalone_charge_by_customer_branch(db, auth_client):
    """A custom charge has no booking — it must still be attributed to the
    customer's own branch, not disappear from every branch filter."""
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Second Branch")
    db.add(b2)
    db.commit()

    cust = _customer(db, cid, b1.id, name="Cara")
    _standalone_payment(db, cid, cust, 1500)

    r1 = auth_client.get(f"/api/payments?branch_id={b1.id}").json()
    r2 = auth_client.get(f"/api/payments?branch_id={b2.id}").json()
    assert [p["amount"] for p in r1] == [1500]
    assert r2 == []


def test_payments_summary_per_branch_sums_to_all(db, auth_client):
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Branch B")
    db.add(b2)
    db.commit()

    cust1 = _customer(db, cid, None, name="Dee")
    cust2 = _customer(db, cid, None, name="Eve")
    _booking_payment(db, cid, cust1, b1.id, 1000)
    _booking_payment(db, cid, cust2, b2.id, 2500)

    s1 = auth_client.get(f"/api/payments/summary?branch_id={b1.id}").json()
    s2 = auth_client.get(f"/api/payments/summary?branch_id={b2.id}").json()
    sall = auth_client.get("/api/payments/summary").json()

    assert s1["revenue"] == 1000
    assert s2["revenue"] == 2500
    assert sall["revenue"] == s1["revenue"] + s2["revenue"] == 3500


def test_payments_list_combines_status_and_branch_filters(db, auth_client):
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Second Branch")
    db.add(b2)
    db.commit()

    cust1 = _customer(db, cid, None, name="Fon")
    cust2 = _customer(db, cid, None, name="Gee")
    _booking_payment(db, cid, cust1, b1.id, 1000, ptype="deposit")   # -> "booked"
    _booking_payment(db, cid, cust2, b1.id, 2000, ptype="full")      # -> "paid"

    booked_b1 = auth_client.get(f"/api/payments?branch_id={b1.id}&status=booked").json()
    paid_b1 = auth_client.get(f"/api/payments?branch_id={b1.id}&status=paid").json()
    booked_b2 = auth_client.get(f"/api/payments?branch_id={b2.id}&status=booked").json()

    assert [p["amount"] for p in booked_b1] == [1000]
    assert [p["amount"] for p in paid_b1] == [2000]
    assert booked_b2 == []


def test_a_deposit_later_topped_up_to_full_moves_out_of_the_deposit_bucket(db, auth_client):
    """A booking that paid a deposit and later paid the remaining balance in full ends
    up with TWO paid Payment rows (create_payment never edits the deposit row — the
    top-up is its own row, for just the remaining amount). Counting both as separate
    "achievements" forever double-counted the same booking into both deposit_paid AND
    paid, and the "จองแล้ว" tab kept listing it as still just-deposited even after full
    settlement. The booking's CURRENT state is "paid" — it should count and list there
    only, not in both."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    cust = _customer(db, cid, branch.id, name="Hana")
    bk, deposit = _booking_payment(db, cid, cust, branch.id, 1800, ptype="deposit")
    # a SEPARATE row for the remaining balance, same booking
    full = models.Payment(clinic_id=cid, customer_id=cust.id, booking_id=bk.id,
                          type="full", amount=7100, status="paid", paid_at=datetime.utcnow())
    db.add(full)
    db.commit()

    summary = auth_client.get("/api/payments/summary").json()
    assert summary["deposit_paid"] == 0        # no longer counted as "still just deposited"
    assert summary["paid"] == 1                 # counted once, as fully settled
    assert summary["revenue"] == 1800 + 7100    # both real payments still add to revenue

    booked = auth_client.get("/api/payments?status=booked").json()
    paid = auth_client.get("/api/payments?status=paid").json()
    assert booked == []                          # the deposit row no longer appears here
    assert [p["amount"] for p in paid] == [7100]


def test_a_deposit_with_no_later_topup_still_counts_as_deposit(db, auth_client):
    """The ordinary, unfinished case must be unaffected: a booking that has ONLY paid
    its deposit still counts and lists as deposit_paid / "booked"."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    cust = _customer(db, cid, branch.id, name="Ivy")
    _booking_payment(db, cid, cust, branch.id, 1800, ptype="deposit")

    summary = auth_client.get("/api/payments/summary").json()
    assert summary["deposit_paid"] == 1
    assert summary["paid"] == 0

    booked = auth_client.get("/api/payments?status=booked").json()
    assert [p["amount"] for p in booked] == [1800]


def test_period_filter_excludes_old_paid_payments(db, auth_client):
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    cust_old = _customer(db, cid, branch.id, name="Jo")
    cust_new = _customer(db, cid, branch.id, name="Kai")
    bk_old, pay_old = _booking_payment(db, cid, cust_old, branch.id, 1000)
    pay_old.paid_at = datetime.utcnow() - timedelta(days=60)
    _booking_payment(db, cid, cust_new, branch.id, 2000)
    db.commit()

    r30 = auth_client.get("/api/payments?period=30d").json()
    r90 = auth_client.get("/api/payments?period=90d").json()
    rall = auth_client.get("/api/payments").json()   # no period -> unfiltered, today's default

    assert [p["amount"] for p in r30] == [2000]
    assert sorted(p["amount"] for p in r90) == [1000, 2000]
    assert sorted(p["amount"] for p in rall) == [1000, 2000]

    s30 = auth_client.get("/api/payments/summary?period=30d").json()
    assert s30["revenue"] == 2000


def test_period_filter_falls_back_to_created_at_for_unsettled_payments(db, auth_client):
    """A pending/failed row has no paid_at yet — the period must still bound it,
    using when it was CREATED, or every unsettled payment ever made would leak into
    every period no matter how narrow."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    cust = _customer(db, cid, branch.id, name="Lin")
    svc = db.query(models.Service).filter_by(clinic_id=cid).first()
    bk = models.Booking(clinic_id=cid, customer_id=cust.id, branch_id=branch.id,
                        service_id=svc.id, slot_at=datetime.utcnow(), status="confirmed")
    db.add(bk)
    db.flush()
    pending = models.Payment(clinic_id=cid, customer_id=cust.id, booking_id=bk.id,
                             type="deposit", amount=500, status="pending",
                             created_at=datetime.utcnow() - timedelta(days=60))
    db.add(pending)
    db.commit()

    r30 = auth_client.get("/api/payments?period=30d&status=pending").json()
    r90 = auth_client.get("/api/payments?period=90d&status=pending").json()
    assert r30 == []
    assert [p["amount"] for p in r90] == [500]


def test_period_all_surfaces_records_older_than_a_year(db, auth_client):
    """period=all is the escape hatch for a clinic open more than a year — 1y must
    NOT show a payment from before then, but "all" must."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    cust = _customer(db, cid, branch.id, name="Veteran")
    bk, pay = _booking_payment(db, cid, cust, branch.id, 3000)
    pay.paid_at = datetime.utcnow() - timedelta(days=400)
    db.commit()

    r1y = auth_client.get("/api/payments?period=1y").json()
    rall = auth_client.get("/api/payments?period=all").json()
    s1y = auth_client.get("/api/payments/summary?period=1y").json()
    sall = auth_client.get("/api/payments/summary?period=all").json()

    assert r1y == []
    assert [p["amount"] for p in rall] == [3000]
    assert s1y["revenue"] == 0
    assert sall["revenue"] == 3000
