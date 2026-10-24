"""The customer portal (app/routers/portal.py).

The rule this file exists to hold: **a customer sees their own data and nothing
else.** Every account route resolves the customer from the signed cookie, never
from anything the client sends, so the tests below are mostly "customer B asks
for A's things and gets their own".
"""
import pytest

from app import models
from app.security import hash_password

PW = "secret12345"


def _register(client, phone="0812345678", name="คุณทดสอบ", password=PW, **kw):
    return client.post("/api/portal/register",
                       json={"name": name, "phone": phone, "password": password, **kw})


def _login(client, phone="0812345678", password=PW):
    return client.post("/api/portal/login", json={"phone": phone, "password": password})


@pytest.fixture
def clinic(make_clinic):
    return make_clinic()


# --------------------------------------------------------------- public
def test_home_is_public_and_publishes_only_catalog_content(client, db, clinic):
    cust = models.Customer(clinic_id=clinic.id, name="Someone Private",
                           channel="web", channel_user_id="w1", phone="0999999999")
    db.add(cust)
    db.commit()

    d = client.get("/api/portal/home").json()
    assert d["clinic"]["slug"] == clinic.slug
    assert d["services"] and d["branches"]
    blob = str(d)
    assert "Someone Private" not in blob and "0999999999" not in blob


# --------------------------------------------------------------- register
def test_register_signs_in_and_creates_a_customer(client, db, clinic):
    r = _register(client)
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "0812345678"
    cust = db.query(models.Customer).filter_by(phone="0812345678").one()
    assert cust.password_hash and cust.password_hash != PW   # stored hashed, never plain
    assert client.get("/api/portal/me").json()["id"] == cust.id


@pytest.mark.parametrize("phone", ["12345", "", "08123456789", "abcdefghij"])
def test_register_rejects_a_phone_that_is_not_a_thai_mobile(client, clinic, phone):
    assert _register(client, phone=phone).status_code == 400


def test_register_rejects_a_short_password(client, clinic):
    assert _register(client, password="short").status_code == 400


def test_register_claims_the_existing_crm_record_for_that_phone(client, db, clinic):
    """Someone who chatted with the AI already exists here. Registering must land on
    THAT record, or their bookings would be invisible to them."""
    existing = models.Customer(clinic_id=clinic.id, name="LINE User", phone="081-234-5678",
                               channel="line", channel_user_id="L1", ltv=4200)
    db.add(existing)
    db.commit()
    eid = existing.id

    assert _register(client).status_code == 200
    assert client.get("/api/portal/me").json()["id"] == eid
    assert db.query(models.Customer).filter_by(clinic_id=clinic.id).count() == 1


def test_register_refuses_a_phone_that_already_has_a_password(client, db, clinic):
    _register(client)
    client.post("/api/portal/logout")
    assert _register(client).status_code == 409


def test_register_refuses_when_the_phone_matches_several_records(client, db, clinic):
    """Ambiguous identity is a human's job, not a guess: picking one would hand the
    new account whichever duplicate happened to sort first."""
    for i in (1, 2):
        db.add(models.Customer(clinic_id=clinic.id, name=f"Dup {i}", phone="0812345678",
                               channel="web", channel_user_id=f"w{i}"))
    db.commit()
    assert _register(client).status_code == 409


# --------------------------------------------------------------- login
def test_login_works_and_normalises_the_phone_format(client, db, clinic):
    _register(client)
    client.post("/api/portal/logout")
    for typed in ("0812345678", "081-234-5678", "+66812345678"):
        assert _login(client, phone=typed).status_code == 200, typed
        client.post("/api/portal/logout")


def test_login_rejects_a_wrong_password_without_revealing_the_account(client, clinic):
    _register(client)
    client.post("/api/portal/logout")
    bad_pw = _login(client, password="wrongwrong")
    unknown = _login(client, phone="0898765432", password=PW)
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json()["detail"] == unknown.json()["detail"]


def test_a_customer_record_without_a_password_cannot_be_logged_into(client, db, clinic):
    """Every customer the AI creates from a chat has an empty password_hash. An empty
    stored hash must never verify, or all of them would be open accounts."""
    db.add(models.Customer(clinic_id=clinic.id, name="Chat lead", phone="0812345678",
                           channel="web", channel_user_id="w9"))
    db.commit()
    assert _login(client).status_code == 401
    assert _login(client, password="").status_code == 401


