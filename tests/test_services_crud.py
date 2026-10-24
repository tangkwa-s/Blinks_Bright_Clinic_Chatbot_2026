"""HTTP-level regression tests for the service catalog endpoints
(`app/routers/catalog.py`).

Focus: the DELETE /api/services/{id} route (it used to be missing → 405) and its
archive-vs-hard-delete branching, plus POST/PATCH create/update round-trips.
All calls go through ``auth_client`` (owner logged in + entered into the clinic);
DB state is verified through the ``db`` fixture (same engine).
"""
from datetime import datetime, timedelta

from app import models


def _services(auth_client):
    r = auth_client.get("/api/services")
    assert r.status_code == 200, r.text
    return r.json()


def _make_booking(db, *, clinic_id, service_id, branch_id):
    """Create a customer + a booking referencing the service so the delete path
    takes the soft-archive branch."""
    cust = models.Customer(clinic_id=clinic_id, name="Booking Cust",
                           branch_id=branch_id)
    db.add(cust)
    db.flush()
    bk = models.Booking(clinic_id=clinic_id, customer_id=cust.id,
                        branch_id=branch_id, service_id=service_id,
                        slot_at=datetime.utcnow() + timedelta(days=1),
                        price=1000.0, deposit_required=200.0)
    db.add(bk)
    db.commit()
    return bk


def test_delete_route_exists_not_405(auth_client, db):
    """The bug: DELETE /api/services/{id} returned 405 Method Not Allowed.
    It must be a real route returning 200."""
    svc = _services(auth_client)[0]
    r = auth_client.delete(f"/api/services/{svc['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "archived" in body


def test_delete_with_booking_archives(auth_client, db):
    """A service referenced by a booking is soft-archived: row stays, active=False."""
    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    services = _services(auth_client)
    svc = services[0]
    assert svc["active"] is True

    _make_booking(db, clinic_id=clinic.id, service_id=svc["id"],
                  branch_id=branch.id)

    r = auth_client.delete(f"/api/services/{svc['id']}")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "archived": True}

    # Row still exists but is deactivated.
    db.expire_all()
    row = db.get(models.Service, svc["id"])
    assert row is not None
    assert row.active is False


def test_delete_without_booking_hard_deletes(auth_client, db):
    """A service with no bookings is hard-deleted along with its ServicePrice
    rows and linked promotions."""
    clinic = auth_client.test_clinic
    # Pick a service that has no booking attached (none created in this test).
    services = _services(auth_client)
    svc = services[0]
    sid = svc["id"]

    # Sanity: provisioning created per-branch ServicePrice rows for the service.
    price_count = (db.query(models.ServicePrice)
                   .filter_by(clinic_id=clinic.id, service_id=sid).count())
    assert price_count >= 1

    # Attach a promotion to the service so we can assert it is removed too.
    promo = models.Promotion(clinic_id=clinic.id, title="Linked promo",
                             service_id=sid, promo_price=500.0, active=True)
    db.add(promo)
    db.commit()
    promo_id = promo.id

    r = auth_client.delete(f"/api/services/{sid}")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "archived": False}

    db.expire_all()
    assert db.get(models.Service, sid) is None
    assert (db.query(models.ServicePrice)
            .filter_by(service_id=sid).count() == 0)
    assert db.get(models.Promotion, promo_id) is None


def test_create_service(auth_client, db):
    """POST /api/services creates a Service (200) with given fields, and seeds a
    ServicePrice per branch from base_price."""
    clinic = auth_client.test_clinic
    n_branches = db.query(models.Branch).filter_by(clinic_id=clinic.id).count()

    payload = {"name": "Hydra Glow Facial", "category": "Facial",
               "base_price": 3200.0, "duration_min": 60}
    r = auth_client.post("/api/services", json=payload)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["name"] == "Hydra Glow Facial"
    assert created["category"] == "Facial"
    assert created["base_price"] == 3200.0
    assert created["active"] is True

    # Confirm it is now listed via a fresh GET.
    listed = {s["id"]: s for s in _services(auth_client)}
    assert created["id"] in listed
    assert listed[created["id"]]["name"] == "Hydra Glow Facial"

    # A ServicePrice row per branch was created at base_price.
    db.expire_all()
    prices = (db.query(models.ServicePrice)
              .filter_by(clinic_id=clinic.id, service_id=created["id"]).all())
    assert len(prices) == n_branches
    assert all(p.price == 3200.0 for p in prices)


def test_create_service_refuses_a_branch_price_of_zero_or_less(auth_client, db):
    """A per-branch price is an OVERRIDE, so it has to be a real amount.

    It used to clamp a negative up to 0 and store it, which reads back as falsy in
    ``booking.resolved_price_detail`` — the ฿0 quietly fell through to the base price
    while the form kept showing 0, i.e. a number nobody would ever be charged. There
    is no safe value to clamp to, so it is refused; blank is how you say "base price".
    """
    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()

    for bad in (-500, 0):
        r = auth_client.post("/api/services", json={
            "name": f"Rejected Facial {bad}", "category": "Facial",
            "base_price": 1000.0, "duration_min": 30,
            "prices": {str(branch.id): bad}})
        assert r.status_code == 400, r.text
        assert not (db.query(models.Service)
                    .filter_by(clinic_id=clinic.id, name=f"Rejected Facial {bad}").first()), \
            "a rejected price must not leave half a treatment behind"


