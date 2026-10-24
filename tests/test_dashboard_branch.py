"""Dashboard per-branch attribution.

Regression: a Customer created without a branch (web / AI leads have branch_id=None)
still BOOKS at a specific branch, so its revenue + lead must show under that branch.
The dashboard used to attribute revenue/leads by customer.branch_id, leaving every
per-branch view at 0 while the booking count was right.
"""
from datetime import datetime, timedelta

from app import models


def _seed_no_branch_paid_booking(db, cid, branch_id, amount):
    svc = db.query(models.Service).filter_by(clinic_id=cid).first()
    cust = models.Customer(clinic_id=cid, name="No-Branch Lead", channel="web",
                           channel_user_id=f"nb-{branch_id}-{amount}", branch_id=None)
    db.add(cust)
    db.flush()
    bk = models.Booking(clinic_id=cid, customer_id=cust.id, branch_id=branch_id,
                        service_id=svc.id, slot_at=datetime.utcnow(), status="confirmed")
    db.add(bk)
    db.flush()
    pay = models.Payment(clinic_id=cid, customer_id=cust.id, booking_id=bk.id,
                         type="deposit", amount=amount, status="paid",
                         paid_at=datetime.utcnow())
    db.add(pay)
    db.commit()
    return cust, bk, pay


def _pending_payment(db, cid, branch_id, amount, name, created_at=None):
    svc = db.query(models.Service).filter_by(clinic_id=cid).first()
    cust = models.Customer(clinic_id=cid, name=name, channel="web",
                           channel_user_id=f"pend-{name}")
    db.add(cust)
    db.flush()
    bk = models.Booking(clinic_id=cid, customer_id=cust.id, branch_id=branch_id,
                        service_id=svc.id, slot_at=datetime.utcnow(), status="pending")
    db.add(bk)
    db.flush()
    pay = models.Payment(clinic_id=cid, customer_id=cust.id, booking_id=bk.id,
                         type="deposit", amount=amount, status="pending",
                         created_at=created_at or datetime.utcnow())
    db.add(pay)
    db.commit()
    return cust, bk, pay


def test_dashboard_reports_pending_payments(db, auth_client):
    """The "รอชำระ" card mirrors payments.py::payments_summary's own pending count —
    a still-open payment link, bounded by when it was CREATED (it has no paid_at yet)."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    _pending_payment(db, cid, branch.id, 1800, "Waiting")

    d = auth_client.get("/api/dashboard?period=30d").json()
    assert d["stats"]["pending"] == 1
    assert d["sparks"]["pending"][-1] >= 1     # today's bucket carries it


def test_dashboard_pending_respects_branch_filter(db, auth_client):
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Branch B (pending)")
    db.add(b2)
    db.commit()

    _pending_payment(db, cid, b1.id, 1800, "AtB1")
    _pending_payment(db, cid, b2.id, 900, "AtB2")

    d1 = auth_client.get(f"/api/dashboard?branch_id={b1.id}&period=30d").json()
    d2 = auth_client.get(f"/api/dashboard?branch_id={b2.id}&period=30d").json()
    dall = auth_client.get("/api/dashboard?period=30d").json()
    assert d1["stats"]["pending"] == 1
    assert d2["stats"]["pending"] == 1
    assert dall["stats"]["pending"] == 2


def test_dashboard_pending_respects_period_filter(db, auth_client):
    """A payment link opened 60 days ago and never paid must not still show up in the
    30-day view — same reasoning as payments.py's own period fallback for unsettled
    rows (no paid_at yet, so bound by created_at instead)."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    _pending_payment(db, cid, branch.id, 1800, "Old",
                     created_at=datetime.utcnow() - timedelta(days=60))
    _pending_payment(db, cid, branch.id, 900, "New")

    d30 = auth_client.get("/api/dashboard?period=30d").json()
    d90 = auth_client.get("/api/dashboard?period=90d").json()
    assert d30["stats"]["pending"] == 1
    assert d90["stats"]["pending"] == 2


def test_dashboard_and_payments_page_agree_on_pending_count(db, auth_client):
    """The exact cross-page consistency the "รอชำระ" card exists to give: same branch,
    same period, same underlying rows -> the two pages must show the same number."""
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Branch B (agree)")
    db.add(b2)
    db.commit()

    _pending_payment(db, cid, b1.id, 1800, "AgreeA")
    _pending_payment(db, cid, b2.id, 900, "AgreeB")
    _pending_payment(db, cid, b1.id, 500, "AgreeOld",
                     created_at=datetime.utcnow() - timedelta(days=60))

    for params in ("period=30d", "period=90d", f"period=30d&branch_id={b1.id}",
                  f"period=90d&branch_id={b2.id}"):
        dash = auth_client.get(f"/api/dashboard?{params}").json()["stats"]["pending"]
        pay = auth_client.get(f"/api/payments/summary?{params}").json()["pending"]
        assert dash == pay, f"mismatch for {params}: dashboard={dash} payments={pay}"


