"""Per-doctor external calendar (ICS) sync — cross-checking booking availability
against a doctor's OWN calendar (personal appointments, leave — anything not in our
booking system).

Three things this locks in:
  1. day_availability/claim_slot treat a synced ExternalBusyBlock exactly like a
     Booking, but ONLY once a doctor is pinned (doctor_id given) — same scope boundary
     as the existing doctor-conflict check.
  2. calendar_sync.sync_staff_calendar never lets a broken feed widen availability: a
     failed fetch/parse leaves previously-synced blocks untouched, and one doctor's
     broken feed cannot affect a clinic-mate's sync.
  3. The safety-critical property from the design discussion: claim_slot's lock never
     waits on a network call. It rejects a claim against a pre-synced busy block with
     zero calls to the ICS fetcher.
"""
from datetime import datetime, timedelta

import pytest

from app import models
from app.routers.catalog import _validate_ics_url
from app.services import booking as bk
from app.services import calendar_sync as CS

# Wednesday 5 Aug 2026, well inside the seeded starter branch's normal hours.
FROZEN_NOW = datetime(2026, 8, 5, 8, 0)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(bk, "_now_local", lambda: FROZEN_NOW)
    monkeypatch.setattr(CS, "_now_local", lambda: FROZEN_NOW)
    return FROZEN_NOW


@pytest.fixture
def doctor(db, clinic):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    m = models.StaffMember(clinic_id=clinic.id, branch_id=branch.id, name="Dr. Test",
                           role="doctor")
    db.add(m)
    db.commit()
    return m


def _ics(dtstart: str, dtend: str, rrule: str = "", status: str = "") -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//",
             "BEGIN:VEVENT", "UID:evt1@example.com",
             f"DTSTART:{dtstart}", f"DTEND:{dtend}"]
    if rrule:
        lines.append(f"RRULE:{rrule}")
    if status:
        lines.append(f"STATUS:{status}")
    lines += ["SUMMARY:Busy", "END:VEVENT", "END:VCALENDAR"]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 1. day_availability / claim_slot scope
# --------------------------------------------------------------------------
def test_external_busy_block_excludes_slot_when_doctor_matches(db, clinic, doctor, frozen):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    day = frozen + timedelta(days=2)
    slot = bk.available_slots(db, branch.id, day, doctor_id=doctor.id)[0]

    db.add(models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=doctor.id,
                                    starts_at=slot, ends_at=slot + timedelta(minutes=30)))
    db.commit()

    remaining = bk.available_slots(db, branch.id, day, doctor_id=doctor.id)
    assert slot not in remaining


def test_external_busy_block_ignored_without_doctor_id(db, clinic, doctor, frozen):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    day = frozen + timedelta(days=2)
    slot = bk.available_slots(db, branch.id, day, doctor_id=doctor.id)[0]

    db.add(models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=doctor.id,
                                    starts_at=slot, ends_at=slot + timedelta(minutes=30)))
    db.commit()

    # No doctor pinned -> the branch-level check doesn't know to look at this doctor's
    # calendar at all, same as today's doctor-conflict clause.
    remaining = bk.available_slots(db, branch.id, day, doctor_id=None)
    assert slot in remaining


def test_claim_slot_rejects_external_busy_without_network_call(db, clinic, doctor, frozen, monkeypatch):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    day = frozen + timedelta(days=2)
    slot = bk.available_slots(db, branch.id, day, doctor_id=doctor.id)[0]

    db.add(models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=doctor.id,
                                    starts_at=slot, ends_at=slot + timedelta(minutes=30)))
    db.commit()

    def _boom(*a, **kw):
        raise AssertionError("claim_slot must never fetch a calendar feed")
    monkeypatch.setattr(CS.httpx, "get", _boom)

    def _write():
        raise AssertionError("write() must not run — the slot is not free")

    result, reason = bk.claim_slot(db, clinic_id=clinic.id, branch_id=branch.id,
                                   slot_at=slot, doctor_id=doctor.id, write=_write)
    assert result is None
    assert reason  # SLOT_TAKEN or a day_availability reason, but rejected either way


