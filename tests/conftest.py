"""Shared pytest fixtures for the Blinks Bright regression suite.

The whole suite runs against a THROWAWAY SQLite database and with the external
services (OpenAI / Gemini) disabled, so tests are fast, deterministic
and never touch the network or the real ``clinic.db``.

Key fixtures:
  - ``db``          a SQLAlchemy session on the fresh test DB
  - ``client``      a FastAPI ``TestClient`` (lifespan NOT run → no seeding/threads)
  - ``make_clinic`` factory → provision an isolated clinic
  - ``owner`` / ``auth_client`` a logged-in client scoped into a clinic
"""
import os
import tempfile

# Bind the engine to a throwaway DB BEFORE importing the app (the engine is built
# from settings.db_path at import time).
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="bb-test-"), "test.db")

import pytest  # noqa: E402

from app.config import settings  # noqa: E402

# Never reach a real external service from a test.
settings.openai_api_key = ""
settings.gemini_api_key = ""
settings.resend_api_key = ""

from app import models  # noqa: E402,F401  (registers models on the metadata)
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.seed import provision_clinic  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """Drop + recreate every table before each test → full isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _no_payment_qr(tmp_path_factory, monkeypatch):
    """No payment QR unless a test asks for one (``qr_file``) — so the suite behaves the
    same whether or not the real web/assets/images/payment-qr.png has been added."""
    from app.services import promptpay
    monkeypatch.setattr(promptpay, "WEB_DIR", tmp_path_factory.mktemp("no-qr-web"))


@pytest.fixture
def qr_file(tmp_path, monkeypatch):
    """A payment QR image on disk, served at the configured path."""
    from app.services import promptpay
    (tmp_path / "assets" / "images").mkdir(parents=True)
    (tmp_path / "assets" / "images" / "payment-qr.png").write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(promptpay, "WEB_DIR", tmp_path)
    monkeypatch.setattr(promptpay.settings, "payment_qr_image", "/assets/images/payment-qr.png")
    return "/assets/images/payment-qr.png"


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def make_clinic(db):
    """Factory: provision a fully-usable clinic (branch + starter catalog/prices)."""
    n = {"i": 0}

    def _make(name=None, slug=None, **kw):
        n["i"] += 1
        name = name or f"Test Clinic {n['i']}"
        slug = slug or f"test-clinic-{n['i']}"
        c = provision_clinic(db, name, slug=slug, **kw)
        db.commit()
        return c

    return _make


@pytest.fixture
def clinic(make_clinic):
    return make_clinic("Clinic A", slug="clinic-a")


@pytest.fixture
def make_owner(db):
    """Factory: create an owner login for a clinic with a known password."""
    def _make(clinic, email=None, password="pw", role="owner"):
        email = email or f"owner-{clinic.id}@test.co"
        u = models.User(clinic_id=clinic.id, name="Owner", email=email,
                        password_hash=hash_password(password), role=role, active=True)
        db.add(u)
        db.commit()
        return u, password

    return _make


@pytest.fixture
def owner(make_owner, clinic):
    u, _pw = make_owner(clinic)
    return u


@pytest.fixture
def client():
    # No `with` → the lifespan (seeding / KB index / scheduler) does NOT run.
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture
def auth_client(client, clinic, make_owner):
    """A TestClient logged in as the clinic's owner and entered into it."""
    _u, pw = make_owner(clinic, email="owner@a.co")
    r = client.post("/api/auth/login", json={"email": "owner@a.co", "password": pw})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/clinics/{clinic.id}/enter")
    assert r.status_code == 200, r.text
    client.test_clinic = clinic  # convenience handle for tests
    return client
