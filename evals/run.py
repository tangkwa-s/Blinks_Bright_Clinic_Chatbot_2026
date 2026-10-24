"""Eval runner.  Usage:
    cd <repo> && PYTHONPATH=. .venv/bin/python -m evals.run            # all cases
    PYTHONPATH=. .venv/bin/python -m evals.run --case=discount_refusal # one case
    PYTHONPATH=. .venv/bin/python -m evals.run --no-kb                 # skip KB indexing
    PYTHONPATH=. .venv/bin/python -m evals.run --no-log                # don't write a log

Every run is saved under evals/results/:
  - <timestamp>.json   full per-case / per-check detail of that run
  - history.jsonl      one summary line per run, to track quality over time
"""
import json
import os
import sys
from datetime import datetime

from app.ai.client import is_configured
from app.config import settings
from evals.cases import CASES
from evals.harness import run_case, setup_clinic

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _save(report: dict) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = report["timestamp"].replace(":", "").replace("-", "").replace("T", "-")[:15]
    path = os.path.join(RESULTS_DIR, f"{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(RESULTS_DIR, "history.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": report["timestamp"], "model": report["model"],
            "cases": f"{report['cases_passed']}/{report['cases_total']}",
            "checks": f"{report['checks_passed']}/{report['checks_total']}",
            "failed_cases": [c["id"] for c in report["cases"] if not c["passed"]],
        }, ensure_ascii=False) + "\n")
    return path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--case=")), None)
    index_kb = "--no-kb" not in argv
    do_log = "--no-log" not in argv

    if not is_configured():
        print("OpenAI is not configured (.env OPENAI_API_KEY). The eval runs the real model — skipping.")
        return 0

    cases = [c for c in CASES if (not only or c.id == only)]
    if not cases:
        print(f"No case matches --case={only!r}. Available: {', '.join(c.id for c in CASES)}")
        return 1

    print(f"Model: {settings.chat_model}")
    print("Provisioning eval clinic + indexing knowledge base…")
    cid = setup_clinic(index_kb=index_kb)
    print(f"Running {len(cases)} eval case(s)\n" + "=" * 64)

    report = {"timestamp": datetime.now().isoformat(timespec="seconds"),
              "model": settings.chat_model, "cases": [],
              "cases_passed": 0, "cases_total": len(cases),
              "checks_passed": 0, "checks_total": 0}

    for case in cases:
        try:
            results = run_case(case, cid)
        except Exception as exc:  # pragma: no cover
            print(f"\n💥 ERROR  {case.id}: {exc}")
            report["cases"].append({"id": case.id, "description": case.description,
                                    "passed": False, "error": str(exc), "checks": []})
            continue
        ok = all(r.ok for r in results)
        report["cases_passed"] += int(ok)
        report["cases"].append({
            "id": case.id, "description": case.description, "passed": ok,
            "checks": [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results],
        })
        print(f"\n{'✅ PASS' if ok else '❌ FAIL'}  {case.id}")
        print(f"        {case.description}")
        for r in results:
            report["checks_total"] += 1
            report["checks_passed"] += int(r.ok)
            mark = "·" if r.ok else "✗"
            line = f"        {mark} {r.name}"
            if r.detail and not r.ok:
                line += f"  →  {r.detail}"
            elif r.detail and r.name == "judge":
                line += f"  ({r.detail})"
            print(line)

    print("\n" + "=" * 64)
    print(f"RESULT: {report['cases_passed']}/{report['cases_total']} cases passed · "
          f"{report['checks_passed']}/{report['checks_total']} checks passed")
    if do_log:
        path = _save(report)
        print(f"Saved: {os.path.relpath(path)}  (+ appended evals/results/history.jsonl)")
    return 0 if report["cases_passed"] == report["cases_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