# --------------------------------------------------------------------------
# 2. ICS parsing
# --------------------------------------------------------------------------
def test_ics_parsing_expands_recurring_event():
    ics = _ics("20260106T130000Z", "20260106T140000Z", rrule="FREQ=WEEKLY;COUNT=3")
    window_start = datetime(2026, 1, 1)
    window_end = datetime(2026, 1, 31)
    blocks = CS._parse_busy_blocks(ics, window_start, window_end)

    assert len(blocks) == 3
    starts = sorted(b[0] for b in blocks)
    # UTC 13:00 -> Bangkok local 20:00, one week apart each.
    assert starts == [datetime(2026, 1, 6, 20, 0), datetime(2026, 1, 13, 20, 0),
                      datetime(2026, 1, 20, 20, 0)]
    for start, end, uid in blocks:
        assert end - start == timedelta(hours=1)
        assert uid == "evt1@example.com"


def test_ics_parsing_drops_cancelled_events():
    ics = _ics("20260106T090000Z", "20260106T093000Z", status="CANCELLED")
    blocks = CS._parse_busy_blocks(ics, datetime(2026, 1, 1), datetime(2026, 1, 31))
    assert blocks == []


def test_ics_parsing_all_day_event_blocks_whole_local_day():
    ics = ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//test//\n"
          "BEGIN:VEVENT\nUID:leave@example.com\n"
          "DTSTART;VALUE=DATE:20260110\nDTEND;VALUE=DATE:20260111\n"
          "SUMMARY:Leave\nEND:VEVENT\nEND:VCALENDAR")
    blocks = CS._parse_busy_blocks(ics, datetime(2026, 1, 1), datetime(2026, 1, 31))
    assert blocks == [(datetime(2026, 1, 10), datetime(2026, 1, 11), "leave@example.com")]


# --------------------------------------------------------------------------
# 3. sync_staff_calendar — fail-safe + per-staff isolation
# --------------------------------------------------------------------------
def test_failed_sync_keeps_last_known_good_blocks(db, clinic, doctor, frozen, monkeypatch):
    doctor.ics_url = "https://example.com/doctor.ics"
    old_start = frozen + timedelta(days=5)
    db.add(models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=doctor.id,
                                    starts_at=old_start, ends_at=old_start + timedelta(hours=1)))
    db.commit()

    def _boom(url, timeout=CS.FETCH_TIMEOUT):
        raise ConnectionError("feed host unreachable")
    monkeypatch.setattr(CS, "_fetch_ics", _boom)

    ok = CS.sync_staff_calendar(db, doctor, now=frozen)

    assert ok is False
    assert doctor.ics_last_error
    assert doctor.ics_last_synced_at is None
    remaining = (db.query(models.ExternalBusyBlock)
                .filter_by(staff_id=doctor.id).all())
    assert len(remaining) == 1
    assert remaining[0].starts_at == old_start


def test_sync_all_staff_calendars_isolates_one_broken_feed(db, clinic, frozen, monkeypatch):
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    good = models.StaffMember(clinic_id=clinic.id, branch_id=branch.id, name="Dr. Good",
                              role="doctor", ics_url="https://good.example.com/cal.ics")
    bad = models.StaffMember(clinic_id=clinic.id, branch_id=branch.id, name="Dr. Bad",
                             role="doctor", ics_url="https://bad.example.com/cal.ics")
    db.add_all([good, bad])
    db.commit()

    good_ics = _ics("20260806T090000Z", "20260806T100000Z")

    def _fake_fetch(url, timeout=CS.FETCH_TIMEOUT):
        if "bad" in url:
            raise ConnectionError("unreachable")
        return good_ics
    monkeypatch.setattr(CS, "_fetch_ics", _fake_fetch)

    result = CS.sync_all_staff_calendars(now=frozen)

    assert result == {"synced": 1, "failed": 1}
    db.refresh(good)
    db.refresh(bad)
    assert good.ics_last_error == ""
    assert good.ics_last_synced_at is not None
    assert bad.ics_last_error
    assert (db.query(models.ExternalBusyBlock).filter_by(staff_id=good.id).count()) == 1
    assert (db.query(models.ExternalBusyBlock).filter_by(staff_id=bad.id).count()) == 0


