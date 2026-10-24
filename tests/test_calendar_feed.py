"""Regression tests for the ICS calendar feed + the Resend emailer no-op path."""
from datetime import timedelta

from app import models
from app.security import make_calendar_token
from app.services.booking import _now_local, create_booking
from app.services.emailer import send_booking_email, send_booking_email_async


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _mk_booking(db, clinic, *, days_ahead=3, status="pending", email=""):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = models.Service(clinic_id=clinic.id, name="Test, Laser; Deluxe",
                         category="laser", base_price=5000, active=True)
    cust = models.Customer(clinic_id=clinic.id, name="Feed Customer",
                           email=email, channel="web")
    db.add_all([svc, cust])
    db.commit()
    slot = (_now_local() + timedelta(days=days_ahead)).replace(
        hour=11, minute=0, second=0, microsecond=0)
    b = create_booking(db, customer=cust, service=svc, branch_id=branch.id,
                       slot_at=slot, created_by="admin")
    b.status = status
    db.commit()
    return b


def _fetch(client, clinic_id, branch_id=None):
    token = make_calendar_token(clinic_id, branch_id)
    return client.get(f"/api/calendar/{token}.ics")


# --------------------------------------------------------------------------
# feed contents
# --------------------------------------------------------------------------
def test_feed_returns_valid_vcalendar(db, clinic, client):
    b = _mk_booking(db, clinic)
    r = _fetch(client, clinic.id)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in body
    assert f"UID:booking-{b.id}@{clinic.slug}.blinksbright" in body
    assert "DTSTART:" in body and "DTEND:" in body and "DTSTAMP:" in body
    # RFC 5545 requires CRLF line endings
    assert "\r\n" in body
    assert body.endswith("\r\n")
    # TEXT escaping: the service name's comma/semicolon must be escaped
    assert "Test\\, Laser\\; Deluxe" in body


def test_feed_converts_bangkok_wallclock_to_utc(db, clinic, client):
    b = _mk_booking(db, clinic)  # 11:00 Bangkok wall-clock
    r = _fetch(client, clinic.id)
    # 11:00 +07:00 -> 04:00 UTC (Thailand has no DST)
    expected = b.slot_at.strftime("%Y%m%d") + "T040000Z"
    assert f"DTSTART:{expected}" in r.text


def test_feed_excludes_cancelled_and_other_clinics(db, make_clinic, client):
    c1 = make_clinic("Clinic One", slug="feed-one")
    c2 = make_clinic("Clinic Two", slug="feed-two")
    b1 = _mk_booking(db, c1)
    b_cancelled = _mk_booking(db, c1, status="cancelled")
    b2 = _mk_booking(db, c2)
    body = _fetch(client, c1.id).text
    assert f"UID:booking-{b1.id}@" in body
    assert f"UID:booking-{b_cancelled.id}@" not in body
    assert f"UID:booking-{b2.id}@" not in body
    # and clinic 2's token never sees clinic 1's booking
    body2 = _fetch(client, c2.id).text
    assert f"UID:booking-{b2.id}@" in body2
    assert f"UID:booking-{b1.id}@" not in body2


def test_feed_branch_filter(db, clinic, client):
    b1 = _mk_booking(db, clinic)
    other = models.Branch(clinic_id=clinic.id, name="Second Branch")
    db.add(other)
    db.commit()
    body = _fetch(client, clinic.id, branch_id=other.id).text
    assert f"UID:booking-{b1.id}@" not in body
    assert "BEGIN:VCALENDAR" in body


def test_feed_invalid_token_404(client):
    assert client.get("/api/calendar/not-a-real-token.ics").status_code == 404


def test_feed_archived_clinic_404(db, clinic, client):
    _mk_booking(db, clinic)
    clinic.status = "archived"
    db.commit()
    assert _fetch(client, clinic.id).status_code == 404


def test_feed_url_endpoint(auth_client):
    r = auth_client.get("/api/calendar/feed-url")
    assert r.status_code == 200
    url = r.json()["url"]
    assert "/api/calendar/" in url and url.endswith(".ics")
    # the minted URL must itself serve the feed
    path = url.split("://", 1)[1].split("/", 1)[1]
    r2 = auth_client.get(f"/{path}")
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("text/calendar")


# --------------------------------------------------------------------------
# emailer — offline no-op paths
# --------------------------------------------------------------------------
def test_emailer_noop_without_api_key(db, clinic):
    b = _mk_booking(db, clinic, email="someone@example.com")
    # resend_api_key is blanked by conftest → both paths return without network
    send_booking_email(b.id)
    send_booking_email_async(b.id)


def test_emailer_noop_without_customer_email(db, clinic, monkeypatch):
    from app.config import settings
    b = _mk_booking(db, clinic, email="")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not reach the network")

    import httpx
    monkeypatch.setattr(httpx, "post", _boom)
    send_booking_email(b.id)  # no email on file → returns before httpx.post
    assert called["n"] == 0
