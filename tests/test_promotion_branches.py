"""A promotion can run at several branches, the way a treatment can be offered at several.

Before this it carried a single ``Promotion.branch_id``, so "this deal runs at Central
and North but not South" could not be expressed at all. The join table is read
everywhere through ``promotions.promo_branch_ids``, because the same question — where
does this promo apply? — is asked by the price quote, the AI's promo list, the KB index
and the catalog block, and those four disagreeing is how the opening-hours bug happened.
"""
from datetime import timedelta

from app import models
from app.services import booking as bk
from app.services.promotions import promo_branch_ids, promo_runs_at


def _branches(db, clinic, names=("Central", "North", "South")):
    out = [db.query(models.Branch).filter_by(clinic_id=clinic.id).first()]
    out[0].name = names[0]
    for n in names[1:]:
        b = models.Branch(clinic_id=clinic.id, name=n, open_hour=9, close_hour=21)
        db.add(b)
        out.append(b)
    db.commit()
    return out


def _service(db, clinic, price=10000.0):
    s = models.Service(clinic_id=clinic.id, name="Glow Facial", category="facial",
                       base_price=price, duration_min=45, active=True)
    db.add(s)
    db.commit()
    return s


def _promo(db, clinic, service, price, branches=()):
    now = bk._now_local()
    p = models.Promotion(clinic_id=clinic.id, title="Bundle", service_id=service.id,
                         promo_price=price, active=True,
                         valid_from=now - timedelta(days=1),
                         valid_to=now + timedelta(days=30))
    db.add(p)
    db.flush()
    for b in branches:
        db.add(models.PromotionBranch(clinic_id=clinic.id, promotion_id=p.id,
                                      branch_id=b.id))
    db.commit()
    return p


# --------------------------------------------------------------------------
# the shared reader
# --------------------------------------------------------------------------
def test_no_rows_means_every_branch(db, clinic):
    assert promo_runs_at(set(), 5) is True
    assert promo_runs_at(None, 5) is True


def test_a_restricted_promo_needs_a_matching_branch(db, clinic):
    assert promo_runs_at({1, 2}, 1) is True
    assert promo_runs_at({1, 2}, 3) is False


def test_a_restricted_promo_never_applies_to_an_unknown_branch(db, clinic):
    """Quoting a branch-specific deal before the customer has picked a branch is how
    a price gets promised that the branch they choose does not honour."""
    assert promo_runs_at({1, 2}, None) is False
    assert promo_runs_at({1, 2}, 0) is False


def test_the_legacy_single_column_still_reads(db, clinic):
    """Rows written before the join table existed must not read as clinic-wide."""
    central, north, _south = _branches(db, clinic)
    svc = _service(db, clinic)
    p = _promo(db, clinic, svc, 7000)
    p.branch_id = north.id          # as an un-migrated row looks
    db.commit()

    ids = promo_branch_ids(db, clinic.id)
    assert ids[p.id] == {north.id}
    assert promo_runs_at(ids.get(p.id), central.id) is False


# --------------------------------------------------------------------------
# the price a customer is actually quoted
# --------------------------------------------------------------------------
def test_price_applies_the_promo_only_at_its_branches(db, clinic):
    central, north, south = _branches(db, clinic)
    svc = _service(db, clinic, 10000)
    _promo(db, clinic, svc, 7000, branches=(central, north))

    assert bk.resolved_price(db, clinic.id, svc, central.id) == 7000
    assert bk.resolved_price(db, clinic.id, svc, north.id) == 7000
    assert bk.resolved_price(db, clinic.id, svc, south.id) == 10000, "South is excluded"


def test_an_unrestricted_promo_applies_everywhere(db, clinic):
    central, _north, south = _branches(db, clinic)
    svc = _service(db, clinic, 10000)
    _promo(db, clinic, svc, 7000)

    assert bk.resolved_price(db, clinic.id, svc, central.id) == 7000
    assert bk.resolved_price(db, clinic.id, svc, south.id) == 7000


# --------------------------------------------------------------------------
# the API
# --------------------------------------------------------------------------
def test_api_round_trips_several_branches(db, auth_client):
    clinic = auth_client.test_clinic
    central, north, _south = _branches(db, clinic)

    r = auth_client.post("/api/promotions", json={
        "title": "Two-branch deal", "branch_ids": [central.id, north.id]})
    assert r.status_code == 200, r.text
    assert r.json()["branch_ids"] == sorted([central.id, north.id])

    listed = auth_client.get("/api/promotions").json()
    assert listed[0]["branch_ids"] == sorted([central.id, north.id])


def test_api_collapses_every_branch_to_all(db, auth_client):
    """Ticking all of them means "all branches", which is stored as no rows — the same
    normalisation a treatment's branches get."""
    clinic = auth_client.test_clinic
    all_b = _branches(db, clinic)

    r = auth_client.post("/api/promotions", json={
        "title": "Everywhere", "branch_ids": [b.id for b in all_b]})
    assert r.json()["branch_ids"] == []
    assert db.query(models.PromotionBranch).filter_by(clinic_id=clinic.id).count() == 0


def test_api_can_narrow_and_widen_an_existing_promo(db, auth_client):
    clinic = auth_client.test_clinic
    central, north, _south = _branches(db, clinic)
    pid = auth_client.post("/api/promotions", json={"title": "P"}).json()["id"]

    r = auth_client.patch(f"/api/promotions/{pid}", json={"branch_ids": [central.id]})
    assert r.json()["branch_ids"] == [central.id]

    r = auth_client.patch(f"/api/promotions/{pid}",
                          json={"branch_ids": [central.id, north.id]})
    assert r.json()["branch_ids"] == sorted([central.id, north.id])

    r = auth_client.patch(f"/api/promotions/{pid}", json={"branch_ids": []})
    assert r.json()["branch_ids"] == [], "back to every branch"


def test_editing_another_field_leaves_the_branches_alone(db, auth_client):
    """A PATCH that never mentions branch_ids must not silently widen the promo."""
    clinic = auth_client.test_clinic
    central, _north, _south = _branches(db, clinic)
    pid = auth_client.post("/api/promotions",
                           json={"title": "P", "branch_ids": [central.id]}).json()["id"]

    r = auth_client.patch(f"/api/promotions/{pid}", json={"title": "Renamed"})
    assert r.json()["branch_ids"] == [central.id]


# --------------------------------------------------------------------------
# the startup migration
# --------------------------------------------------------------------------
def test_backfill_moves_the_old_column_onto_the_table(db, clinic):
    from app.seed import backfill_promotion_branches

    _central, north, _south = _branches(db, clinic)
    svc = _service(db, clinic)
    p = _promo(db, clinic, svc, 7000)
    p.branch_id = north.id
    db.commit()

    assert backfill_promotion_branches(db) == 1
    db.refresh(p)
    assert p.branch_id is None, "the column stops being a second source of truth"
    assert promo_branch_ids(db, clinic.id)[p.id] == {north.id}
    assert backfill_promotion_branches(db) == 0, "idempotent"