def test_a_deposit_later_topped_up_to_full_moves_out_of_dashboard_deposit_count(db, auth_client):
    """Same fix as payments.py::payments_summary, applied here too: a booking that
    paid a deposit and later paid the remaining balance in full ends up with TWO paid
    Payment rows. Counting the deposit row forever left the dashboard's "ชำระค่ามัดจำ"
    card stuck showing a booking as still-just-deposited even after full settlement."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    svc = db.query(models.Service).filter_by(clinic_id=cid).first()
    cust = models.Customer(clinic_id=cid, name="Topped Up", channel="web",
                           channel_user_id="topup-1")
    db.add(cust)
    db.flush()
    bk = models.Booking(clinic_id=cid, customer_id=cust.id, branch_id=branch.id,
                        service_id=svc.id, slot_at=datetime.utcnow(), status="confirmed")
    db.add(bk)
    db.flush()
    db.add(models.Payment(clinic_id=cid, customer_id=cust.id, booking_id=bk.id,
                          type="deposit", amount=1800, status="paid",
                          paid_at=datetime.utcnow()))
    db.add(models.Payment(clinic_id=cid, customer_id=cust.id, booking_id=bk.id,
                          type="full", amount=7100, status="paid",
                          paid_at=datetime.utcnow()))
    db.commit()

    d = auth_client.get("/api/dashboard?period=90d").json()
    assert d["stats"]["deposit_paid"] == 0
    assert d["stats"]["revenue"] == 1800 + 7100    # both real payments still add up


def test_dashboard_attributes_revenue_and_leads_to_booking_branch(db, auth_client):
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Second Branch")
    db.add(b2)
    db.commit()

    # a branch-less customer who booked + paid at b1
    _seed_no_branch_paid_booking(db, cid, b1.id, 1500)

    d1 = auth_client.get(f"/api/dashboard?branch_id={b1.id}&period=90d").json()
    # revenue + the lead surface under b1 even though customer.branch_id is None
    assert d1["stats"]["revenue"] == 1500
    assert d1["stats"]["leads"] >= 1
    assert d1["stats"]["bookings"] >= 1

    d2 = auth_client.get(f"/api/dashboard?branch_id={b2.id}&period=90d").json()
    assert d2["stats"]["revenue"] == 0
    assert d2["stats"]["bookings"] == 0

    dall = auth_client.get("/api/dashboard?period=90d").json()
    assert dall["stats"]["revenue"] == 1500


def test_dashboard_branch_revenue_sums_to_all(db, auth_client):
    """Per-branch revenue must add up to the all-branches total, so the
    two views never disagree."""
    cid = auth_client.test_clinic.id
    b1 = db.query(models.Branch).filter_by(clinic_id=cid).first()
    b2 = models.Branch(clinic_id=cid, name="Branch B")
    b3 = models.Branch(clinic_id=cid, name="Branch C")
    db.add_all([b2, b3])
    db.commit()

    _seed_no_branch_paid_booking(db, cid, b1.id, 1000)
    _seed_no_branch_paid_booking(db, cid, b2.id, 2500)
    _seed_no_branch_paid_booking(db, cid, b3.id, 500)

    per = [auth_client.get(f"/api/dashboard?branch_id={b.id}&period=90d").json()["stats"]["revenue"]
           for b in (b1, b2, b3)]
    total = auth_client.get("/api/dashboard?period=90d").json()["stats"]["revenue"]
    assert per == [1000, 2500, 500]
    assert sum(per) == total == 4000


def test_dashboard_period_all_surfaces_records_older_than_a_year(db, auth_client):
    """period=all is the escape hatch for a clinic open more than a year — 1y must
    NOT show revenue from before then, but "all" must. Mirrors the identical fix on
    the Payments page."""
    cid = auth_client.test_clinic.id
    branch = db.query(models.Branch).filter_by(clinic_id=cid).first()
    cust, bk, pay = _seed_no_branch_paid_booking(db, cid, branch.id, 3000)
    pay.paid_at = datetime.utcnow() - timedelta(days=400)
    db.commit()

    d1y = auth_client.get("/api/dashboard?period=1y").json()
    dall = auth_client.get("/api/dashboard?period=all").json()
    assert d1y["stats"]["revenue"] == 0
    assert dall["stats"]["revenue"] == 3000
