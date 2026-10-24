"""Multi-tenant isolation regression tests.

Three things must hold for the per-clinic tenancy model to be safe:
  1. ``app.scope.scoped`` only ever returns rows for the requested clinic.
  2. Over HTTP, a clinic's owner cannot enter or read another clinic's data.
  3. A customer merged into a golden record (``merged_into_id`` set) is a *stub*
     that must be hidden from every list and excluded from broadcast aggregates.
"""
from fastapi.testclient import TestClient

from app import models
from app.main import app
from app.routers.broadcast import _audience


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _add_customer(db, clinic, name, **kw) -> models.Customer:
    c = models.Customer(clinic_id=clinic.id, name=name, **kw)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _authed_client(clinic, make_owner, email) -> TestClient:
    """A fresh TestClient (own cookie jar) logged in as `clinic`'s owner and
    entered into it."""
    _u, pw = make_owner(clinic, email=email)
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    r = c.post(f"/api/clinics/{clinic.id}/enter")
    assert r.status_code == 200, r.text
    return c


# --------------------------------------------------------------------------- #
# 1. scoped() — the isolation chokepoint
# --------------------------------------------------------------------------- #
def test_scoped_returns_only_requested_clinic(db, make_clinic):
    from app.scope import scoped

    a = make_clinic("Iso A", slug="iso-a")
    b = make_clinic("Iso B", slug="iso-b")
    ca = _add_customer(db, a, "Alice A", phone="0810000001")
    cb = _add_customer(db, b, "Bob B", phone="0810000002")

    a_rows = scoped(db, models.Customer, a.id).all()
    b_rows = scoped(db, models.Customer, b.id).all()

    a_ids = {c.id for c in a_rows}
    b_ids = {c.id for c in b_rows}

    assert ca.id in a_ids
    assert cb.id not in a_ids          # B's customer never leaks into A's scope
    assert cb.id in b_ids
    assert ca.id not in b_ids
    # And every returned row really does belong to the requested clinic.
    assert all(c.clinic_id == a.id for c in a_rows)
    assert all(c.clinic_id == b.id for c in b_rows)


# --------------------------------------------------------------------------- #
# 2. HTTP-level isolation
# --------------------------------------------------------------------------- #
def test_owner_cannot_enter_another_clinic(db, make_clinic, make_owner):
    a = make_clinic("HTTP A", slug="http-a")
    b = make_clinic("HTTP B", slug="http-b")
    a_client = _authed_client(a, make_owner, "owner@http-a.co")

    # Clinic B exists and is active, but A's owner has no access → 403 (not 404).
    r = a_client.post(f"/api/clinics/{b.id}/enter")
    assert r.status_code == 403, r.text

    # A non-existent clinic id is a 404.
    r = a_client.post("/api/clinics/999999/enter")
    assert r.status_code == 404, r.text


def test_list_customers_isolated_between_clinics(db, make_clinic, make_owner):
    a = make_clinic("List A", slug="list-a")
    b = make_clinic("List B", slug="list-b")
    a_cust = _add_customer(db, a, "Alice In A", phone="0820000001")
    b_cust = _add_customer(db, b, "Bob In B", phone="0820000002")

    a_client = _authed_client(a, make_owner, "owner@list-a.co")
    b_client = _authed_client(b, make_owner, "owner@list-b.co")

    a_rows = a_client.get("/api/customers").json()
    b_rows = b_client.get("/api/customers").json()

    a_ids = {row["id"] for row in a_rows}
    b_ids = {row["id"] for row in b_rows}

    # A's client sees A's customer and never B's; B's client is the mirror image.
    assert a_cust.id in a_ids
    assert b_cust.id not in a_ids
    assert b_cust.id in b_ids
    assert a_cust.id not in b_ids


def test_cannot_read_other_clinics_customer_by_id(db, make_clinic, make_owner):
    a = make_clinic("ById A", slug="byid-a")
    b = make_clinic("ById B", slug="byid-b")
    b_cust = _add_customer(db, b, "Hidden B", phone="0830000001")

    a_client = _authed_client(a, make_owner, "owner@byid-a.co")
    # Asking A's session for B's customer id must 404, not leak the record.
    r = a_client.get(f"/api/customers/{b_cust.id}")
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# 3. Merged stub excluded from lists + aggregates
# --------------------------------------------------------------------------- #
def test_merged_stub_excluded_from_list_and_audience(db, auth_client):
    clinic = auth_client.test_clinic
    # Two records for the same person (shared phone); the duplicate gets merged
    # into the primary by setting merged_into_id directly.
    primary = _add_customer(db, clinic, "Real Person", phone="0840001234",
                            channel="web")
    dup = _add_customer(db, clinic, "LINE User", phone="6684 000 1234",
                        channel="line", channel_user_id="U-dup")
    dup.merged_into_id = primary.id
    db.commit()

    # --- HTTP list excludes the stub -------------------------------------- #
    rows = auth_client.get("/api/customers").json()
    ids = {row["id"] for row in rows}
    assert primary.id in ids
    assert dup.id not in ids

    # --- broadcast audience aggregate excludes the stub ------------------- #
    audience = _audience(db, {}, clinic.id)
    aud_ids = {c.id for c in audience}
    assert primary.id in aud_ids
    assert dup.id not in aud_ids
    # The stub is not double-counting the same human in the campaign size.
    assert len(audience) == sum(1 for c in audience if c.merged_into_id is None)
    assert dup.id not in aud_ids


def test_pipeline_counts_exclude_merged_stub(db, auth_client):
    """The pipeline summary aggregate must also drop merged stubs."""
    clinic = auth_client.test_clinic
    primary = _add_customer(db, clinic, "Keeper", phone="0850009999",
                            pipeline_stage="interested")
    dup = _add_customer(db, clinic, "Web Visitor", phone="0850009999",
                        pipeline_stage="interested", merged_into_id=primary.id)
    db.commit()

    counts = auth_client.get("/api/customers/pipeline").json()
    # Exactly one "interested" record despite two rows — the stub is uncounted.
    assert counts["interested"] == 1
