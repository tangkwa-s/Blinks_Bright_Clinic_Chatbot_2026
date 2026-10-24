"""GET /api/bookings honours an inclusive date_from / date_to window.

The Bookings view defaults to the current Monday-Sunday week, so this filter carries
every page load — and the boundary that matters is the LAST day: slot_at holds a time,
so a naive `slot_at <= date_to` silently drops everything booked after midnight on it.
"""
from datetime import timedelta

from app import models
from app.services import booking as bk


def _mk(db, clinic, day_offset, hour=14):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    svc = db.query(models.Service).filter_by(clinic_id=clinic.id).first()
    cust = models.Customer(clinic_id=clinic.id, name=f"C{day_offset}-{hour}",
                           channel="web")
    db.add(cust)
    db.flush()
    slot = (bk._now_local() + timedelta(days=day_offset)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    b = models.Booking(clinic_id=clinic.id, customer_id=cust.id, branch_id=branch.id,
                       service_id=svc.id, slot_at=slot, status="confirmed",
                       price=1000, deposit_required=200)
    db.add(b)
    db.commit()
    return b, slot


def _ymd(dt):
    return dt.strftime("%Y-%m-%d")


def _ids(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items() if v)
    r = client.get("/api/bookings" + ("?" + q if q else ""))
    assert r.status_code == 200, r.text
    return {b["id"] for b in r.json()}


def test_range_keeps_only_bookings_inside_it(db, auth_client):
    clinic = auth_client.test_clinic
    before, d_before = _mk(db, clinic, 1)
    inside, d_inside = _mk(db, clinic, 4)
    after, d_after = _mk(db, clinic, 9)

    got = _ids(auth_client, date_from=_ymd(d_inside), date_to=_ymd(d_inside))
    assert got == {inside.id}
    assert before.id not in got and after.id not in got


def test_the_last_day_is_included_whole(db, auth_client):
    """The bug this guards: slot_at carries a time, so the window must end at the
    START of the following day, not at midnight on date_to."""
    clinic = auth_client.test_clinic
    early, d = _mk(db, clinic, 3, hour=9)
    late, _ = _mk(db, clinic, 3, hour=23)

    got = _ids(auth_client, date_from=_ymd(d), date_to=_ymd(d))
    assert got == {early.id, late.id}


def test_the_first_day_is_included_from_midnight(db, auth_client):
    clinic = auth_client.test_clinic
    b, d = _mk(db, clinic, 2, hour=0)

    assert b.id in _ids(auth_client, date_from=_ymd(d), date_to=_ymd(d))


def test_each_side_works_on_its_own(db, auth_client):
    clinic = auth_client.test_clinic
    early, d_early = _mk(db, clinic, 1)
    late, d_late = _mk(db, clinic, 8)

    assert _ids(auth_client, date_from=_ymd(d_late)) == {late.id}
    assert _ids(auth_client, date_to=_ymd(d_early)) == {early.id}


def test_no_range_returns_everything(db, auth_client):
    clinic = auth_client.test_clinic
    a, _ = _mk(db, clinic, 1)
    b, _ = _mk(db, clinic, 40)

    assert {a.id, b.id} <= _ids(auth_client)


def test_a_garbage_date_is_ignored_rather_than_erroring(db, auth_client):
    """The value comes off a URL, so it must never 500 the whole page."""
    clinic = auth_client.test_clinic
    b, _ = _mk(db, clinic, 1)

    assert b.id in _ids(auth_client, date_from="not-a-date", date_to="")


def test_range_composes_with_the_status_filter(db, auth_client):
    clinic = auth_client.test_clinic
    confirmed, d = _mk(db, clinic, 3)
    other, _ = _mk(db, clinic, 3, hour=16)
    other.status = "cancelled"
    db.commit()

    got = _ids(auth_client, date_from=_ymd(d), date_to=_ymd(d), status="confirmed")
    assert got == {confirmed.id}


def test_a_backwards_range_returns_nothing(db, auth_client):
    """The UI refuses this, but the API must not invent rows if one slips through."""
    clinic = auth_client.test_clinic
    _b, d = _mk(db, clinic, 5)
    later = _ymd(d + timedelta(days=2))

    assert _ids(auth_client, date_from=later, date_to=_ymd(d)) == set()
