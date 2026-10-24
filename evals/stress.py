"""Stress test — a long, realistic branch-shopping conversation, scored for the
failure that matters most in long chats: the assistant asking round and round.

Why this exists: the normal eval CASES are 1-3 turns, so they never reach the
regime where things break. Real chats run 15+ turns across several branches, and
that is exactly when the assistant starts re-asking the branch / time / treatment
the customer already gave. This replays such a chat and counts, objectively:

  redundant_asks : AI asked for a slot (branch / date / time / treatment) that the
                   customer had ALREADY given -> "ถามวนไปวนมา" (asking round and round)
  booked         : did it ever call book_appointment
  turns_to_book  : how many customer messages that took (fewer = less friction)

Run:
    PYTHONPATH=. .venv/bin/python -m evals.stress                      # current model
    PYTHONPATH=. .venv/bin/python -m evals.stress --model gpt-5.6-luna --runs 3
    PYTHONPATH=. .venv/bin/python -m evals.stress --compare            # A/B both models

Uses the throwaway eval DB (evals/__init__ pins DB_PATH) — never the live clinic.db.
"""
import argparse
import json
import os
import re
import statistics
import time
from datetime import datetime

from app import models
from app.ai.chat import respond
from app.ai.sales import analyze
from app.config import settings
from app.database import Base, SessionLocal, engine

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
_SLUG = "stress-clinic"

# Three branches with DIFFERENT prices — a realistic multi-branch setup, and the reason
# the assistant has to re-quote per branch (a big source of extra turns).
BRANCHES = [
    ("Central Aurora, Bangkok", "CTA", 8, 20),      # opens 08:00
    ("North Aurora, Chiang Mai", "NTA", 9, 20),
    ("South Aurora, Chumphon", "STA", 9, 19),
]
SERVICE = ("Acne Clear Program", "Facial", 3000.0, 50)
BRANCH_PRICES = {"Central Aurora, Bangkok": 3500.0,
                 "North Aurora, Chiang Mai": 3200.0,
                 "South Aurora, Chumphon": 3000.0}

def build_script(day: int | None = None, hhmm: str = "14:00"):
    """The scripted conversation, turn for turn. `known` = slots the CUSTOMER has
    supplied by the end of that turn; the reply must not ask for them again.

    The target date is a real FUTURE day and the time sits mid-afternoon inside
    every branch's hours, so the slot genuinely IS free — otherwise the assistant
    would be right to offer alternatives and the metric would measure nothing.
    """
    from datetime import timedelta
    target = datetime.now() + timedelta(days=10)
    d = day or target.day
    return [
        ("สนใจรักษาสิวค่ะ มีทรีตเมนต์อะไรแนะนำบ้าง", {}),
        ("Acne Clear Program ราคาเท่าไหร่คะ", {"treatment"}),
        ("สาขาชุมพร", {"treatment", "branch"}),
        ("สาขาเชียงใหม่ละคะ", {"treatment", "branch"}),
        # two branches asked about, no commitment -> asking which branch here is
        # FAIR, so 'branch' is intentionally dropped from the expected-known set.
        (f"วันที่ {d} {hhmm}", {"treatment", "date", "time"}),
        ("ชุมพร", {"treatment", "branch", "date", "time"}),
        (f"วันที่ {d} ว่างมั้ยคะ", {"treatment", "branch", "date"}),
        (f"มีสาขาไหนว่างวันที่ {d} บ้าง", {"treatment", "date"}),
        (f"เซ็นทรัล วันที่ {d} {hhmm}", {"treatment", "branch", "date", "time"}),
        ("ชื่อมะลิ เบอร์ 0812345678", {"treatment", "branch", "date", "time", "contact"}),
        (f"{hhmm} ค่ะ", {"treatment", "branch", "date", "time", "contact"}),
        ("ค่ะ", {"treatment", "branch", "date", "time", "contact"}),
        ("Acne Clear Program ค่ะ", {"treatment", "branch", "date", "time", "contact"}),
        ("ว่างอยู่นี่คะ", {"treatment", "branch", "date", "time", "contact"}),
        (f"{hhmm}", {"treatment", "branch", "date", "time", "contact"}),
        ("เต็มจำนวนเลยค่ะ", {"treatment", "branch", "date", "time", "contact"}),
    ]


SCRIPT = build_script()

# The assistant is NOT re-asking redundantly when it just told the customer the
# requested slot is unavailable / closed — offering alternatives is correct then.
DECLINE_PATTERNS = [r"ไม่ว่าง", r"เต็ม", r"ผ่านไปแล้ว", r"ยังไม่เปิด", r"ปิดทำการ",
                    r"เลยเวลา", r"หมดแล้ว", r"not available", r"fully booked"]