# --------------------------------------------------------------- account
def test_account_routes_require_a_session(client, clinic):
    for path in ("/api/portal/me", "/api/portal/bookings", "/api/portal/payments",
                 "/api/portal/treatments"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/portal/chat", json={}).status_code == 401


def test_a_staff_session_is_not_a_customer_session(auth_client):
    """auth_client is logged in as STAFF. Its cookie must not open the portal:
    the two use the same secret with different signing salts."""
    assert auth_client.get("/api/portal/me").status_code == 401


def test_bookings_and_payments_show_only_the_signed_in_customer(client, db, clinic):
    svc = db.query(models.Service).filter_by(clinic_id=clinic.id).first()
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    from datetime import datetime, timedelta
    other = models.Customer(clinic_id=clinic.id, name="Other Person", phone="0898765432",
                            channel="web", channel_user_id="w2")
    db.add(other)
    db.flush()
    db.add(models.Booking(clinic_id=clinic.id, customer_id=other.id, service_id=svc.id,
                          branch_id=branch.id, slot_at=datetime.utcnow() + timedelta(days=2),
                          status="confirmed", price=5000))
    db.add(models.Payment(clinic_id=clinic.id, customer_id=other.id, amount=1000, status="paid"))
    db.commit()

    _register(client)                         # a different person signs up
    assert client.get("/api/portal/bookings").json()["bookings"] == []
    assert client.get("/api/portal/payments").json()["payments"] == []


def test_bookings_returns_the_customers_own_rows(client, db, clinic):
    from datetime import datetime, timedelta
    _register(client)
    me = db.query(models.Customer).filter_by(phone="0812345678").one()
    svc = db.query(models.Service).filter_by(clinic_id=clinic.id).first()
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    db.add(models.Booking(clinic_id=clinic.id, customer_id=me.id, service_id=svc.id,
                          branch_id=branch.id, slot_at=datetime.utcnow() + timedelta(days=3),
                          status="confirmed", price=5000, deposit_required=1000))
    db.commit()

    rows = client.get("/api/portal/bookings").json()["bookings"]
    assert len(rows) == 1
    assert rows[0]["service_name"] == svc.name and rows[0]["upcoming"] is True


def test_profile_edit_cannot_change_the_phone(client, db, clinic):
    """The phone is the login identifier and the key other records are matched on,
    so it is not self-service — accepting it here would let someone type their way
    onto another customer's number."""
    _register(client)
    r = client.patch("/api/portal/me", json={"name": "ชื่อใหม่", "nickname": "นิก",
                                             "phone": "0899999999"})
    assert r.status_code == 200
    assert r.json()["name"] == "ชื่อใหม่" and r.json()["phone"] == "0812345678"


def test_chat_opens_this_customers_own_conversation(client, db, clinic):
    from app.security import read_chat_token
    _register(client)
    me = db.query(models.Customer).filter_by(phone="0812345678").one()
    first = client.post("/api/portal/chat", json={}).json()
    again = client.post("/api/portal/chat", json={}).json()
    assert first["conversation_id"] == again["conversation_id"]   # resumed, not duplicated
    conv = db.get(models.Conversation, read_chat_token(first["token"]))
    assert conv.customer_id == me.id


def test_new_chat_opens_a_fresh_conversation_for_the_same_customer(client, db, clinic):
    """The widget's "start a new chat" button. It must not resume, must stay on the
    signed-in customer's record, must leave the old thread in place, and must be
    what a later plain resume comes back to."""
    from app.security import read_chat_token
    _register(client)
    me = db.query(models.Customer).filter_by(phone="0812345678").one()
    first = client.post("/api/portal/chat", json={}).json()
    fresh = client.post("/api/portal/chat", json={"new": True}).json()
    assert fresh["conversation_id"] != first["conversation_id"]
    conv = db.get(models.Conversation, read_chat_token(fresh["token"]))
    assert conv.customer_id == me.id
    assert db.get(models.Conversation, first["conversation_id"]) is not None
    assert db.query(models.Customer).filter_by(phone="0812345678").count() == 1
    again = client.post("/api/portal/chat", json={}).json()
    assert again["conversation_id"] == fresh["conversation_id"]


def test_a_merged_customer_still_reaches_their_golden_record(client, db, clinic):
    """Staff can merge duplicates. The session points at the row that was merged
    away, so the portal must follow merged_into_id or the customer is locked out
    of the account that now holds their history."""
    _register(client)
    me = db.query(models.Customer).filter_by(phone="0812345678").one()
    golden = models.Customer(clinic_id=clinic.id, name="Golden", phone="0812345678",
                             channel="web", channel_user_id="w-golden",
                             password_hash=hash_password(PW))
    db.add(golden)
    db.flush()
    me.merged_into_id = golden.id
    db.commit()
    assert client.get("/api/portal/me").json()["id"] == golden.id
