"""Per-branch Customers view must not be empty.

Web / LINE / Messenger leads are created by ``handle_inbound`` before any branch
is known, so ``Customer.branch_id`` stays NULL. Filtering the Customers page on
that column alone showed every branch as empty even though the customers had
bookings and conversations at a real branch. The list + pipeline counts now use
the EFFECTIVE branch (own → booked → chatted), like the dashboard already did.
"""
from datetime import datetime, timedelta

from app import models
from app.scope import customer_branch_map


def _branches(db, clinic):
    existing = (db.query(models.Branch).filter_by(clinic_id=clinic.id)
                .order_by(models.Branch.id).all())
    b2 = models.Branch(clinic_id=clinic.id, name="Second Branch", address="x")
    db.add(b2)
    db.commit()
    return existing[0], b2


def _customer(db, clinic, name, branch_id=None):
    c = models.Customer(clinic_id=clinic.id, name=name, channel="web",
                        channel_user_id=name, branch_id=branch_id,
                        pipeline_stage="booked", last_activity_at=datetime.utcnow())
    db.add(c)
    db.commit()
    return c


def _service(db, clinic):
    return (db.query(models.Service).filter_by(clinic_id=clinic.id)
            .order_by(models.Service.id).first())


def test_customer_branch_map_falls_back_to_booking_then_conversation(db, clinic):
    b1, b2 = _branches(db, clinic)
    own = _customer(db, clinic, "own", branch_id=b1.id)
    booked = _customer(db, clinic, "booked")
    chatted = _customer(db, clinic, "chatted")
    orphan = _customer(db, clinic, "orphan")

    svc = _service(db, clinic)
    db.add(models.Booking(clinic_id=clinic.id, customer_id=booked.id, branch_id=b2.id,
                          service_id=svc.id, slot_at=datetime.utcnow() + timedelta(days=1),
                          status="pending", price=1000))
    db.add(models.Conversation(clinic_id=clinic.id, customer_id=chatted.id,
                               channel="web", branch_id=b2.id))
    db.commit()

    m = customer_branch_map(db, clinic.id)
    assert m[own.id] == b1.id
    assert m[booked.id] == b2.id
    assert m[chatted.id] == b2.id
    assert m[orphan.id] is None


def test_own_branch_wins_over_a_booking_at_another_branch(db, clinic):
    b1, b2 = _branches(db, clinic)
    cust = _customer(db, clinic, "visitor", branch_id=b1.id)
    svc = _service(db, clinic)
    db.add(models.Booking(clinic_id=clinic.id, customer_id=cust.id, branch_id=b2.id,
                          service_id=svc.id, slot_at=datetime.utcnow() + timedelta(days=1),
                          status="pending", price=1000))
    db.commit()
    assert customer_branch_map(db, clinic.id)[cust.id] == b1.id


def test_branch_filtered_list_and_pipeline_include_branchless_customers(db, clinic, auth_client):
    b1, b2 = _branches(db, clinic)
    booked = _customer(db, clinic, "booked-at-b2")
    other = _customer(db, clinic, "at-b1", branch_id=b1.id)

    svc = _service(db, clinic)
    db.add(models.Booking(clinic_id=clinic.id, customer_id=booked.id, branch_id=b2.id,
                          service_id=svc.id, slot_at=datetime.utcnow() + timedelta(days=1),
                          status="pending", price=1000))
    db.commit()

    rows = auth_client.get(f"/api/customers?branch_id={b2.id}").json()
    assert [r["name"] for r in rows] == ["booked-at-b2"]
    assert auth_client.get(f"/api/customers/pipeline?branch_id={b2.id}").json()["booked"] == 1

    rows = auth_client.get(f"/api/customers?branch_id={b1.id}").json()
    assert [r["name"] for r in rows] == ["at-b1"]

    all_rows = auth_client.get("/api/customers").json()
    assert {r["name"] for r in all_rows} == {"booked-at-b2", "at-b1"}


def test_branch_filter_never_leaks_another_clinic(db, make_clinic, auth_client):
    """The effective-branch map is clinic-scoped — an id from clinic B can't match."""
    clinic_a = auth_client.test_clinic
    b1, b2 = _branches(db, clinic_a)
    _customer(db, clinic_a, "a-cust", branch_id=b1.id)

    clinic_b = make_clinic("Clinic B", slug="clinic-b")
    _customer(db, clinic_b, "b-cust", branch_id=b2.id)   # deliberately clinic A's branch

    rows = auth_client.get(f"/api/customers?branch_id={b2.id}").json()
    assert rows == []


def test_booking_gives_a_branchless_customer_a_home_branch(db, clinic):
    from app.services.booking import create_booking

    b1, _b2 = _branches(db, clinic)
    cust = _customer(db, clinic, "lead")
    assert cust.branch_id is None

    create_booking(db, customer=cust, service=_service(db, clinic), branch_id=b1.id,
                   slot_at=datetime.utcnow() + timedelta(days=1))
    db.commit()
    db.refresh(cust)
    assert cust.branch_id == b1.id