# "The reply is asking the customer for X" — Thai first, English fallback.
ASK_PATTERNS = {
    "branch": [r"สาขาไหน", r"สาขาที่ต้องการ", r"บอกสาขา", r"เลือกสาขา", r"สาขาใด",
               r"ต้องการสาขา", r"which branch", r"prefer.*branch"],
    "time": [r"ช่วงเวลาที่", r"บอกเวลา", r"เวลาที่ต้องการ", r"เวลาที่สะดวก", r"กี่โมง",
             r"เลือกเวลา", r"ระบุเวลา", r"ต้องการเวลา", r"what time", r"which time"],
    "date": [r"วันไหน", r"วันที่ต้องการ", r"บอกวัน", r"เลือกวัน", r"ระบุวัน",
             r"which (day|date)", r"what date"],
    "treatment": [r"ทรีตเมนต์อะไร", r"ทำอะไร", r"สนใจตัวไหน", r"รายการไหน", r"เลือกทรีตเมนต์",
                  r"ต้องการทรีตเมนต์", r"which treatment", r"what treatment"],
    # new checklist flow collects name+phone once; asking AGAIN after given = loop
    "contact": [r"ขอชื่อ", r"ชื่อและเบอร์", r"เบอร์โทร(?:ศัพท์)?(?:ด้วย|หน่อย|สำหรับ)",
                r"ขอเบอร์", r"your name", r"phone number"],
}
# "…ทั้งวัน มีช่วงเช้า บ่าย และเย็นให้เลือก" — a menu of times = asking for the time.
ASK_PATTERNS["time"].append(r"ช่วงเช้า.*บ่าย")


def _asks_for(reply: str, slot: str) -> bool:
    if any(re.search(p, reply, re.I) for p in DECLINE_PATTERNS):
        return False       # it explained the slot is taken — alternatives are fine
    return any(re.search(p, reply, re.I) for p in ASK_PATTERNS[slot])


def setup(index_kb: bool = False) -> int:
    """Provision the 3-branch stress clinic once (idempotent). Returns its id."""
    if "bb-eval-" not in str(engine.url):
        raise RuntimeError(f"refusing to run against {engine.url} — not a throwaway DB")
    from app.ai import rag
    from app.ai.client import is_configured
    from app.seed import provision_clinic

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        clinic = db.query(models.Clinic).filter_by(slug=_SLUG).first()
        if clinic:
            return clinic.id
        clinic = provision_clinic(db, "Aurora Stress Clinic", slug=_SLUG)
        db.commit()
        # exactly the three branches, replacing whatever the starter seeded
        db.query(models.ServicePrice).filter_by(clinic_id=clinic.id).delete()
        db.query(models.Branch).filter_by(clinic_id=clinic.id).delete()
        db.query(models.Service).filter_by(clinic_id=clinic.id).delete()
        db.commit()
        branches = {}
        for name, code, oh, ch in BRANCHES:
            b = models.Branch(clinic_id=clinic.id, name=name, code=code,
                              open_hour=oh, close_hour=ch, address=name)
            db.add(b)
            db.flush()
            branches[name] = b
        name, cat, price, mins = SERVICE
        svc = models.Service(clinic_id=clinic.id, name=name, category=cat,
                             base_price=price, duration_min=mins, active=True,
                             description="Targeted acne treatment with extraction, "
                                         "blue light and a care plan.")
        db.add(svc)
        db.flush()
        for bname, bprice in BRANCH_PRICES.items():
            db.add(models.ServicePrice(clinic_id=clinic.id, service_id=svc.id,
                                       branch_id=branches[bname].id, price=bprice))
        db.commit()
        if index_kb and is_configured():
            try:
                rag.reindex(db, clinic.id)
            except Exception as exc:  # pragma: no cover
                print(f"[stress] KB index skipped: {exc}")
        return clinic.id
    finally:
        db.close()


