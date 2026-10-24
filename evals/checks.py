"""Reusable check builders for eval cases. Each builder returns a callable
``ctx -> CheckResult``. Checks are cheap + programmatic except ``judge`` (LLM)."""
import re
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _norm(s: str) -> str:
    return (s or "").replace(",", "").lower()


def reply_contains(*subs, require_all: bool = False):
    def _c(ctx):
        t = ctx.text.lower()
        hits = [s for s in subs if s.lower() in t]
        ok = (len(hits) == len(subs)) if require_all else bool(hits)
        return CheckResult(f"reply_contains({'|'.join(subs)})", ok,
                           "" if ok else f"not in reply: {ctx.text[:90]!r}")
    return _c


def reply_not_contains(*subs):
    def _c(ctx):
        t = ctx.text.lower()
        bad = [s for s in subs if s.lower() in t]
        return CheckResult(f"reply_not_contains({'|'.join(subs)})", not bad,
                           f"found {bad} in reply" if bad else "")
    return _c


def quotes_price(price):
    """The reply states this price (comma-insensitive)."""
    want = _norm(str(price))
    def _c(ctx):
        ok = want in _norm(ctx.text)
        return CheckResult(f"quotes_price({price})", ok,
                           "" if ok else f"{price} not in reply: {ctx.text[:90]!r}")
    return _c


def used_tool(name):
    def _c(ctx):
        ok = name in ctx.tools
        return CheckResult(f"used_tool({name})", ok, "" if ok else f"tools={ctx.tools}")
    return _c


def used_any_tool(*names):
    def _c(ctx):
        hit = [n for n in names if n in ctx.tools]
        return CheckResult(f"used_any_tool({'|'.join(names)})", bool(hit),
                           "" if hit else f"tools={ctx.tools}")
    return _c


def is_grounded():
    def _c(ctx):
        uns = ctx.meta.get("unsupported", [])
        return CheckResult("is_grounded", not uns, f"unsupported numbers={uns}" if uns else "")
    return _c


def no_discount_flag():
    def _c(ctx):
        df = ctx.meta.get("discount_flags", [])
        return CheckResult("no_invented_discount", not df, f"below-floor prices={df}" if df else "")
    return _c


def no_false_payment_claim():
    def _c(ctx):
        bad = ctx.meta.get("payment_unverified", False)
        return CheckResult("no_false_payment_claim", not bad,
                           "claimed paid without a paid payment" if bad else "")
    return _c


def booked(expected: bool = True):
    def _c(ctx):
        n = len(ctx.bookings)
        ok = (n > 0) is expected
        return CheckResult(f"booked_is_{expected}", ok, f"bookings={n}")
    return _c


def escalated(expected: bool = True):
    def _c(ctx):
        ok = ctx.escalated is expected
        return CheckResult(f"escalated_is_{expected}", ok, f"escalated={ctx.escalated}")
    return _c


# Thai letters/vowels/tones/digits only — U+0E3F is the baht sign, and "฿2,800" is a
# price in any language, not Thai left in an English reply.
_THAI_RE = re.compile(r"[ก-ฺเ-๛]")
_THAI_RUN_RE = re.compile(r"[ก-ฺเ-๛]+")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
_URL_RE = re.compile(r"https?://\S+|\S+@\S+")
# Latin that is legitimately at home in a Thai sentence beyond the clinic's own
# proper nouns (channel and brand names the clinic itself uses).
_ALWAYS_OK = {"ai", "line", "facebook", "messenger", "stripe", "vip", "sms", "qr", "app"}


def _script(text: str) -> str:
    """'th', 'en', or '' — deliberately the SAME function the orchestrator uses to
    decide the reply language, so the eval grades against the real rule."""
    from app.ai.chat import script_of

    return script_of(text)


def _proper_nouns(ctx) -> set:
    """Latin words that may appear in a Thai sentence: the clinic's own names plus
    whatever the customer typed (the prompt orders their name echoed verbatim)."""
    from app import models

    allowed = set(_ALWAYS_OK)
    cid = ctx.clinic.id if ctx.clinic else None
    for model in (models.Service, models.Branch, models.StaffMember):
        for row in ctx.db.query(model).filter_by(clinic_id=cid).all():
            allowed |= {w.lower() for w in _LATIN_WORD_RE.findall(row.name or "")}
    # Promotion titles are catalog names too ("Glow Season", "Intro Bundle") — a reply
    # that surfaces a promotion has to be able to say what it is called.
    for row in ctx.db.query(models.Promotion).filter_by(clinic_id=cid).all():
        allowed |= {w.lower() for w in _LATIN_WORD_RE.findall(row.title or "")}
    allowed |= {w.lower() for w in _LATIN_WORD_RE.findall(
        (ctx.clinic.name if ctx.clinic else "") or "")}
    allowed |= {w.lower() for w in _LATIN_WORD_RE.findall(" ".join(ctx.turns))}
    return allowed


def _prose(ctx) -> str:
    """The reply with URLs and the clinic's own proper nouns removed — what is left
    is the PROSE, and only prose says which language a reply is written in.

    Names must come out BEFORE the script is decided, not only when listing strays:
    "ที่สาขา Main Branch มี Signature Facial ราคาเริ่มต้น ฿2,800 ค่ะ" carries more Latin
    letters in its two names than Thai letters around them, so counted whole it reads
    as an English reply with stray Thai — the opposite of what it is."""
    allowed = _proper_nouns(ctx)
    cleaned = _URL_RE.sub(" ", ctx.text or "")
    return _LATIN_WORD_RE.sub(lambda m: " " if m.group(0).lower() in allowed else m.group(0),
                              cleaned)


