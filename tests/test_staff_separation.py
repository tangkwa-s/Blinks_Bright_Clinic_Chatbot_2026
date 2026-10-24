"""Regression tests for the StaffMember-vs-User separation.

`StaffMember` (the clinical roster: doctors/therapists, assignable to bookings)
and `User` (login accounts) are two INDEPENDENT tables. These tests pin:

  * `/api/team-members` CRUD operates purely on `StaffMember` and never
    creates/modifies a `User` row.
  * `Booking.doctor_id` references a `StaffMember`, and `booking_dict` resolves
    the doctor name from that roster.
  * `seed.backfill_staff_members` migrates legacy doctor *Users* into the roster
    and remaps existing bookings — idempotently.
"""
from datetime import datetime, timedelta

from app import models
from app.routers.bookings import booking_dict
from app.seed import backfill_staff_members
from app.services.booking import create_booking


def _user_snapshot(db):
    """Map of every User id -> (name, role, email) — to detect any User mutation."""
    return {u.id: (u.name, u.role, u.email) for u in db.query(models.User).all()}


# ---------------------------------------------------------------------------
# /api/team-members CRUD never touches the Users table
# ---------------------------------------------------------------------------
def test_team_member_crud_is_isolated_from_users(auth_client, db):
    clinic = auth_client.test_clinic

    # Baseline: the owner login exists as a User; no StaffMembers yet.
    users_before = _user_snapshot(db)
    assert len(users_before) >= 1
    assert db.query(models.StaffMember).filter_by(clinic_id=clinic.id).count() == 0

    # CREATE -----------------------------------------------------------------
    r = auth_client.post("/api/team-members",
                         json={"name": "Dr. Siri", "role": "doctor",
                               "title": "Aesthetic Physician", "phone": "0812345678"})
    assert r.status_code == 200, r.text
    created = r.json()
    mid = created["id"]
    assert created["name"] == "Dr. Siri"
    assert created["role"] == "doctor"
    assert created["title"] == "Aesthetic Physician"
    assert created["active"] is True

    # A StaffMember row exists; no extra User was created.
    db.expire_all()
    sm = db.get(models.StaffMember, mid)
    assert sm is not None and sm.clinic_id == clinic.id and sm.role == "doctor"
    assert _user_snapshot(db) == users_before, "creating a team member must not add a User"

    # READ (list) ------------------------------------------------------------
    r = auth_client.get("/api/team-members")
    assert r.status_code == 200, r.text
    listing = r.json()
    assert [m["id"] for m in listing] == [mid]
    assert listing[0]["name"] == "Dr. Siri"

    # UPDATE name + role -----------------------------------------------------
    r = auth_client.patch(f"/api/team-members/{mid}",
                          json={"name": "Dr. Siri Anan", "role": "therapist"})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["name"] == "Dr. Siri Anan"
    assert updated["role"] == "therapist"

    db.expire_all()
    sm = db.get(models.StaffMember, mid)
    assert sm.name == "Dr. Siri Anan" and sm.role == "therapist"
    assert _user_snapshot(db) == users_before, "patching a team member must not touch Users"

    # DELETE -----------------------------------------------------------------
    r = auth_client.delete(f"/api/team-members/{mid}")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    db.expire_all()
    assert db.get(models.StaffMember, mid) is None
    assert auth_client.get("/api/team-members").json() == []
    # Users table untouched through the whole CRUD lifecycle.
    assert _user_snapshot(db) == users_before, "deleting a team member must not touch Users"


