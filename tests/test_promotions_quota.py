"""Regression tests for promotion effective-period enforcement on every AI
surface and the quota (limited-slots) feature.

Covers: resolved_price_detail's winning promo + Booking.promo_id stamping,
quota exhaustion flipping eligibility (paid payments consume; pending /
refunded do not), the list_promotions AI tool, RAG query-time filtering,
build_context, and the /api/promotions quota/used API surface.
"""
from datetime import timedelta

from app import models
from app.ai import context as ai_context
from app.ai import rag
from app.ai.tools import execute_tool
from app.services import booking
from app.services.booking import create_booking, resolved_price, resolved_price_detail
from app.services.promotions import exhausted_promo_ids, promo_used_counts


# --------------------------------------------------------------------------
# helpers (mirroring tests/test_pricing_booking.py)
# --------------------------------------------------------------------------
def _branch(db, clinic):
    return db.query(models.Branch).filter_by(clinic_id=clinic.id).first()


def _mk_service(db, clinic, base_price):
    s = models.Service(clinic_id=clinic.id, name="Test Laser",
                        category="laser", base_price=base_price, active=True)
    db.add(s)
    db.commit()
    return s


def _set_branch_price(db, clinic, service, branch, price):
    sp = models.ServicePrice(clinic_id=clinic.id, service_id=service.id,
                             branch_id=branch.id, price=price)
    db.add(sp)
    db.commit()
    return sp


def _mk_promo(db, clinic, service, promo_price, *, valid_from_days=-5,
              valid_to_days=+5, branch=None, active=True, quota=0, title="Promo"):
    now = booking._now_local()
    p = models.Promotion(
        clinic_id=clinic.id, title=title, service_id=service.id,
        branch_id=branch.id if branch else None,
        promo_price=promo_price, active=active, quota=quota,
        valid_from=now + timedelta(days=valid_from_days),
        valid_to=now + timedelta(days=valid_to_days),
    )
    db.add(p)
    db.commit()
    return p


def _mk_customer(db, clinic):
    c = models.Customer(clinic_id=clinic.id, name="Test Customer", channel="web")
    db.add(c)
    db.commit()
    return c


def _mk_booking(db, clinic, customer, service, branch, days_ahead=2):
    bk = create_booking(db, customer=customer, service=service,
                        branch_id=branch.id,
                        slot_at=booking._now_local() + timedelta(days=days_ahead))
    db.commit()
    return bk


def _pay(db, clinic, bk, status="paid"):
    p = models.Payment(clinic_id=clinic.id, customer_id=bk.customer_id,
                       booking_id=bk.id, type="deposit",
                       amount=bk.deposit_required, status=status)
    db.add(p)
    db.commit()
    return p


def _mk_conversation(db, clinic, customer, branch=None):
    conv = models.Conversation(clinic_id=clinic.id, customer_id=customer.id,
                               channel="web",
                               branch_id=branch.id if branch else None)
    db.add(conv)
    db.commit()
    return conv


def _promo_chunk(db, clinic, promo):
    c = models.KBChunk(clinic_id=clinic.id, source_type="promotion",
                       source_id=promo.id, title=promo.title,
                       text=f"Promotion: {promo.title}", embedding=[])
    db.add(c)
    db.commit()
    return c


# --------------------------------------------------------------------------
# resolved_price_detail — winning promo + Booking.promo_id stamping
# --------------------------------------------------------------------------
def test_resolved_price_detail_returns_winning_promo(db, clinic):
    branch = _branch(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8000)

    price, promo = resolved_price_detail(db, clinic.id, svc, branch.id)
    assert (price, promo) == (8000.0, None)  # no promo yet

    p = _mk_promo(db, clinic, svc, promo_price=6000)
    price, promo = resolved_price_detail(db, clinic.id, svc, branch.id)
    assert price == 6000.0
    assert promo is not None and promo.id == p.id
    # the float wrapper keeps its old contract
    assert resolved_price(db, clinic.id, svc, branch.id) == 6000.0


def test_create_booking_stamps_promo_id(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)

    bk = _mk_booking(db, clinic, cust, svc, branch)
    assert bk.promo_id is None  # no promo → no attribution

    p = _mk_promo(db, clinic, svc, promo_price=6000)
    bk2 = _mk_booking(db, clinic, cust, svc, branch, days_ahead=3)
    assert bk2.promo_id == p.id
    assert bk2.price == 6000.0