# The same allowlist app/ai/chat.py enforces, EXCEPT CJK is deliberately left OUT of it
# here: in production CJK always passes _drop_alien_scripts (a customer's own Chinese/
# Japanese/Korean name is legitimate) and is only judged separately, with backing, by
# _drop_unbacked_cjk. Folding both of those into one check here means a hallucinated
# CJK run — stray Chinese/Japanese/Korean text, the failure that motivated this whole check —
# fails the eval even if some future bug lets it slip past the app's own filters, instead
# of being invisible to grading because CJK is unconditionally "fine" the way it is in
# _drop_alien_scripts. This is a deliberately SEPARATE implementation from chat.py's
# (not a call back into it), so a bug shared between the two doesn't hide from both.
_SAFE_NO_BACKING_RE = re.compile(
    "[\x20-\x7e\t\n\r"
    "\u00a0-\u024f\u1e00-\u1eff"   # Latin-1 Supplement + Latin Extended A/B/Additional
    "\u0e00-\u0e7f"                  # Thai
    "\u2000-\u206f\u20a0-\u20cf"   # general punctuation + currency symbols
    "\u2190-\u21ff\u2600-\u27bf"   # arrows + misc symbols/dingbats
    "\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff"  # emoji
    "\ufe0e\ufe0f\u200d\u20e3]")   # variation selectors + ZWJ + combining keycap


def _stray_script_runs(ctx) -> list:
    """Runs of characters outside the safe set above that the CUSTOMER did not
    themselves type anywhere in this conversation — CJK included. An independent,
    from-scratch scan (not a call into chat.py), so it can catch a live recurrence of
    the glitch even if the bug is in chat.py's own filters."""
    prose = _prose(ctx)
    said = " ".join(ctx.turns).lower()
    runs, i, n = [], 0, len(prose)
    while i < n:
        if _SAFE_NO_BACKING_RE.match(prose[i]):
            i += 1
            continue
        j = i
        while j < n and not _SAFE_NO_BACKING_RE.match(prose[j]):
            j += 1
        token = prose[i:j]
        if token.lower() not in said:
            runs.append(token)
        i = j
    return runs


def single_language():
    """One reply, one language.

    The system prompt is written in English and the model has been caught leaving its
    wording inside a Thai sentence ("ติดต่อกลับ shortly ค่ะ"), which reads as a
    half-translated bot; it has also been caught leaving stray Chinese/Japanese/Korean
    characters, or characters from a script the clinic never writes in at all, glued
    into an otherwise Thai or English reply. Checks whichever script is the minority
    for Thai/Latin mixing, PLUS any CJK-or-other-script run the customer never
    themselves typed, regardless of which language dominates the reply. Proper names
    are exempt via the clinic's own catalog rather than a guessed word list, and URLs
    are stripped so a payment link is not mistaken for prose.
    """
    def _c(ctx):
        prose = _prose(ctx)
        lang = _script(prose)
        alien = _stray_script_runs(ctx)
        if lang == "th":
            stray = sorted(set(_LATIN_WORD_RE.findall(prose))) + alien
            return CheckResult("single_language", not stray,
                               f"English left in a Thai reply: {stray}" if stray else "")
        if lang == "en":
            stray = sorted(set(_THAI_RUN_RE.findall(prose))) + alien
            return CheckResult("single_language", not stray,
                               f"Thai left in an English reply: {stray}" if stray else "")
        if alien:
            return CheckResult("single_language", False,
                               f"stray script in reply: {alien}")
        return CheckResult("single_language", True, "no prose to judge")
    return _c


def matches_customer_language():
    """Answer in the language the CUSTOMER wrote in — Thai in, Thai out; English in,
    English out. Uses the orchestrator's own resolver, so a bare "11:00" and a lone
    "Hello" (which Thai customers type too) are treated here exactly as the app
    treats them."""
    def _c(ctx):
        from app.ai.chat import clinic_name_words, customer_language

        # The SAME call the orchestrator makes — clinic names included — or a Thai
        # question about "Botox Jaw Slimming" grades as an English customer here while
        # the app (correctly) answered in Thai.
        names = clinic_name_words(ctx.db, ctx.clinic.id) if ctx.clinic else frozenset()
        want = customer_language(ctx.turns, names)
        got = _script(_prose(ctx))
        if not got:
            return CheckResult("matches_customer_language", True, "no prose to judge")
        return CheckResult("matches_customer_language", want == got,
                           "" if want == got else f"customer wrote {want}, reply is {got}")
    return _c


def judge(rubric: str):
    """LLM judge — grade the reply against a pass/fail rubric (uses OpenAI)."""
    def _c(ctx):
        from evals.judge import grade
        ok, reason = grade(ctx.text, rubric, "\n".join(ctx.turns))
        return CheckResult("judge", ok, reason)
    return _c


# Properties every reply must have, whatever the case is about. The harness appends
# these to each case's own checks, so adding a case cannot forget them.
ALWAYS_ON = (single_language(), matches_customer_language())
