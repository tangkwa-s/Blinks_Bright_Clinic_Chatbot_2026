"""Smoke tests — prove the fixtures (throwaway DB, no seeding, auth) work."""


def test_db_is_empty_no_seeding(db):
    """The lifespan must NOT run for TestClient/db fixtures — no demo clinics seeded."""
    from app import models
    assert db.query(models.Clinic).count() == 0


def test_provision_clinic_creates_branch_and_services(make_clinic, db):
    from app import models
    c = make_clinic()
    assert c.id
    branches = db.query(models.Branch).filter_by(clinic_id=c.id).count()
    services = db.query(models.Service).filter_by(clinic_id=c.id).count()
    assert branches >= 1
    assert services >= 1


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_client_is_scoped_into_its_clinic(auth_client):
    """A logged-in + entered client can read its own clinic's customers (200, not 409)."""
    r = auth_client.get("/api/customers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_unauthenticated_is_rejected(client):
    r = client.get("/api/customers")
    assert r.status_code in (401, 403, 409)
