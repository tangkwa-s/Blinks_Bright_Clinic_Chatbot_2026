"""check_availability must say WHY a date has no openings.

Regression for a real LINE conversation: at 00:02 on Saturday 1 Aug 2026 a customer
asked for 10:30 the same morning. The branch is shut on Saturdays, so the tool
returned an empty slot list with no explanation — and the AI filled the gap by
telling the customer 10:30 "had already passed", ten and a half hours before it had.
The reason now travels with the tool result (and the tool result carries `now`), so
the model has no gap to invent into.
"""
import json
from datetime import datetime

import pytest

from app import models
from app.ai import tools as T
from app.services import booking as bk

# Saturday 1 August 2026, two minutes past midnight — the moment from the report.
MIDNIGHT_SAT = datetime(2026, 8, 1, 0, 2)
OPEN_ALL_WEEK = {d: {"open": "09:00", "close": "21:00"}
                 for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}
# The schedule the reported branch actually has: short Saturday, Sunday off.
SHORT_SAT = {**{d: {"open": "09:00", "close": "21:00"}
                for d in ["mon", "tue", "wed", "thu", "fri"]},
             "sat": {"open": "10:00", "close": "18:00"},
             "sun": {"open": "10:00", "close": "18:00", "closed": True}}


@pytest.fixture
def frozen(monkeypatch):
    """Pin the clinic clock so 'today' is always Sat 1 Aug 2026 00:02."""
    monkeypatch.setattr(bk, "_now_local", lambda: MIDNIGHT_SAT)
    monkeypatch.setattr(T, "_now_local", lambda: MIDNIGHT_SAT)
    return MIDNIGHT_SAT


@pytest.fixture
def convo(db, clinic):
    """A LINE conversation already locked to the clinic's only branch."""
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    cust = models.Customer(clinic_id=clinic.id, name="คุณเทส", phone="0812345678",
                           channel="line")
    db.add(cust)
    db.flush()
    c = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="line",
                            branch_id=branch.id)
    db.add(c)
    db.commit()
    return c, cust, branch


def _hours(branch, db, days):
    branch.hours = json.dumps({"days": days})
    db.commit()


def test_slot_later_today_is_offered_just_after_midnight(db, convo, frozen):
    """The bug's core case: 10:30 today is still 10.5 hours away, so it is bookable."""
    conv, cust, branch = convo
    _hours(branch, db, OPEN_ALL_WEEK)

    res = T.execute_tool(db, conv, cust, "check_availability", {"date": "2026-08-01"})

    assert "2026-08-01 10:30" in res["available_slots"]
    assert "requested_date_unavailable" not in res
    assert res["now"].startswith("Saturday 01 August 2026, 00:02")


def test_short_saturday_still_offers_1030(db, convo, frozen):
    """The reported branch's real schedule: Sat 10:00-18:00, Sun closed.

    At 00:02 on the Saturday, 10:30 that morning must be offered — and the day's
    own slots must come FIRST in the alternatives, ahead of Monday's.
    """
    conv, cust, branch = convo
    _hours(branch, db, SHORT_SAT)

    res = T.execute_tool(db, conv, cust, "check_availability", {"date": "2026-08-01"})
    assert "2026-08-01 10:30" in res["available_slots"]
    assert res["available_slots"][0] == "2026-08-01 10:00"     # opens at 10 on a Sat
    assert res["available_slots"][-1] == "2026-08-01 17:30"    # closes at 18

    # Sunday is the closed day, not Saturday
    sun = T.execute_tool(db, conv, cust, "check_availability", {"date": "2026-08-02"})
    assert sun["reason_code"] == bk.CLOSED
    assert "Sunday" in sun["reason"]
    assert sun["branch_hours_that_day"] == "closed"


def test_closed_day_reports_closed_not_a_passed_time(db, convo, frozen):
    """Branch shut on Saturdays → the reason must be the closure, never the clock."""
    conv, cust, branch = convo
    days = dict(OPEN_ALL_WEEK)
    days["sat"] = {"open": "09:00", "close": "21:00", "closed": True}
    _hours(branch, db, days)

    res = T.execute_tool(db, conv, cust, "check_availability", {"date": "2026-08-01"})

    assert res["available_slots"] == []
    assert res["reason_code"] == bk.CLOSED
    assert "CLOSED all day" in res["reason"]
    assert "Saturday" in res["reason"]
    # The wrong reason the model used to invent must not be implied anywhere.
    assert "passed" not in res["reason"]
    assert res["now"].startswith("Saturday 01 August 2026")
    # The customer-facing wording is service language, not a door slammed shut.
    assert res["say_it_like"] == "สาขานี้ปิดให้บริการในวันเสาร์ค่ะ"
    # and it still offers real alternatives, on days the branch actually opens
    assert res["other_days"] and all(not s.startswith("2026-08-01")
                                     for s in res["other_days"])


