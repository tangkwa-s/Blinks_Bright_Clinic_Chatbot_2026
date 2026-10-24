"""The AI must be told each branch's REAL opening hours, in every block it reads.

Reported: asked about North Aurora the assistant answered "จันทร์ถึงศุกร์ 10:00-20:00 และ
เสาร์อาทิตย์ 10:00-19:00" while the branch card showed Mon-Tue 08:00-22:00, Wed closed,
Thu 08:00-22:00, Fri 18:00-24:00, Sat-Sun 10:00-19:00. That sentence was not a
hallucination — the branch's KB chunk carried those exact hours hardcoded, and read the
clinic's own hours never. The structured catalog block had them right, so the answer was
correct or wrong depending on which block the model happened to use.
"""
import json

from app import models
from app.ai.context import build_context
from app.ai.rag import _source_items, fmt_hours

# The reported branch, exactly as Settings shows it.
NORTH = {
    "mon": {"open": "08:00", "close": "22:00"},
    "tue": {"open": "08:00", "close": "22:00"},
    "wed": {"open": "08:00", "close": "22:00", "closed": True},
    "thu": {"open": "08:00", "close": "22:00"},
    "fri": {"open": "18:00", "close": "24:00"},
    "sat": {"open": "10:00", "close": "19:00"},
    "sun": {"open": "10:00", "close": "19:00"},
}


def _branch(db, clinic, name, hours=None):
    b = models.Branch(clinic_id=clinic.id, name=name, address="Chiang Mai",
                      phone="02 222 2222", open_hour=10, close_hour=20,
                      hours=json.dumps({"days": hours}) if hours else None)
    db.add(b)
    db.commit()
    return b


def test_the_reported_hours_are_formatted_faithfully(db, clinic):
    b = _branch(db, clinic, "North Aurora", NORTH)
    assert fmt_hours(b) == ("Mon-Tue 08:00-22:00, Wed closed, Thu 08:00-22:00, "
                            "Fri 18:00-24:00, Sat-Sun 10:00-19:00")


def test_the_kb_chunk_carries_the_real_hours(db, clinic):
    """The bug lived here: the chunk had a fixed sentence and ignored the branch."""
    b = _branch(db, clinic, "North Aurora", NORTH)
    chunk = next(txt for kind, sid, _title, txt, _bid in _source_items(db, clinic.id)
                 if kind == "branch" and sid == b.id)

    assert "Fri 18:00-24:00" in chunk and "Wed closed" in chunk
    # the invented line that used to be there, in either of its wordings
    assert "weekdays 10:00-20:00" not in chunk
    assert "Open daily" not in chunk


def test_the_catalog_block_and_the_kb_chunk_agree(db, clinic):
    """Two blocks reach the model every turn. If they disagree it quotes whichever it
    reads first, which is exactly what made the answer non-deterministic."""
    b = _branch(db, clinic, "North Aurora", NORTH)
    hours = fmt_hours(b)
    chunk = next(txt for kind, sid, _t, txt, _b in _source_items(db, clinic.id)
                 if kind == "branch" and sid == b.id)
    context, _sources = build_context(db, clinic.id, None, "เวลาทำการ")

    assert hours in chunk
    assert hours in context


def test_a_branch_with_no_per_day_hours_falls_back(db, clinic):
    b = _branch(db, clinic, "Simple Branch")
    assert fmt_hours(b) == "10:00-20:00 daily"


def test_each_branch_keeps_its_own_hours(db, clinic):
    """Three branches, three different schedules — no cross-contamination."""
    north = _branch(db, clinic, "North Aurora", NORTH)
    south = _branch(db, clinic, "South Aurora", {
        **{d: {"open": "09:00", "close": "21:00"} for d in
           ("mon", "tue", "wed", "thu", "fri")},
        "sat": {"open": "10:00", "close": "18:00"},
        "sun": {"open": "10:00", "close": "18:00", "closed": True},
    })

    assert fmt_hours(north) != fmt_hours(south)
    assert fmt_hours(south) == "Mon-Fri 09:00-21:00, Sat 10:00-18:00, Sun closed"
    context, _ = build_context(db, clinic.id, None, "เวลาทำการ")
    assert fmt_hours(north) in context and fmt_hours(south) in context


# --------------------------------------------------------------------------
# the legacy weekday/weekend shape every seeded clinic still carries
# --------------------------------------------------------------------------
LEGACY = {"weekday": "10:00-20:00", "weekend": "10:00-19:00"}


def _legacy_branch(db, clinic, name="Sukhumvit Flagship"):
    b = models.Branch(clinic_id=clinic.id, name=name, address="Bangkok", phone="02",
                      open_hour=10, close_hour=20, hours=json.dumps(LEGACY))
    db.add(b)
    db.commit()
    return b


def test_legacy_weekend_hours_are_not_flattened(db, clinic):
    """Four of the five seeded clinics store this shape. Only the Settings card read
    it, so the AI was told "10:00-20:00 daily" for a branch that shuts at 19:00 on
    Saturday and Sunday."""
    b = _legacy_branch(db, clinic)
    assert fmt_hours(b) == "Mon-Fri 10:00-20:00, Sat-Sun 10:00-19:00"
    assert "daily" not in fmt_hours(b)


def test_legacy_hours_close_the_weekend_slots_too(db, clinic):
    """Worse than a wrong sentence: availability offered 19:00 and 19:30 on a Saturday
    the branch is shut, so a customer could be booked into a closed clinic."""
    from datetime import timedelta

    from app.services import booking as bk

    b = _legacy_branch(db, clinic)
    sat = bk._now_local() + timedelta(days=1)
    while sat.weekday() != 5:
        sat += timedelta(days=1)
    fri = sat - timedelta(days=1)

    assert bk._day_window(b, sat) == (10 * 60, 19 * 60), "Saturday closes at 19:00"
    assert bk._day_window(b, fri) == (10 * 60, 20 * 60), "Friday still closes at 20:00"
    assert bk.available_slots(db, b.id, sat)[-1].strftime("%H:%M") == "18:30"


