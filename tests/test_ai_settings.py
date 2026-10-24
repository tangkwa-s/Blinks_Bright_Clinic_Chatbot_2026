"""Regression tests for the per-clinic AI-assistant settings.

GET /api/clinic/ai-settings is open to any logged-in clinic user and defaults to
empty; PATCH is guarded by MANAGER (branch_manager / marketing, elevated pass),
strips whitespace, enforces the 60 / 2000 char limits (400 when over), and
round-trips {ai_name, ai_instructions}.
"""
from app import models


def _login_as(client, clinic, make_owner, role, email):
    """A client logged in with the given role and entered into the clinic."""
    _u, pw = make_owner(clinic, email=email, role=role)
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/clinics/{clinic.id}/enter")
    assert r.status_code == 200, r.text
    return client


# ---------------------------------------------------------------------------
# Defaults + round-trip
# ---------------------------------------------------------------------------
def test_get_defaults_empty(auth_client):
    r = auth_client.get("/api/clinic/ai-settings")
    assert r.status_code == 200, r.text
    assert r.json() == {"ai_name": "", "ai_instructions": "", "hold_minutes": 0}


def test_patch_saves_and_round_trips(db, auth_client):
    r = auth_client.patch("/api/clinic/ai-settings", json={
        "ai_name": "  น้องฟ้า  ",
        "ai_instructions": "  Speak politely, end with ka.  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"ai_name": "น้องฟ้า",
                        "ai_instructions": "Speak politely, end with ka.",
                        "hold_minutes": 0}
    # persisted on the Clinic row and returned by a fresh GET
    db.expire_all()
    clinic = db.get(models.Clinic, auth_client.test_clinic.id)
    assert clinic.ai_name == "น้องฟ้า"
    assert clinic.ai_instructions == "Speak politely, end with ka."
    r = auth_client.get("/api/clinic/ai-settings")
    assert r.json() == {"ai_name": "น้องฟ้า",
                        "ai_instructions": "Speak politely, end with ka.",
                        "hold_minutes": 0}


def test_patch_partial_keeps_other_field(auth_client):
    auth_client.patch("/api/clinic/ai-settings",
                      json={"ai_name": "Fah", "ai_instructions": "Be warm."})
    r = auth_client.patch("/api/clinic/ai-settings", json={"ai_name": "Ploy"})
    assert r.status_code == 200
    assert r.json() == {"ai_name": "Ploy", "ai_instructions": "Be warm.", "hold_minutes": 0}


# ---------------------------------------------------------------------------
# hold_minutes — 0 is the valid "use the .env default" sentinel, not clamped away
# ---------------------------------------------------------------------------
def test_hold_minutes_saves_and_round_trips(db, auth_client):
    r = auth_client.patch("/api/clinic/ai-settings", json={"hold_minutes": 15})
    assert r.status_code == 200, r.text
    assert r.json()["hold_minutes"] == 15
    db.expire_all()
    clinic = db.get(models.Clinic, auth_client.test_clinic.id)
    assert clinic.hold_minutes == 15


def test_hold_minutes_clamps_at_the_ceiling(auth_client):
    from app.services.booking import MAX_HOLD_MINUTES

    r = auth_client.patch("/api/clinic/ai-settings",
                          json={"hold_minutes": MAX_HOLD_MINUTES * 10})
    assert r.status_code == 200, r.text
    assert r.json()["hold_minutes"] == MAX_HOLD_MINUTES


def test_hold_minutes_negative_clamps_to_zero(auth_client):
    r = auth_client.patch("/api/clinic/ai-settings", json={"hold_minutes": -5})
    assert r.status_code == 200, r.text
    assert r.json()["hold_minutes"] == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_over_length_name_rejected(auth_client):
    r = auth_client.patch("/api/clinic/ai-settings", json={"ai_name": "x" * 61})
    assert r.status_code == 400
    # nothing was saved
    assert auth_client.get("/api/clinic/ai-settings").json()["ai_name"] == ""


def test_over_length_instructions_rejected(auth_client):
    r = auth_client.patch("/api/clinic/ai-settings",
                          json={"ai_instructions": "x" * 2001})
    assert r.status_code == 400
    assert auth_client.get("/api/clinic/ai-settings").json()["ai_instructions"] == ""


def test_max_length_values_accepted(auth_client):
    r = auth_client.patch("/api/clinic/ai-settings", json={
        "ai_name": "n" * 60, "ai_instructions": "i" * 2000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["ai_name"]) == 60
    assert len(body["ai_instructions"]) == 2000


# ---------------------------------------------------------------------------
# Role guard (MANAGER = branch_manager / marketing; elevated pass)
# ---------------------------------------------------------------------------
def test_marketing_can_patch(client, clinic, make_owner):
    c = _login_as(client, clinic, make_owner, "marketing", "marketing@a.co")
    r = c.patch("/api/clinic/ai-settings", json={"ai_name": "Fah"})
    assert r.status_code == 200, r.text
    assert r.json()["ai_name"] == "Fah"


def test_sales_cannot_patch_but_can_read(client, clinic, make_owner):
    c = _login_as(client, clinic, make_owner, "sales", "sales@a.co")
    r = c.get("/api/clinic/ai-settings")
    assert r.status_code == 200, r.text
    r = c.patch("/api/clinic/ai-settings", json={"ai_name": "Nope"})
    assert r.status_code == 403
    assert c.get("/api/clinic/ai-settings").json()["ai_name"] == ""
