"""Regression tests for per-branch treatments (Service <-> ServiceBranch).

A Service can now be restricted to any SUBSET of a clinic's branches (a proper
many-to-many via ServiceBranch), or left unrestricted ("every branch" — no
rows at all). Selecting every branch in the clinic is normalised back to
"unrestricted" (the UI's "Auto: all branches" state). Covers: catalog CRUD
reconciling ServiceBranch/ServicePrice rows as the scope changes, per-branch
(overlap-based) name uniqueness, the AI's list_treatments/book_appointment
tools respecting the scope, RAG source items carrying one chunk per branch,
and the booking route rejecting a booking for a service at the wrong branch.
"""
from datetime import timedelta

from app import models
from app.ai import rag
from app.ai.tools import execute_tool
from app.services import booking
from app.services.booking import create_booking


# Booking on the website is members-only (tools.booking_requires_signup), and these
# tests are about the booking itself, so their web customers hold a portal account.
MEMBER = "portal-member"


def _second_branch(db, clinic, name="Second Branch"):
    b = models.Branch(clinic_id=clinic.id, name=name)
    db.add(b)
    db.commit()
    return b


def _mk_service(db, clinic, name, base_price=1000.0, branch_ids=None):
    s = models.Service(clinic_id=clinic.id, name=name, category="facial",
                       base_price=base_price, active=True)
    db.add(s)
    db.flush()
    for bid in (branch_ids or []):
        db.add(models.ServiceBranch(clinic_id=clinic.id, service_id=s.id, branch_id=bid))
    db.commit()
    return s


def _mk_customer(db, clinic, branch_id=None):
    c = models.Customer(password_hash=MEMBER, clinic_id=clinic.id, name="Test Customer", channel="web",
                        branch_id=branch_id)
    db.add(c)
    db.commit()
    return c


def _mk_conversation(db, clinic, customer, branch=None):
    conv = models.Conversation(clinic_id=clinic.id, customer_id=customer.id,
                               channel="web", branch_id=branch.id if branch else None)
    db.add(conv)
    db.commit()
    return conv


def _branch_ids_of(db, sid):
    return {row.branch_id for row in
            db.query(models.ServiceBranch).filter_by(service_id=sid).all()}


# --------------------------------------------------------------------------
# catalog.py — create/update reconciles ServiceBranch + ServicePrice rows
# --------------------------------------------------------------------------
def test_create_service_restricted_to_one_branch_only_seeds_that_branch(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)

    r = auth_client.post("/api/services", json={
        "name": "Branch B Only Facial", "base_price": 2000.0, "branch_ids": [b2.id]})
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["branch_ids"] == [b2.id]
    sid = created["id"]

    db.expire_all()
    prices = db.query(models.ServicePrice).filter_by(service_id=sid).all()
    assert len(prices) == 1
    assert prices[0].branch_id == b2.id
    assert b1  # sanity: b1 exists but got no price row for this treatment


def test_create_service_selecting_every_branch_normalises_to_unrestricted(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)

    r = auth_client.post("/api/services", json={
        "name": "All Selected Facial", "base_price": 1000.0, "branch_ids": [b1.id, b2.id]})
    assert r.status_code == 200, r.text
    created = r.json()
    # Selecting EVERY branch collapses to "Auto" — the canonical unrestricted state.
    assert created["branch_ids"] == []
    db.expire_all()
    assert _branch_ids_of(db, created["id"]) == set()


def test_create_service_restricted_to_subset_of_three_branches(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic, "B2")
    b3 = _second_branch(db, clinic, "B3")

    r = auth_client.post("/api/services", json={
        "name": "Two Of Three Facial", "base_price": 1000.0, "branch_ids": [b1.id, b2.id]})
    assert r.status_code == 200, r.text
    created = r.json()
    assert set(created["branch_ids"]) == {b1.id, b2.id}
    db.expire_all()
    prices = {p.branch_id for p in
              db.query(models.ServicePrice).filter_by(service_id=created["id"]).all()}
    assert prices == {b1.id, b2.id}
    assert b3  # untouched — no price row for the excluded branch


