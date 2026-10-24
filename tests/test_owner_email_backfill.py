"""The seeded owner login moves to owner@blinksb.co on an already-seeded database.

The seed only runs on an empty DB, so without the startup backfill a deployed clinic
kept owner@clinic.co while the login page advertised the new address.
"""
from app import models
from app.security import hash_password, verify_password
from app.seed import OLD_OWNER_EMAIL, OWNER_EMAIL, backfill_owner_email


def _user(db, clinic, email, role="owner"):
    u = models.User(clinic_id=clinic.id, name="Owner", email=email,
                    password_hash=hash_password("demo1234"), role=role)
    db.add(u)
    db.commit()
    return u


def test_old_owner_address_is_renamed_and_keeps_its_password(db, make_clinic):
    clinic = make_clinic()
    u = _user(db, clinic, OLD_OWNER_EMAIL)
    assert backfill_owner_email(db) == 1
    db.expire_all()
    u = db.get(models.User, u.id)
    assert u.email == OWNER_EMAIL
    assert verify_password("demo1234", u.password_hash)
    assert backfill_owner_email(db) == 0, "idempotent"


def test_never_renames_when_the_new_address_is_taken(db, make_clinic):
    clinic = make_clinic()
    _user(db, clinic, OWNER_EMAIL)
    old = _user(db, clinic, OLD_OWNER_EMAIL)
    assert backfill_owner_email(db) == 0
    db.expire_all()
    assert db.get(models.User, old.id).email == OLD_OWNER_EMAIL


def test_only_an_owner_is_renamed(db, make_clinic):
    clinic = make_clinic()
    u = _user(db, clinic, OLD_OWNER_EMAIL, role="sales")
    assert backfill_owner_email(db) == 0
    db.expire_all()
    assert db.get(models.User, u.id).email == OLD_OWNER_EMAIL