def test_patch_service_refuses_a_branch_price_of_zero_or_less(auth_client, db):
    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    sid = _services(auth_client)[0]["id"]
    before = (db.query(models.ServicePrice)
              .filter_by(clinic_id=clinic.id, service_id=sid, branch_id=branch.id).first())
    kept = float(before.price) if before else None

    for bad in (-100, 0):
        r = auth_client.patch(f"/api/services/{sid}", json={"prices": {str(branch.id): bad}})
        assert r.status_code == 400, r.text

    db.expire_all()
    row = (db.query(models.ServicePrice)
           .filter_by(clinic_id=clinic.id, service_id=sid, branch_id=branch.id).first())
    assert (float(row.price) if row else None) == kept, "the stored price is untouched"


def test_a_branch_may_price_above_the_base_price(auth_client, db):
    """A premium branch charging more than the catalog's starting price is normal, and
    the AI is built for it — ``tools._price_change_note`` composes the "฿X higher than
    the ฿Y I quoted earlier" sentence. Clamping it down to the base price silently
    undercharged that branch."""
    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = _services(auth_client)[0]
    sid, base_price = svc["id"], float(svc["base_price"])

    r = auth_client.patch(f"/api/services/{sid}",
                          json={"prices": {str(branch.id): base_price + 2000}})
    assert r.status_code == 200, r.text
    assert r.json()["prices"][str(branch.id)] == base_price + 2000

    db.expire_all()
    row = (db.query(models.ServicePrice)
           .filter_by(clinic_id=clinic.id, service_id=sid, branch_id=branch.id).first())
    assert row.price == base_price + 2000


def test_branch_price_still_clamps_at_the_sanity_ceiling(auth_client, db):
    """An absurd figure is a paste/typo rather than a meaning error, so it clamps to
    the same MAX_PRICE the base price gets."""
    from app.routers.catalog import MAX_PRICE

    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    sid = _services(auth_client)[0]["id"]

    r = auth_client.patch(f"/api/services/{sid}",
                          json={"prices": {str(branch.id): MAX_PRICE * 10}})
    assert r.status_code == 200, r.text
    db.expire_all()
    row = (db.query(models.ServicePrice)
           .filter_by(clinic_id=clinic.id, service_id=sid, branch_id=branch.id).first())
    assert row.price == float(MAX_PRICE)


def test_patch_service_updates_field(auth_client, db):
    """PATCH /api/services/{id} updates a field (base_price); verified via GET."""
    svc = _services(auth_client)[0]
    sid = svc["id"]
    new_price = float(svc["base_price"]) + 777.0

    r = auth_client.patch(f"/api/services/{sid}", json={"base_price": new_price})
    assert r.status_code == 200, r.text
    assert r.json()["base_price"] == new_price

    # Follow-up GET reflects the change.
    listed = {s["id"]: s for s in _services(auth_client)}
    assert listed[sid]["base_price"] == new_price

    db.expire_all()
    assert db.get(models.Service, sid).base_price == new_price


def test_hold_minutes_zero_stays_zero_the_inherit_sentinel(auth_client, db):
    """Unlike deposit (which clamps to base_price), 0 is a real, valid value here —
    it means 'use the clinic's setting' — so it must never be clamped away."""
    sid = _services(auth_client)[0]["id"]
    r = auth_client.patch(f"/api/services/{sid}", json={"hold_minutes": 0})
    assert r.status_code == 200, r.text
    assert r.json()["hold_minutes"] == 0


def test_hold_minutes_clamps_at_the_sanity_ceiling_not_rejected(auth_client, db):
    """A typo/paste is clamped, like every other numeric field on this form, not
    400'd — matching base_price/duration/interval/deposit's existing behavior."""
    from app.services.booking import MAX_HOLD_MINUTES

    sid = _services(auth_client)[0]["id"]
    r = auth_client.patch(f"/api/services/{sid}", json={"hold_minutes": MAX_HOLD_MINUTES * 10})
    assert r.status_code == 200, r.text
    assert r.json()["hold_minutes"] == MAX_HOLD_MINUTES
    db.expire_all()
    assert db.get(models.Service, sid).hold_minutes == MAX_HOLD_MINUTES


def test_hold_minutes_negative_clamps_to_zero(auth_client, db):
    sid = _services(auth_client)[0]["id"]
    r = auth_client.patch(f"/api/services/{sid}", json={"hold_minutes": -5})
    assert r.status_code == 200, r.text
    assert r.json()["hold_minutes"] == 0
