"""One broken job must not take the scheduler down.

When calendar_sync gained the ``icalendar`` dependency and the server was restarted
without reinstalling the .venv, a single ImportError at the top of start_scheduler
silently disabled EVERY background job — the 10-minute hold sweep, the retention
reminders, the takeover timeout — while the site kept serving 200s. Each job now
resolves its own import and registers on its own; a failure costs that job only, and
is reported loudly with the fix.

The scheduler is really started here (daemon thread) but no job can fire inside a
test: the first run of an interval job is one full interval away (>= 60 s), and the
fixture shuts it down immediately after.
"""
import sys

import pytest

from app.services import scheduler as S

ALL_JOBS = {"retention-automations", "hold-expiry-sweep", "hold-reminder-sweep",
            "calendar-sync", "takeover-timeout-sweep"}


@pytest.fixture
def fresh_scheduler(monkeypatch):
    monkeypatch.setattr(S, "_scheduler", None)
    monkeypatch.setattr(S, "_status", None)
    yield
    if S._scheduler is not None:
        S._scheduler.shutdown(wait=False)


def _job_ids():
    return {j.id for j in S._scheduler.get_jobs()}


def test_every_job_registers_when_its_dependencies_are_present(fresh_scheduler):
    status = S.start_scheduler()
    assert S._scheduler.running
    assert status["skipped"] == {}
    assert set(status["registered"]) == ALL_JOBS == _job_ids()


def test_a_missing_dependency_costs_that_one_job_not_the_scheduler(
        fresh_scheduler, monkeypatch, capsys):
    """The production failure, replayed: calendar_sync cannot be imported."""
    # None in sys.modules makes `import app.services.calendar_sync` raise ImportError,
    # exactly as a missing `icalendar` does from inside that module.
    monkeypatch.setitem(sys.modules, "app.services.calendar_sync", None)
    status = S.start_scheduler()
    assert S._scheduler.running, "the scheduler must start with the jobs it CAN run"
    assert "calendar-sync" not in _job_ids()
    assert ALL_JOBS - {"calendar-sync"} == _job_ids(), (
        "the hold sweep, reminders and takeover timeout are unaffected")
    assert set(status["skipped"]) == {"calendar-sync"}
    assert "ImportError" in status["skipped"]["calendar-sync"] or \
        "ModuleNotFoundError" in status["skipped"]["calendar-sync"]
    out = capsys.readouterr().out
    assert "JOB SKIPPED — calendar-sync" in out, "loud, per job, not one quiet line"
    assert "pip install -r requirements.txt" in out, "the fix travels with the report"


def test_start_scheduler_is_idempotent(fresh_scheduler):
    first = S.start_scheduler()
    sched = S._scheduler
    second = S.start_scheduler()
    assert S._scheduler is sched and second == first


def test_every_job_target_resolves_to_a_callable():
    """The table is strings, so a typo would only surface at startup as a skipped job —
    pin it here instead, where a rename fails the suite."""
    for job_id, target, opts, _desc in S._jobs():
        assert callable(S._resolve(target)), f"{job_id}: {target}"
        assert opts.get("minutes") or opts.get("seconds"), f"{job_id}: no interval"