def test_fully_booked_day_is_not_reported_as_past(db, convo, frozen):
    """Every slot taken → 'fully_booked', not 'the time has passed'."""
    conv, cust, branch = convo
    _hours(branch, db, {**OPEN_ALL_WEEK, "sat": {"open": "10:00", "close": "11:00"}})
    svc = db.query(models.Service).filter_by(clinic_id=branch.clinic_id).first()
    other = models.Customer(clinic_id=branch.clinic_id, name="Someone else", channel="web")
    db.add(other)
    db.flush()
    for hh, mm in [(10, 0), (10, 30)]:                     # the whole 10:00-11:00 window
        db.add(models.Booking(clinic_id=branch.clinic_id, customer_id=other.id,
                              branch_id=branch.id, service_id=svc.id,
                              slot_at=datetime(2026, 8, 1, hh, mm), status="confirmed"))
    db.commit()

    res = T.execute_tool(db, conv, cust, "check_availability", {"date": "2026-08-01"})

    assert res["reason_code"] == bk.FULLY_BOOKED
    assert "already booked" in res["reason"]
    assert "passed" not in res["reason"]
    assert res["say_it_like"] == "วันเสาร์ที่ 01/08 คิวเต็มแล้วค่ะ"


def test_day_already_over_reports_past(db, convo, frozen, monkeypatch):
    """Late in the evening, 'the time has passed' IS the right reason — say it then."""
    conv, cust, branch = convo
    _hours(branch, db, OPEN_ALL_WEEK)
    late = datetime(2026, 8, 1, 22, 30)                    # after the 21:00 close
    monkeypatch.setattr(bk, "_now_local", lambda: late)
    monkeypatch.setattr(T, "_now_local", lambda: late)

    res = T.execute_tool(db, conv, cust, "check_availability", {"date": "2026-08-01"})

    assert res["reason_code"] == bk.PAST
    assert "22:30" in res["reason"]


def test_past_date_says_so(db, convo, frozen):
    """A date that is genuinely behind us gets the past-date wording, not 'closed'."""
    conv, cust, branch = convo
    _hours(branch, db, OPEN_ALL_WEEK)

    res = T.execute_tool(db, cust and conv, cust, "check_availability",
                         {"date": "2026-07-30"})

    assert res["available_slots"] == []
    assert "in the past" in res["reason"]


# --------------------------------------------------------------------------
# book_appointment must carry the same reason, not just check_availability
# --------------------------------------------------------------------------
def test_book_appointment_on_a_closed_day_gives_the_real_reason(db, convo, frozen):
    """A booking attempt for a shut day gets the same reason vocabulary
    check_availability uses, on the FIRST call — the regression that sent a
    customer's typo-corrected retry into a vague "ระบบขัดข้อง" escalation instead of
    the real answer, because the old failure was a bare "not available"."""
    conv, cust, branch = convo
    days = dict(OPEN_ALL_WEEK)
    days["sat"] = {"open": "09:00", "close": "21:00", "closed": True}
    _hours(branch, db, days)
    svc = db.query(models.Service).filter_by(clinic_id=branch.clinic_id).first()

    res = T.execute_tool(db, conv, cust, "book_appointment",
                         {"treatment": svc.name, "date": "2026-08-01", "time": "10:30"})

    assert res.get("booked") is not True
    assert "error" not in res
    assert res["reason_code"] == bk.CLOSED
    assert "Saturday" in res["reason"]
    assert res["say_it_like"] == "สาขานี้ปิดให้บริการในวันเสาร์ค่ะ"
    assert res["other_days"], "concrete alternatives, not just a refusal"
    assert db.query(models.Booking).count() == 0


def test_book_appointment_on_a_taken_slot_offers_same_day_alternatives(db, convo, frozen):
    """The day itself is open — only the exact minute asked for is gone — so the
    result must offer other times that same day, not the whole-day reason."""
    conv, cust, branch = convo
    _hours(branch, db, OPEN_ALL_WEEK)
    svc = db.query(models.Service).filter_by(clinic_id=branch.clinic_id).first()
    other = models.Customer(clinic_id=branch.clinic_id, name="คนอื่น", channel="web")
    db.add(other)
    db.flush()
    taken = datetime(2026, 8, 1, 10, 30)
    db.add(models.Booking(clinic_id=branch.clinic_id, customer_id=other.id, branch_id=branch.id,
                          service_id=svc.id, slot_at=taken, status="confirmed"))
    db.commit()

    res = T.execute_tool(db, conv, cust, "book_appointment",
                         {"treatment": svc.name, "date": "2026-08-01", "time": "10:30"})

    assert res.get("booked") is not True
    assert "error" not in res
    assert "reason_code" not in res
    assert res["other_times_same_day"], "the day has other openings"
    assert "10:30" not in res["other_times_same_day"]
    assert db.query(models.Booking).filter_by(service_id=svc.id).count() == 1


def test_day_availability_reasons(db, convo, frozen):
    """The service-layer contract the tool builds on."""
    conv, cust, branch = convo
    _hours(branch, db, OPEN_ALL_WEEK)

    slots, reason, window = bk.day_availability(db, branch.id, datetime(2026, 8, 1))
    assert reason == "" and window == (9 * 60, 21 * 60)
    assert slots[0] == datetime(2026, 8, 1, 9, 0)
    # available_slots keeps its old signature/behaviour for every existing caller
    assert bk.available_slots(db, branch.id, datetime(2026, 8, 1)) == slots