# ---------------------------------------------------------------------------
# Booking.doctor_id -> StaffMember, surfaced as doctor_name
# ---------------------------------------------------------------------------
def test_booking_doctor_name_resolves_from_staff_member(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    service = db.query(models.Service).filter_by(clinic_id=clinic.id, active=True).first()
    assert branch and service

    doctor = models.StaffMember(clinic_id=clinic.id, branch_id=branch.id,
                                name="Dr. Pim Wong", role="doctor",
                                title="Dermatologist", active=True)
    customer = models.Customer(clinic_id=clinic.id, name="Walk-in Guest",
                               branch_id=branch.id, channel="web")
    db.add_all([doctor, customer])
    db.commit()

    booking = create_booking(db, customer=customer, service=service,
                             branch_id=branch.id, slot_at=datetime.utcnow() + timedelta(days=1),
                             doctor_id=doctor.id, created_by="admin")
    db.commit()

    # The FK really points at the StaffMember, not a User.
    assert booking.doctor_id == doctor.id

    d = booking_dict(db, booking, clinic.id)
    assert d["doctor_name"] == "Dr. Pim Wong"
    # The schedule-tab dropdown selects its option from doctor_id, so the API must
    # return it (regression: only doctor_name was returned → the dropdown reset to
    # "no doctor" on re-render even though the assignment was saved).
    assert d["doctor_id"] == doctor.id
    assert d["service_id"] == service.id
    assert d["branch_id"] == branch.id

    # A booking with no doctor reports both as None.
    nodoc = create_booking(db, customer=customer, service=service,
                           branch_id=branch.id, slot_at=datetime.utcnow() + timedelta(days=2),
                           doctor_id=None, created_by="admin")
    db.commit()
    assert booking_dict(db, nodoc, clinic.id)["doctor_name"] is None
    assert booking_dict(db, nodoc, clinic.id)["doctor_id"] is None


# ---------------------------------------------------------------------------
# backfill_staff_members: legacy doctor Users -> StaffMember roster + remap
# ---------------------------------------------------------------------------
def test_backfill_mirrors_doctor_users_and_remaps_bookings(db, make_clinic):
    from app.security import hash_password

    # A filler clinic that already HAS a roster: advances the staff_members PK
    # sequence so the new StaffMember ids cannot collide with the doctor User
    # ids (making the remap assertion below meaningful), and confirms backfill
    # skips clinics that already have a roster.
    make_clinic("Filler", slug="filler",
                doctors=[("Dr. Filler One", "MD", ""), ("Dr. Filler Two", "MD", ""),
                         ("Dr. Filler Three", "MD", "")])

    # The target clinic: no StaffMembers, but legacy doctor *Users* + a booking
    # whose doctor_id points at one of those Users.
    clinic = make_clinic("Legacy", slug="legacy", starter=False)
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    assert db.query(models.StaffMember).filter_by(clinic_id=clinic.id).count() == 0

    doc_a = models.User(clinic_id=clinic.id, name="Dr. Alpha", email="alpha@legacy.co",
                        password_hash=hash_password("pw"), role="doctor",
                        title="Senior Physician", bio="A bio", phone="0810000001",
                        branch_id=branch.id, active=True)
    doc_b = models.User(clinic_id=clinic.id, name="Dr. Beta", email="beta@legacy.co",
                        password_hash=hash_password("pw"), role="doctor",
                        branch_id=branch.id, active=True)
    # A non-doctor User must be ignored by the backfill.
    sales = models.User(clinic_id=clinic.id, name="Sam Sales", email="sam@legacy.co",
                        password_hash=hash_password("pw"), role="sales",
                        branch_id=branch.id, active=True)
    service = models.Service(clinic_id=clinic.id, name="Consult", category="Consult",
                             base_price=1000, duration_min=30, active=True)
    customer = models.Customer(clinic_id=clinic.id, name="Patient", branch_id=branch.id)
    db.add_all([doc_a, doc_b, sales, service, customer])
    db.commit()

    booking = create_booking(db, customer=customer, service=service, branch_id=branch.id,
                             slot_at=datetime.utcnow() + timedelta(days=1),
                             doctor_id=doc_a.id, created_by="admin")
    db.commit()
    assert booking.doctor_id == doc_a.id  # initially a User id

    legacy_user_ids = {doc_a.id, doc_b.id}

    # --- run the migration --------------------------------------------------
    created = backfill_staff_members(db)
    assert created == 2, "two doctor Users should be mirrored (sales User ignored)"

    db.expire_all()
    roster = db.query(models.StaffMember).filter_by(clinic_id=clinic.id).all()
    assert {m.name for m in roster} == {"Dr. Alpha", "Dr. Beta"}
    assert all(m.role == "doctor" for m in roster)
    # Fields mirrored from the source Users.
    by_name = {m.name: m for m in roster}
    assert by_name["Dr. Alpha"].title == "Senior Physician"
    assert by_name["Dr. Alpha"].bio == "A bio"
    assert by_name["Dr. Alpha"].phone == "0810000001"
    # Default title applied when the source User had none.
    assert by_name["Dr. Beta"].title == "Aesthetic Physician"

    # The doctor Users are left intact as login accounts.
    assert db.get(models.User, doc_a.id) is not None
    assert db.get(models.User, doc_b.id) is not None

    # The booking was remapped from the User id to the matching StaffMember id.
    db.refresh(booking)
    assert booking.doctor_id not in legacy_user_ids
    new_doctor = db.get(models.StaffMember, booking.doctor_id)
    assert new_doctor is not None and new_doctor.clinic_id == clinic.id
    assert new_doctor.name == "Dr. Alpha"  # same person, now via the roster

    # --- idempotent ---------------------------------------------------------
    remapped_id = booking.doctor_id
    again = backfill_staff_members(db)
    assert again == 0, "second run must be a no-op"
    db.expire_all()
    assert db.query(models.StaffMember).filter_by(clinic_id=clinic.id).count() == 2
    db.refresh(booking)
    assert booking.doctor_id == remapped_id