def test_sync_staff_calendar_noop_without_url(db, clinic, doctor, frozen):
    assert doctor.ics_url == ""
    assert CS.sync_staff_calendar(db, doctor, now=frozen) is True
    assert doctor.ics_last_synced_at is None


# --------------------------------------------------------------------------
# 4. _validate_ics_url
# --------------------------------------------------------------------------
def test_validate_ics_url_empty_clears():
    assert _validate_ics_url("") == ""
    assert _validate_ics_url(None) == ""
    assert _validate_ics_url("   ") == ""


def test_validate_ics_url_normalises_webcal():
    assert _validate_ics_url("webcal://example.com/cal.ics") == "https://example.com/cal.ics"


def test_validate_ics_url_accepts_https():
    assert _validate_ics_url("https://calendar.google.com/x.ics") == "https://calendar.google.com/x.ics"


def test_validate_ics_url_rejects_bad_scheme():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _validate_ics_url("ftp://example.com/cal.ics")


# --------------------------------------------------------------------------
# 5. Clearing/deleting a staff member cleans up its synced blocks
# --------------------------------------------------------------------------
def test_clearing_ics_url_drops_synced_blocks(auth_client, db):
    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    r = auth_client.post("/api/team-members",
                         json={"name": "Dr. Clear", "role": "doctor",
                               "branch_id": branch.id, "ics_url": "https://x.example/c.ics"})
    mid = r.json()["id"]
    db.add(models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=mid,
                                    starts_at=datetime(2026, 9, 1, 10, 0),
                                    ends_at=datetime(2026, 9, 1, 11, 0)))
    db.commit()
    assert db.query(models.ExternalBusyBlock).filter_by(staff_id=mid).count() == 1

    r = auth_client.patch(f"/api/team-members/{mid}", json={"ics_url": ""})
    assert r.status_code == 200, r.text
    assert r.json()["ics_url"] == ""
    assert db.query(models.ExternalBusyBlock).filter_by(staff_id=mid).count() == 0


def test_deleting_staff_member_drops_synced_blocks(auth_client, db):
    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    r = auth_client.post("/api/team-members",
                         json={"name": "Dr. Gone", "role": "doctor", "branch_id": branch.id})
    mid = r.json()["id"]
    db.add(models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=mid,
                                    starts_at=datetime(2026, 9, 1, 10, 0),
                                    ends_at=datetime(2026, 9, 1, 11, 0)))
    db.commit()

    r = auth_client.delete(f"/api/team-members/{mid}")
    assert r.status_code == 200, r.text
    assert db.query(models.ExternalBusyBlock).filter_by(staff_id=mid).count() == 0


# --------------------------------------------------------------------------
# 6. GET /team-members/busy-blocks — what the Team → Booking schedule tab shows
# --------------------------------------------------------------------------
def test_busy_blocks_endpoint_returns_staff_scoped_day(auth_client, db):
    clinic = auth_client.test_clinic
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    r = auth_client.post("/api/team-members",
                         json={"name": "Dr. Visible", "role": "doctor", "branch_id": branch.id})
    mid = r.json()["id"]
    db.add_all([
        models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=mid,
                                 starts_at=datetime(2026, 9, 1, 10, 0),
                                 ends_at=datetime(2026, 9, 1, 12, 0)),
        # a different day — must not show up in the 2026-09-01 query
        models.ExternalBusyBlock(clinic_id=clinic.id, staff_id=mid,
                                 starts_at=datetime(2026, 9, 2, 9, 0),
                                 ends_at=datetime(2026, 9, 2, 10, 0)),
    ])
    db.commit()

    r = auth_client.get("/api/team-members/busy-blocks?date=2026-09-01")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["staff_id"] == mid
    assert rows[0]["staff_name"] == "Dr. Visible"
    assert rows[0]["starts_at"] == "2026-09-01T10:00:00"
    assert rows[0]["ends_at"] == "2026-09-01T12:00:00"
