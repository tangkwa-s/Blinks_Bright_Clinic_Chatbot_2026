"""AI quality eval harness for Blinks Bright.

Unlike the pytest *regression* suite (deterministic, offline), the eval harness
runs the REAL AI (``app.ai.chat.respond``) against a set of representative customer
conversations and grades each reply with programmatic checks (+ an optional
LLM judge). It measures behaviour quality — grounding, no invented discounts, no
false payment confirmations, on-topic, books only real slots, escalates medical
questions — and catches prompt/model regressions.

Run:  cd <repo> && PYTHONPATH=. .venv/bin/python -m evals.run

THROWAWAY-DB GUARD (load-bearing, keep it HERE): ``app.database`` builds its
engine at import time from ``settings.db_path``, so DB_PATH must be pointed at a
temp file before ANY ``app.*`` import anywhere in this package. Doing it in the
package ``__init__`` is the only spot guaranteed to run first no matter which
evals module gets imported (run.py's own imports used to pull ``app.database``
via evals.cases before harness.py could set it — every eval then silently read
and WROTE the live clinic.db). ``setup_clinic`` double-checks the engine URL.
"""
import os
import tempfile

os.environ.setdefault(
    "DB_PATH", os.path.join(tempfile.mkdtemp(prefix="bb-eval-"), "eval.db"))