def test_one_parser_serves_hours_and_availability(db, clinic):
    """fmt_hours and _day_window must not be able to disagree — that split is what
    produced a correct branch card beside a wrong AI answer."""
    from app.services.booking import branch_days

    for hours in (LEGACY, {"days": NORTH}):
        b = models.Branch(clinic_id=clinic.id, name=f"B{hash(str(hours)) % 999}",
                          open_hour=10, close_hour=20, hours=json.dumps(hours))
        db.add(b)
        db.commit()
        assert branch_days(b) is not None
        assert set(branch_days(b)) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def test_a_branch_with_no_hours_at_all_still_falls_back(db, clinic):
    from app.services.booking import branch_days

    b = models.Branch(clinic_id=clinic.id, name="Bare", open_hour=9, close_hour=18)
    db.add(b)
    db.commit()
    assert branch_days(b) is None
    assert fmt_hours(b) == "09:00-18:00 daily"


# --------------------------------------------------------------------------
# a clinic created from scratch must not be able to reproduce any of this
# --------------------------------------------------------------------------
def test_a_new_clinic_starts_on_the_per_day_shape(db, make_clinic):
    """New clinics used to be seeded with the legacy weekday/weekend pair, so every
    one of them started life carrying the shape that only the Settings card read."""
    from app.services.booking import branch_days

    c = make_clinic("Brand New Clinic", slug="brand-new")
    b = db.query(models.Branch).filter_by(clinic_id=c.id).first()

    assert json.loads(b.hours).get("days"), "stored in the per-day shape"
    assert branch_days(b) is not None
    assert fmt_hours(b) == "Mon-Fri 10:00-20:00, Sat-Sun 10:00-19:00"


def test_the_seeded_kb_does_not_hardcode_any_hours(db, make_clinic):
    """A second copy of the hours in a KB article goes stale the moment a clinic edits
    its schedule, and the AI then has two answers to choose between."""
    import re

    c = make_clinic("KB Check Clinic", slug="kb-check")
    for a in db.query(models.KBArticle).filter_by(clinic_id=c.id).all():
        assert not re.search(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", a.content or ""), \
            f"article {a.title!r} states opening times the branch record owns"


def test_editing_a_new_clinics_hours_reaches_the_ai(db, make_clinic):
    """The end-to-end promise: change the schedule, and both blocks the model reads
    change with it."""
    c = make_clinic("Edited Hours Clinic", slug="edited-hours")
    b = db.query(models.Branch).filter_by(clinic_id=c.id).first()
    b.hours = json.dumps({"days": NORTH})
    db.commit()

    hours = fmt_hours(b)
    assert "Wed closed" in hours and "Fri 18:00-24:00" in hours
    chunk = next(txt for kind, sid, _t, txt, _b in _source_items(db, c.id)
                 if kind == "branch" and sid == b.id)
    context, _ = build_context(db, c.id, None, "เวลาทำการ")
    assert hours in chunk and hours in context


# --------------------------------------------------------------------------
# the startup repair for data already in the wild
# --------------------------------------------------------------------------
def test_backfill_migrates_legacy_hours_without_changing_them(db, clinic):
    """The schedule must mean exactly the same afterwards — this is a shape change,
    not a policy change."""
    from app.seed import backfill_branch_hours

    b = _legacy_branch(db, clinic)
    before = fmt_hours(b)

    result = backfill_branch_hours(db)
    db.refresh(b)

    assert result["branches"] >= 1
    assert json.loads(b.hours).get("days"), "now stored per-day"
    assert fmt_hours(b) == before == "Mon-Fri 10:00-20:00, Sat-Sun 10:00-19:00"


def test_backfill_rewrites_the_stale_hours_article(db, clinic):
    from app.seed import _STALE_HOURS_FAQ, backfill_branch_hours

    a = models.KBArticle(clinic_id=clinic.id, type="faq", active=True,
                         title="What are your opening hours?", content=_STALE_HOURS_FAQ)
    db.add(a)
    db.commit()

    assert backfill_branch_hours(db)["articles"] == 1
    db.refresh(a)
    assert "10:00-20:00" not in a.content
    assert "differ by branch" in a.content


def test_backfill_leaves_an_article_the_clinic_wrote_alone(db, clinic):
    """Their own content, even if it also states times — rewriting it silently would
    be worse than the duplication."""
    from app.seed import backfill_branch_hours

    mine = "สาขาเราเปิด 09:00-18:00 ทุกวันค่ะ ยกเว้นวันหยุดนักขัตฤกษ์"
    a = models.KBArticle(clinic_id=clinic.id, type="faq", active=True,
                         title="เวลาทำการ", content=mine)
    db.add(a)
    db.commit()

    backfill_branch_hours(db)
    db.refresh(a)
    assert a.content == mine


def test_backfill_is_idempotent(db, clinic):
    """It runs on every startup, so a second pass must be a no-op."""
    from app.seed import _STALE_HOURS_FAQ, backfill_branch_hours

    _legacy_branch(db, clinic)
    db.add(models.KBArticle(clinic_id=clinic.id, type="faq", active=True,
                            title="What are your opening hours?",
                            content=_STALE_HOURS_FAQ))
    db.commit()

    first = backfill_branch_hours(db)
    second = backfill_branch_hours(db)

    assert first["branches"] >= 1 and first["articles"] == 1
    assert second == {"branches": 0, "articles": 0}