def test_update_service_branch_ids_all_to_subset_cleans_other_branch_prices(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)

    r = auth_client.post("/api/services", json={"name": "Global Facial", "base_price": 1500.0})
    sid = r.json()["id"]
    db.expire_all()
    assert db.query(models.ServicePrice).filter_by(service_id=sid).count() == 2

    r = auth_client.patch(f"/api/services/{sid}", json={"branch_ids": [b1.id]})
    assert r.status_code == 200, r.text
    assert r.json()["branch_ids"] == [b1.id]

    db.expire_all()
    rows = db.query(models.ServicePrice).filter_by(service_id=sid).all()
    assert [row.branch_id for row in rows] == [b1.id]
    assert _branch_ids_of(db, sid) == {b1.id}
    assert b2  # the other branch's price row was dropped, not just ignored


def test_update_service_branch_ids_subset_back_to_all_reseeds_missing_branches(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)

    r = auth_client.post("/api/services", json={
        "name": "Scoped Then Global", "base_price": 900.0, "branch_ids": [b1.id]})
    sid = r.json()["id"]

    # Selecting every branch (equivalent to sending an empty list) goes back to "all".
    r = auth_client.patch(f"/api/services/{sid}", json={"branch_ids": [b1.id, b2.id]})
    assert r.status_code == 200, r.text
    assert r.json()["branch_ids"] == []

    db.expire_all()
    branch_ids = {row.branch_id for row in
                  db.query(models.ServicePrice).filter_by(service_id=sid).all()}
    assert branch_ids == {b1.id, b2.id}
    assert _branch_ids_of(db, sid) == set()


def test_service_name_unique_only_when_branch_scopes_overlap(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)

    r1 = auth_client.post("/api/services", json={
        "name": "Deluxe Facial", "base_price": 1000.0, "branch_ids": [b1.id]})
    assert r1.status_code == 200, r1.text

    # Same name at a DISJOINT branch is allowed — separate treatments per branch.
    r2 = auth_client.post("/api/services", json={
        "name": "Deluxe Facial", "base_price": 1200.0, "branch_ids": [b2.id]})
    assert r2.status_code == 200, r2.text

    # Same name overlapping branch b1 collides.
    r3 = auth_client.post("/api/services", json={
        "name": "Deluxe Facial", "base_price": 1100.0, "branch_ids": [b1.id]})
    assert r3.status_code == 409, r3.text

    # An unrestricted ("all branches") service overlaps with every scope.
    r4 = auth_client.post("/api/services", json={"name": "Deluxe Facial", "base_price": 1300.0})
    assert r4.status_code == 409, r4.text


# --------------------------------------------------------------------------
# AI tools — list_treatments / book_appointment respect the scope
# --------------------------------------------------------------------------
def test_list_treatments_tool_filters_by_branch(db, clinic):
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)
    _mk_service(db, clinic, "Global Treatment")
    _mk_service(db, clinic, "Branch One Treatment", branch_ids=[b1.id])
    _mk_service(db, clinic, "Branch Two Treatment", branch_ids=[b2.id])

    cust = _mk_customer(db, clinic, branch_id=b1.id)
    conv = _mk_conversation(db, clinic, cust, branch=b1)

    res = execute_tool(db, conv, cust, "list_treatments", {})
    names = {t["name"] for t in res["treatments"]}
    assert "Global Treatment" in names
    assert "Branch One Treatment" in names
    assert "Branch Two Treatment" not in names


