"""A time the branch is SHUT must be answered with the opening hours, not with "full".

A customer asked for 08:00, then 08:30, then 09:00 at a branch that opens at 10:00 and
was told each time "ยังไม่ว่างค่ะ" — which says that hour is BOOKED. It was not: the
clinic had not opened. The hours only travelled with the tool result when a day had NO
openings at all, so on a day that opens at 10:00 the model was left to invent the reason.

The reason lives in the branch's schedule (booking.branch_days), so it is stated.
"""
import json
from datetime import timedelta

from app import models
from app.ai.tools import _parse_clock, execute_tool
from app.services import booking as bk

DAYS = {**{d: {"open": "10:00", "close": "20:00"} for d in
           ("mon", "tue", "wed", "thu", "fri")},
        "sat": {"open": "10:00", "close": "19:00"},
        "sun": {"open": "10:00", "close": "19:00"}}


def _branch(db, clinic, name="สาขาสีลม", days=None):
    b = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    b.name = name
    b.hours = json.dumps({"days": days or DAYS})
    b.open_hour, b.close_hour = 10, 20
    db.commit()
    return b


def _chat(db, clinic, branch, *lines):
    cust = models.Customer(clinic_id=clinic.id, name="Web Visitor", channel="web")
    db.add(cust)
    db.commit()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web",
                               branch_id=branch.id)
    db.add(conv)
    db.commit()
    for line in lines:
        db.add(models.Message(clinic_id=clinic.id, conversation_id=conv.id,
                              sender="customer", text=line))
    db.commit()
    return conv, cust


def _next_weekday():
    """The next Mon-Fri day. DAYS gives weekdays 10:00-20:00 but weekends 10:00-19:00,
    so plain "tomorrow" made these tests fail whenever the suite ran on a Friday or
    Saturday — the app was right (19:00), the test's fixed "20:00" was not."""
    day = bk._now_local() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _tomorrow():
    return _next_weekday().strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# reading the time off the transcript
# --------------------------------------------------------------------------
def test_the_clock_times_customers_actually_type():
    assert _parse_clock("พรุ่งนี้ 8:30") == 8 * 60 + 30
    assert _parse_clock("พรุ่งนี้8โมง") == 8 * 60
    assert _parse_clock("พรุ่งนี้ 9 โมง") == 9 * 60
    assert _parse_clock("บ่าย 2") == 14 * 60
    assert _parse_clock("2 ทุ่ม") == 20 * 60
    assert _parse_clock("9 am") == 9 * 60
    assert _parse_clock("7pm") == 19 * 60
    assert _parse_clock("สนใจ Hifu ค่ะ") is None, "no time named"
    assert _parse_clock("25:00") is None, "not a clock time"


# --------------------------------------------------------------------------
# the tool result
# --------------------------------------------------------------------------
def test_before_opening_is_answered_with_the_hours(db, clinic):
    br = _branch(db, clinic)
    conv, cust = _chat(db, clinic, br, "พรุ่งนี้ 8:30")

    res = execute_tool(db, conv, cust, "check_availability", {"date": _tomorrow()})
    assert res["requested_time_outside_hours"] == "08:30"
    assert res["branch_hours_that_day"] == "10:00-20:00"
    assert br.name in res["say_it_like"] and "10:00-20:00" in res["say_it_like"]
    assert "ยังไม่เปิด" in res["say_it_like"]
    assert "never say that time is 'not available'".lower() in res["outside_hours_note"].lower()
    assert res["available_slots"], "the day itself is open, so alternatives still come back"


def test_after_closing_says_closed_not_full(db, clinic):
    br = _branch(db, clinic)
    conv, cust = _chat(db, clinic, br, "พรุ่งนี้ 3 ทุ่ม")   # 21:00, closes 20:00

    res = execute_tool(db, conv, cust, "check_availability", {"date": _tomorrow()})
    assert res["requested_time_outside_hours"] == "21:00"
    assert "เลยเวลาปิด" in res["say_it_like"]


def test_a_branch_already_called_sakha_is_not_prefixed_twice(db, clinic):
    """"สาขา สาขาเปิดใหม่" reads as a typo in the customer's chat."""
    br = _branch(db, clinic, name="สาขาเปิดใหม่")
    conv, cust = _chat(db, clinic, br, "พรุ่งนี้ 8:00")

    res = execute_tool(db, conv, cust, "check_availability", {"date": _tomorrow()})
    assert res["say_it_like"].startswith("สาขาเปิดใหม่ เปิดให้บริการ")


def test_a_time_inside_the_hours_gets_no_such_note(db, clinic):
    br = _branch(db, clinic)
    conv, cust = _chat(db, clinic, br, "พรุ่งนี้ 14:00")

    res = execute_tool(db, conv, cust, "check_availability", {"date": _tomorrow()})
    assert "requested_time_outside_hours" not in res
    assert "outside_hours_note" not in res
    assert res["branch_hours_that_day"] == "10:00-20:00", "hours still travel, as context"


def test_the_model_passed_time_is_used_too(db, clinic):
    """The transcript is the fallback; an explicit argument is honoured first."""
    br = _branch(db, clinic)
    conv, cust = _chat(db, clinic, br, "เอาเช้าๆ ได้ไหมคะ")

    res = execute_tool(db, conv, cust, "check_availability",
                       {"date": _tomorrow(), "time": "09:00"})
    assert res["requested_time_outside_hours"] == "09:00"


def test_the_newest_time_wins(db, clinic):
    """They said 8:30, were told the branch opens at 10:00, then asked for 14:00."""
    br = _branch(db, clinic)
    conv, cust = _chat(db, clinic, br, "พรุ่งนี้ 8:30", "งั้นขอ 14:00 ค่ะ")

    res = execute_tool(db, conv, cust, "check_availability", {"date": _tomorrow()})
    assert "requested_time_outside_hours" not in res


def test_a_branch_added_later_reports_its_own_hours(db, clinic):
    """A branch opened after the catalog was written carries the default 10:00-20:00
    until someone edits it, and a day it is CLOSED must not read as "fully booked"."""
    _branch(db, clinic)
    fresh = models.Branch(clinic_id=clinic.id, name="สาขาเปิดใหม่",
                          hours=json.dumps({"days": {**DAYS, "sun": {"closed": True}}}),
                          open_hour=10, close_hour=20)
    db.add(fresh)
    db.commit()
    conv, cust = _chat(db, clinic, fresh, "พรุ่งนี้ 8:00")

    res = execute_tool(db, conv, cust, "check_availability", {"date": _tomorrow()})
    day = _next_weekday()
    if day.weekday() == 6:            # the fresh branch is shut on Sundays
        assert res["reason_code"] == bk.CLOSED
        assert res["branch_hours_that_day"] == "closed"
    else:
        assert res["requested_time_outside_hours"] == "08:00"
        assert fresh.name in res["say_it_like"]
        assert "10:00-20:00" in res["say_it_like"]