def run_once(cid: int, label: str = "") -> dict:
    """Replay SCRIPT once against a fresh customer; return the scored result."""
    db = SessionLocal()
    try:
        for model in (models.Message, models.Booking, models.Payment,
                      models.Activity, models.Conversation, models.Customer):
            db.query(model).filter_by(clinic_id=cid).delete()
        db.commit()
        # a portal member: web booking is members-only (tools.booking_requires_signup)
        cust = models.Customer(clinic_id=cid, name="Stress Tester", channel="web",
                              password_hash="eval-member",
                              channel_user_id=f"stress-{label}", pipeline_stage="new_lead")
        db.add(cust)
        db.flush()
        # branch_id stays NULL — a real web lead, which is what makes the
        # assistant have to ask (and then remember) the branch.
        conv = models.Conversation(clinic_id=cid, customer_id=cust.id, channel="web",
                                   status="new_lead", sales_stage="greeting")
        db.add(conv)
        db.commit()

        turns, redundant, booked_at = [], [], None
        def _tok():
            row = (db.query(models.TokenUsage)
                   .filter_by(clinic_id=cid)
                   .with_entities(models.TokenUsage.prompt_tokens,
                                  models.TokenUsage.completion_tokens).all())
            return (sum(r[0] or 0 for r in row), sum(r[1] or 0 for r in row))
        tok0 = _tok()
        t0 = time.time()
        for i, (text, known) in enumerate(SCRIPT, start=1):
            db.add(models.Message(clinic_id=cid, conversation_id=conv.id,
                                  sender="customer", text=text))
            db.commit()
            res = respond(db, conv)
            reply = res.get("text", "") or ""
            db.add(models.Message(clinic_id=cid, conversation_id=conv.id, sender="ai",
                                  text=reply, meta=res.get("meta", {})))
            conv.last_message_at = datetime.utcnow()
            db.commit()
            # Production runs analyze() after every reply (inbox.generate_ai_reply);
            # it refreshes conversation.ai_summary, which the next turn's prompt
            # relies on once early turns fall out of the message window.
            try:
                analyze(db, conv)
            except Exception as exc:  # pragma: no cover
                print(f"    [analyze failed: {exc}]")

            asked_again = sorted(s for s in known if _asks_for(reply, s))
            if asked_again:
                redundant.append({"turn": i, "customer": text, "slots": asked_again,
                                  "reply": reply[:160]})
            n_bookings = db.query(models.Booking).filter_by(clinic_id=cid).count()
            if booked_at is None and n_bookings:
                booked_at = i
            turns.append({"turn": i, "customer": text, "reply": reply,
                          "tools": res.get("meta", {}).get("tools", []),
                          "redundant": asked_again})
        tok1 = _tok()
        return {
            "label": label,
            "model": settings.chat_model,
            "prompt_tokens": tok1[0] - tok0[0],
            "completion_tokens": tok1[1] - tok0[1],
            "redundant_asks": len(redundant),
            "redundant_detail": redundant,
            "booked": booked_at is not None,
            "turns_to_book": booked_at,
            "total_turns": len(SCRIPT),
            "seconds": round(time.time() - t0, 1),
            "turns": turns,
        }
    finally:
        db.close()


def _summarise(runs: list[dict]) -> dict:
    ok = [r for r in runs if r]
    red = [r["redundant_asks"] for r in ok]
    booked = [r for r in ok if r["booked"]]
    ttb = [r["turns_to_book"] for r in booked]
    return {
        "runs": len(ok),
        "redundant_avg": round(statistics.mean(red), 1) if red else 0,
        "redundant_all": red,
        "booked": f"{len(booked)}/{len(ok)}",
        "turns_to_book_avg": round(statistics.mean(ttb), 1) if ttb else None,
        "seconds_avg": round(statistics.mean([r["seconds"] for r in ok]), 1) if ok else 0,
        "prompt_tokens_avg": int(statistics.mean([r.get("prompt_tokens", 0) for r in ok])) if ok else 0,
        "completion_tokens_avg": int(statistics.mean([r.get("completion_tokens", 0) for r in ok])) if ok else 0,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="override settings.chat_model")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--compare", action="store_true",
                    help="A/B the current model against gpt-5.6-luna")
    ap.add_argument("--index-kb", action="store_true")
    args = ap.parse_args(argv)

    from app.ai.client import is_configured
    if not is_configured():
        print("OPENAI_API_KEY is not configured — the stress test needs the real model.")
        return 2

    cid = setup(index_kb=args.index_kb)
    models_to_run = ([settings.chat_model, "gpt-5.6-luna"] if args.compare
                     else [args.model or settings.chat_model])
    original = settings.chat_model
    report = {"timestamp": datetime.now().isoformat(timespec="seconds"),
              "prompt_version": None, "script_turns": len(SCRIPT), "by_model": {}}
    from app.ai.prompts import PROMPT_VERSION
    report["prompt_version"] = PROMPT_VERSION

    try:
        for mdl in models_to_run:
            settings.chat_model = mdl
            print(f"\n=== {mdl} · {args.runs} run(s) · prompt v{PROMPT_VERSION} ===")
            runs = []
            for n in range(1, args.runs + 1):
                r = run_once(cid, label=f"{mdl}#{n}")
                runs.append(r)
                print(f"  run {n}: redundant_asks={r['redundant_asks']:<3} "
                      f"booked={'yes' if r['booked'] else 'NO':<3} "
                      f"turns_to_book={r['turns_to_book']} ({r['seconds']}s, "
                      f"tok {r['prompt_tokens']:,}+{r['completion_tokens']:,})")
                for d in r["redundant_detail"]:
                    print(f"      ↻ turn {d['turn']} '{d['customer']}' -> re-asked {d['slots']}")
            report["by_model"][mdl] = {"summary": _summarise(runs), "runs": runs}
            s = report["by_model"][mdl]["summary"]
            print(f"  SUMMARY {mdl}: redundant_avg={s['redundant_avg']} "
                  f"booked={s['booked']} turns_to_book_avg={s['turns_to_book_avg']} "
                  f"tok_avg={s['prompt_tokens_avg']:,}+{s['completion_tokens_avg']:,} "
                  f"({s['seconds_avg']}s)")
    finally:
        settings.chat_model = original

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = report["timestamp"].replace(":", "").replace("-", "").replace("T", "-")[:15]
    path = os.path.join(RESULTS_DIR, f"stress-{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