# --------------------------------------------------------------------------
# quota — paid bookings consume; pending/refunded do not; 0 = unlimited
# --------------------------------------------------------------------------
def test_quota_exhaustion_disables_promo(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _set_branch_price(db, clinic, svc, branch, price=8000)
    p = _mk_promo(db, clinic, svc, promo_price=6000, quota=1)

    bk = _mk_booking(db, clinic, cust, svc, branch)
    assert bk.promo_id == p.id and bk.price == 6000.0

    # Unpaid booking does NOT consume the quota yet.
    assert promo_used_counts(db, clinic.id) == {}
    assert exhausted_promo_ids(db, clinic.id) == set()
    assert resolved_price(db, clinic.id, svc, branch.id) == 6000.0

    # Once paid, the single slot is redeemed → promo stops applying.
    _pay(db, clinic, bk, status="paid")
    assert promo_used_counts(db, clinic.id) == {p.id: 1}
    assert exhausted_promo_ids(db, clinic.id) == {p.id}
    assert resolved_price(db, clinic.id, svc, branch.id) == 8000.0

    bk2 = _mk_booking(db, clinic, cust, svc, branch, days_ahead=4)
    assert bk2.promo_id is None
    assert bk2.price == 8000.0


def test_quota_pending_payment_does_not_consume(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    _mk_promo(db, clinic, svc, promo_price=6000, quota=1)

    bk = _mk_booking(db, clinic, cust, svc, branch)
    _pay(db, clinic, bk, status="pending")
    assert exhausted_promo_ids(db, clinic.id) == set()
    assert resolved_price(db, clinic.id, svc, branch.id) == 6000.0


def test_quota_refund_frees_the_slot(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    p = _mk_promo(db, clinic, svc, promo_price=6000, quota=1)

    bk = _mk_booking(db, clinic, cust, svc, branch)
    pay = _pay(db, clinic, bk, status="paid")
    assert exhausted_promo_ids(db, clinic.id) == {p.id}

    pay.status = "refunded"
    db.commit()
    assert exhausted_promo_ids(db, clinic.id) == set()
    assert resolved_price(db, clinic.id, svc, branch.id) == 6000.0


def test_quota_zero_is_unlimited(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    p = _mk_promo(db, clinic, svc, promo_price=6000, quota=0)

    for d in (2, 3, 4):
        bk = _mk_booking(db, clinic, cust, svc, branch, days_ahead=d)
        _pay(db, clinic, bk, status="paid")
    assert promo_used_counts(db, clinic.id) == {p.id: 3}
    assert exhausted_promo_ids(db, clinic.id) == set()
    assert resolved_price(db, clinic.id, svc, branch.id) == 6000.0


def test_quota_falls_back_to_next_cheapest_eligible_promo(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)
    cheap = _mk_promo(db, clinic, svc, promo_price=5000, quota=1, title="Flash")
    steady = _mk_promo(db, clinic, svc, promo_price=7000, quota=0, title="Steady")

    bk = _mk_booking(db, clinic, cust, svc, branch)
    assert bk.promo_id == cheap.id and bk.price == 5000.0
    _pay(db, clinic, bk, status="paid")

    price, promo = resolved_price_detail(db, clinic.id, svc, branch.id)
    assert price == 7000.0
    assert promo is not None and promo.id == steady.id


# --------------------------------------------------------------------------
# AI tool surface — list_promotions hides expired + exhausted promos
# --------------------------------------------------------------------------
def test_list_promotions_tool_hides_expired_and_exhausted(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)

    _mk_promo(db, clinic, svc, promo_price=6000, title="Live Promo")
    _mk_promo(db, clinic, svc, promo_price=5000, title="Expired Promo",
              valid_from_days=-10, valid_to_days=-1, active=True)
    _mk_promo(db, clinic, svc, promo_price=5500, title="Future Promo",
              valid_from_days=+3, valid_to_days=+10, active=True)
    full = _mk_promo(db, clinic, svc, promo_price=4000, title="Full Promo", quota=1)
    bk = _mk_booking(db, clinic, cust, svc, branch)
    assert bk.promo_id == full.id  # cheapest live promo won this booking
    _pay(db, clinic, bk, status="paid")

    conv = _mk_conversation(db, clinic, cust, branch)
    res = execute_tool(db, conv, cust, "list_promotions", {})
    titles = {p["title"] for p in res["promotions"]}
    assert "Live Promo" in titles
    assert "Expired Promo" not in titles
    assert "Future Promo" not in titles
    assert "Full Promo" not in titles


# --------------------------------------------------------------------------
# RAG — query-time drop of expired / exhausted promo chunks
# --------------------------------------------------------------------------
def test_rag_drop_inactive_drops_expired_and_exhausted_promos(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)

    live = _mk_promo(db, clinic, svc, promo_price=6000, title="Live Promo")
    expired = _mk_promo(db, clinic, svc, promo_price=5000, title="Expired Promo",
                        valid_from_days=-10, valid_to_days=-1)
    future = _mk_promo(db, clinic, svc, promo_price=5500, title="Future Promo",
                       valid_from_days=+3, valid_to_days=+10)
    full = _mk_promo(db, clinic, svc, promo_price=4000, title="Full Promo", quota=1)
    bk = _mk_booking(db, clinic, cust, svc, branch)
    _pay(db, clinic, bk, status="paid")

    chunks = [_promo_chunk(db, clinic, p) for p in (live, expired, future, full)]
    kept = rag._drop_inactive(db, clinic.id, chunks)
    kept_ids = {c.source_id for c in kept}
    assert kept_ids == {live.id}


def test_rag_source_items_skip_out_of_period_promos(db, clinic):
    svc = _mk_service(db, clinic, base_price=10000)
    _mk_promo(db, clinic, svc, promo_price=6000, title="Live Promo")
    _mk_promo(db, clinic, svc, promo_price=5000, title="Expired Promo",
              valid_from_days=-10, valid_to_days=-1)

    titles = {t for (stype, _sid, t, _text, _bid) in rag._source_items(db, clinic.id)
              if stype == "promotion"}
    assert "Live Promo" in titles
    assert "Expired Promo" not in titles


# --------------------------------------------------------------------------
# Hybrid context — expired / exhausted promos never reach the prompt
# --------------------------------------------------------------------------
def test_build_context_omits_expired_and_exhausted_promos(db, clinic):
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)

    _mk_promo(db, clinic, svc, promo_price=6000, title="Live Context Promo")
    _mk_promo(db, clinic, svc, promo_price=5000, title="Expired Context Promo",
              valid_from_days=-10, valid_to_days=-1)
    full = _mk_promo(db, clinic, svc, promo_price=4000,
                     title="Full Context Promo", quota=1)
    bk = _mk_booking(db, clinic, cust, svc, branch)
    _pay(db, clinic, bk, status="paid")

    text, _sources = ai_context.build_context(db, clinic.id, branch.id, "โปรโมชัน")
    assert "Live Context Promo" in text
    assert "Expired Context Promo" not in text
    assert "Full Context Promo" not in text


# --------------------------------------------------------------------------
# API — quota round-trips and used counts are exposed
# --------------------------------------------------------------------------
def test_promotions_api_quota_and_used(db, auth_client):
    clinic = auth_client.test_clinic
    branch = _branch(db, clinic)
    cust = _mk_customer(db, clinic)
    svc = _mk_service(db, clinic, base_price=10000)

    r = auth_client.post("/api/promotions", json={
        "title": "API Promo", "service_id": svc.id,
        "promo_price": 6000, "quota": 2})
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["quota"] == 2 and created["used"] == 0
    pid = created["id"]

    # a paid booking on the promo shows up as `used`
    bk = _mk_booking(db, clinic, cust, svc, branch)
    assert bk.promo_id == pid
    _pay(db, clinic, bk, status="paid")

    rows = auth_client.get("/api/promotions").json()
    row = next(p for p in rows if p["id"] == pid)
    assert row["quota"] == 2 and row["used"] == 1

    # PATCH updates quota (with sanitised coercion) and returns used
    r = auth_client.patch(f"/api/promotions/{pid}", json={"quota": "5"})
    assert r.status_code == 200, r.text
    assert r.json()["quota"] == 5 and r.json()["used"] == 1

    r = auth_client.patch(f"/api/promotions/{pid}", json={"quota": -3})
    assert r.json()["quota"] == 0  # negative input clamps to unlimited