def test_list_treatments_tool_includes_treatment_shared_by_subset(db, clinic):
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic, "B2")
    b3 = _second_branch(db, clinic, "B3")
    _mk_service(db, clinic, "Two Branch Treatment", branch_ids=[b1.id, b2.id])

    cust1 = _mk_customer(db, clinic, branch_id=b1.id)
    conv1 = _mk_conversation(db, clinic, cust1, branch=b1)
    assert "Two Branch Treatment" in {t["name"] for t in
                                      execute_tool(db, conv1, cust1, "list_treatments", {})["treatments"]}

    cust3 = _mk_customer(db, clinic, branch_id=b3.id)
    conv3 = _mk_conversation(db, clinic, cust3, branch=b3)
    assert "Two Branch Treatment" not in {t["name"] for t in
                                          execute_tool(db, conv3, cust3, "list_treatments", {})["treatments"]}


def test_book_appointment_tool_rejects_wrong_branch_service(db, clinic):
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)
    svc = _mk_service(db, clinic, "Branch Two Exclusive", branch_ids=[b2.id])

    cust = _mk_customer(db, clinic, branch_id=b1.id)
    conv = _mk_conversation(db, clinic, cust, branch=b1)

    slot = booking._now_local() + timedelta(days=2)
    res = execute_tool(db, conv, cust, "book_appointment", {
        "treatment": svc.name, "date": slot.strftime("%Y-%m-%d"), "time": slot.strftime("%H:%M")})
    assert "error" in res
    assert db.query(models.Booking).filter_by(service_id=svc.id).count() == 0


def test_find_service_prefers_customers_own_branch_when_names_collide(db, clinic):
    from app.ai.tools import _find_service

    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)
    svc_b1 = _mk_service(db, clinic, "Shared Name Facial", base_price=1000.0, branch_ids=[b1.id])
    _mk_service(db, clinic, "Shared Name Facial", base_price=2000.0, branch_ids=[b2.id])

    found = _find_service(db, "Shared Name Facial", clinic.id, branch_id=b1.id)
    assert found.id == svc_b1.id


# --------------------------------------------------------------------------
# RAG — source items carry one chunk per restricted branch
# --------------------------------------------------------------------------
def test_rag_source_items_service_branch_ids(db, clinic):
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)
    _mk_service(db, clinic, "Scoped RAG Facial", branch_ids=[b1.id, b2.id])
    _mk_service(db, clinic, "Global RAG Facial")

    items = [(name, bid) for (stype, _sid, name, _text, bid) in rag._source_items(db, clinic.id)
             if stype == "service"]
    scoped_branches = {bid for (name, bid) in items if name == "Scoped RAG Facial"}
    assert scoped_branches == {b1.id, b2.id}   # one chunk per restricted branch
    global_branches = {bid for (name, bid) in items if name == "Global RAG Facial"}
    assert global_branches == {None}


# --------------------------------------------------------------------------
# Booking route — rejects a branch-scoped service booked at the wrong branch
# --------------------------------------------------------------------------
def test_booking_route_rejects_service_at_wrong_branch(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b2 = _second_branch(db, clinic)
    svc = _mk_service(db, clinic, "Branch One Only", branch_ids=[b1.id])
    cust = _mk_customer(db, clinic)

    slot = (booking._now_local() + timedelta(days=2)).replace(microsecond=0)
    r = auth_client.post("/api/bookings", json={
        "customer_id": cust.id, "service_id": svc.id, "branch_id": b2.id,
        "slot_at": slot.isoformat(),
    })
    assert r.status_code == 400, r.text


def test_booking_route_allows_service_at_its_own_branch(auth_client, db):
    clinic = auth_client.test_clinic
    b1 = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _mk_service(db, clinic, "Branch One Only Ok", branch_ids=[b1.id])
    cust = _mk_customer(db, clinic)

    slot = (booking._now_local() + timedelta(days=2)).replace(
        hour=11, minute=0, second=0, microsecond=0)
    r = auth_client.post("/api/bookings", json={
        "customer_id": cust.id, "service_id": svc.id, "branch_id": b1.id,
        "slot_at": slot.isoformat(),
    })
    assert r.status_code == 200, r.text
