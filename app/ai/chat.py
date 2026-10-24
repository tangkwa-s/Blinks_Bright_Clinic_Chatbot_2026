"""AI chat orchestrator — RAG + memory + streaming tool calling + grounding guard."""
import json
import re
from pathlib import Path
from datetime import datetime, timedelta

from app import models
from app.ai import guard, guardrails, usage
from app.ai.client import chat_completion, is_configured
from app.ai.context import build_context
from app.config import settings
from app.ai.memory import customer_memory, past_conversations, workflow_state
from app.ai.prompts import PROMPT_VERSION, build_system_prompt
from app.ai.tools import TOOLS, execute_tool
from app.scope import scoped
from app.services.booking import deposit_for

FALLBACK_TH = (
    "ขอบคุณสำหรับข้อความค่ะ 😊 เดี๋ยวทีมงานจะรีบติดต่อกลับเพื่อให้ข้อมูลเพิ่มเติมนะคะ"
)
MAX_TOOL_LOOPS = 4
# Defensive cap on the persisted grounding trail (Message.meta.grounding) — no observed
# turn comes close to this, but the JSON column has no size limit of its own.
GROUNDING_TRAIL_MAX_CHARS = 8000


def _no_emdash(s: str) -> str:
    """Strip em / en / horizontal dashes the model may emit despite the prompt rule."""
    return (s or "").replace("—", "-").replace("–", "-").replace("―", "-")


# Zero-width space (U+200B), bidi mark/embedding/override/isolate controls
# (U+200E-200F, U+202A-202E, U+2066-2069), the replacement character (U+FFFD), and the
# Private Use Area (U+E000-F8FF) -- never legitimate VISIBLE content in a clinic reply.
# ZWJ/ZWNJ (U+200C/200D) are deliberately absent: real multi-codepoint emoji (a family
# emoji, a flag) are built out of them, and stripping them unconditionally would break
# those. Written as explicit \uXXXX escapes, never literal glyphs -- see the comment on
# _CJK_CHAR below for why that matters here.
_INVISIBLE_RE = re.compile(
    "[\u200b\u200e\u200f\u202a-\u202e\u2066-\u2069\ufffd\ue000-\uf8ff]")


def _drop_invisible(s: str) -> str:
    """Delete control/formatting characters that have no legitimate visible use here."""
    return _INVISIBLE_RE.sub("", s or "")


# --------------------------------------------------------------------------
# What this assistant is ever expected to write. Built as an ALLOWLIST rather than a
# hand-enumerated list of "known bad" scripts (the previous approach -- Cyrillic, Greek,
# Armenian, Hebrew, Arabic, Devanagari -- needed a new patch every time a glitch showed
# up in a script not yet on the list, e.g. Lao/Khmer/Myanmar/Georgian/accented Latin).
# Anything outside this set is alien and gets the same customer-said/clinic-name
# exemption the original six-script check used. CJK is included here so it is never
# flagged as "alien" by THIS function -- a Chinese/Japanese/Korean customer's own name
# is common enough here to need more than a bare keep-if-quoted rule, so it gets its
# own hybrid backing check in ``_drop_unbacked_cjk`` instead.
#
# Every range below is an explicit \uXXXX/\UXXXXXXXX escape, never a literal glyph --
# CJK Compatibility Ideographs (U+F900...) and their canonical CJK Unified twins render
# identically but are different codepoints, and a copy-pasted literal silently picks
# whichever one the input method normalises to. Verify any change to this block with
# ``ord()`` on every character, not by eye.
# --------------------------------------------------------------------------
_CJK_CHAR = "\u3040-\u30ff\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\uac00-\ud7a3"
_EXPECTED_RE = re.compile(
    "[\x20-\x7e\t\n\r"        # printable ASCII + whitespace
    "\u00a0-\u024f"              # Latin-1 Supplement + Latin Extended A/B (accented names)
    "\u1e00-\u1eff"              # Latin Extended Additional (Vietnamese: Nguy\u1ec5n, Th\u1ea3o...)
    "\u0e00-\u0e7f"              # Thai (the whole block -- currency sign etc. are fine here)
    "\u2000-\u206f"              # general punctuation (smart quotes, bullets, ellipsis...)
    "\u20a0-\u20cf"              # currency symbols (euro sign etc; baht/dollar/yen covered above)
    "\u2190-\u21ff"              # arrows
    "\u2600-\u27bf"              # misc symbols & dingbats
    "\U0001f1e6-\U0001f1ff"      # regional indicators (flag emoji)
    "\U0001f300-\U0001faff"      # emoji blocks
    "\ufe0e\ufe0f"               # emoji/text variation selectors
    "\u200d\u20e3"               # ZWJ (compound emoji) + combining keycap (as in 1-keycap emoji)
    f"{_CJK_CHAR}"                # CJK -- never alien here, see docstring above
    "\u1100-\u11ff"              # Hangul Jamo
    "\u3000-\u303f"              # CJK punctuation/symbols
    "\uff00-\uffef]")            # halfwidth/fullwidth forms


def _drop_alien_scripts(s: str, customer_text: str = "") -> str:
    """Delete stray foreign-script gibberish the model tacks onto a reply.

    A real reply ended "...ด้วยนะคะеfoн". It is rare and random, so no prompt rule can
    be trusted to prevent it and no test can reliably provoke it — but it is trivially
    detectable, because the assistant only ever writes Thai and English (plus CJK for a
    customer's own name — handled separately). Anything the CUSTOMER wrote is kept:
    their name may genuinely be in one of these scripts, and echoing it back is correct.
    """
    text = s or ""
    n = len(text)
    is_alien = [not _EXPECTED_RE.match(ch) for ch in text]
    if not any(is_alien):
        return text
    # Widen each alien position to swallow adjacent Latin letters glued onto it: the
    # observed glitch was "еfoн" — Cyrillic-Latin-Latin-Cyrillic stuck together with no
    # space, and only the Cyrillic chars are "alien" on their own.
    for i in [k for k, v in enumerate(is_alien) if v]:
        j = i - 1
        while j >= 0 and text[j].isascii() and text[j].isalpha():
            is_alien[j] = True
            j -= 1
        j = i + 1
        while j < n and text[j].isascii() and text[j].isalpha():
            is_alien[j] = True
            j += 1
    said = (customer_text or "").lower()
    out, i = [], 0
    while i < n:
        if not is_alien[i]:
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < n and is_alien[j]:
            j += 1
        token = text[i:j]
        if token.lower() in said:
            out.append(token)
        i = j
    # tidy the space left where a standalone token used to be
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()


# Words that address a customer by name — CJK immediately after one of these is almost
# certainly the customer's own name, the only pattern the assistant is ever shown using
# CJK for at all.
_ADDRESS_WORD_RE = re.compile(r"(?:คุณ|Mr\.?|Mrs\.?|Ms\.?|khun)\s*$", re.IGNORECASE)
_CJK_RUN_RE = re.compile(f"[{_CJK_CHAR}]+")


def _drop_unbacked_cjk(text: str, customer_text: str = "", crm_names: str = "") -> str:
    """Delete a CJK run the customer never said and nothing in the CRM record backs.

    ``_drop_alien_scripts`` never touches CJK anywhere in a reply — a Chinese/Japanese/
    Korean customer's own name is legitimate content the prompt forbids translating —
    but that also means hallucinated CJK glued into the MIDDLE of a reply (not just the
    tail, which ``_drop_trailing_gibberish`` already catches) has no filter at all. A
    CJK run is kept when: the customer typed it themselves anywhere in this
    conversation; it's part of their saved CRM name/nickname (covers a name a staff
    member entered that the customer never typed); or it immediately follows an address
    word ("คุณ田中") — the only shape the assistant is ever shown using CJK for.
    Anything else goes.
    """
    text = text or ""
    if not _CJK_RUN_RE.search(text):
        return text
    said = (customer_text or "").lower()
    crm = (crm_names or "").lower()

    def _keep(m):
        token = m.group(0)
        if token.lower() in said or (crm and token.lower() in crm):
            return token
        if _ADDRESS_WORD_RE.search(text[:m.start()]):
            return token
        return ""

    out = _CJK_RUN_RE.sub(_keep, text)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


# Thai letters, vowels, tone marks and digits — NOT the whole U+0E00 block: U+0E3F is
# the baht sign, and "฿2,800" in an English reply is a price, not Thai prose.
_THAI_RE = re.compile(r"[ก-ฺเ-๛]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
_URL_RE = re.compile(r"https?://\S+|\S+@\S+")

# A lone Latin word hanging off the end of a Thai reply — with punctuation/space before
# it, or (like the digit glitch below) glued straight onto the Thai text with nothing at
# all. Bounded with lookaround against [A-Za-z0-9] rather than \b: \b treats Thai letters
# as word characters too, so "ค่ะabc" has no \w/\W transition at all right before the "a"
# and the boundary silently never fires — measured zero legitimate replies either way.
_TRAILING_LATIN = re.compile(
    r"[\s.,;:!?)\]]*(?<![A-Za-z0-9])([A-Za-z][A-Za-z'\-]{1,14})(?![A-Za-z0-9])[\s.,;:!?]*$")
# Chinese/Japanese/Korean characters glued onto the end. _drop_alien_scripts
# deliberately leaves CJK alone everywhere in a reply (a customer's own name in one
# of these scripts is legitimate content), but a run stuck on the very tail, after
# everything else has already been said, needs the same customer-said/clinic-name/URL
# exceptions as the Latin case: a real glitch ended "...ไหนคะ 乐彩". Hangul included on
# the same reasoning even though no Korean glitch has been observed yet -- measured zero
# legitimate replies contain it at all. Reuses the module-level ``_CJK_CHAR`` defined
# above (not a second copy of it), so there is exactly one source of truth for what
# counts as CJK in this file.
_TRAILING_CJK = re.compile(rf"[\s.,;:!?)\]]*([{_CJK_CHAR}]+)[\s.,;:!?]*$")
# A digit run glued with NO space at all onto the reply's own punctuation -- a real phone
# number/price/time is never written this way (always a space before it, and a unit word
# after: "บาท"/"น."/etc). No length cap, unlike an earlier version of this pattern: a
# legitimate reply never ends in a digit glued on with no space, whether the run is
# 1 digit or 10. The glitch looks like "...ด้วยนะคะ1".
_TRAILING_DIGITS = re.compile(r"(?<=[^\s0-9])([0-9]+)[\s.,;:!?]*$")
# The same giveaway words guardrails.unbacked_offers already knows how to judge as
# backed/unbacked -- one wordlist, not two. Longest-first so "เครดิตฟรี" is matched whole
# rather than as a bare "ฟรี" with "เครดิต" left dangling in front of it. The captured
# group runs up to 20 chars past the word itself so a trailing polite particle
# ("ฟรีค่ะ") is swept up with it, not left as its own orphaned tail.
_OFFER_ALT = "|".join(re.escape(w) for w in
                      sorted(guardrails._OFFER_WORDS, key=len, reverse=True))
_TRAILING_OFFER = re.compile(
    rf"[\s.,;:!?)\]]*((?:{_OFFER_ALT})[^\n]{{0,20}})$", re.IGNORECASE)


def _drop_trailing_gibberish(s: str, keep: frozenset = frozenset(),
                             customer_text: str = "", grounding: str = "") -> str:
    """Delete a stray token stuck on the very end of a reply.

    Sibling of ``_drop_alien_scripts``, for glitches that guard doesn't cover: a Latin
    word ("ขอเบอร์โทรสำหรับการจองด้วยนะคะ.ones." -- Latin letters, so the alien-script
    strip passed it straight through), a run of Chinese/Japanese characters (that guard
    deliberately leaves CJK alone everywhere ELSE, since a customer's own name may be in
    it -- but a token glued onto the tail with nothing before or after it never is), a
    bare digit or two with no space before it at all, or a giveaway word ("เครดิตฟรี")
    the reply itself introduces with nothing in the grounding or the customer's own
    words to back it -- the exact shape ``guardrails.unbacked_offers`` already detects,
    just never wired up anywhere to actually remove the text. Kept when the token is one
    of the clinic's own names, something the CUSTOMER wrote (digit runs are matched on
    digit boundaries, not plain substring, so a stray "1" isn't excused just because
    their phone number happens to contain a 1 somewhere), or part of a URL -- never chew
    the tail off a payment link.

    Only the Latin check is gated to a Thai-majority reply -- stripping a trailing
    English word only makes sense when the rest of the reply is Thai; an English reply
    ending in an English word is normal. The CJK/digit/offer checks run whichever
    language the reply is classified as: a glitch glued to the tail, or an invented
    giveaway, is suspect either way, and gating them to Thai-only meant an English-
    classified reply got no trailing cleanup at all. Measured against every AI message
    in this database before being switched on: of 893, not one legitimate reply ended
    in a Latin word, any CJK character, or a bare digit -- every match was one of the
    glitches above.
    """
    text = s or ""
    customer_lower = (customer_text or "").lower()
    patterns = []
    if script_of(text) == "th":
        patterns.append((_TRAILING_LATIN, "text"))
    patterns.append((_TRAILING_CJK, "text"))
    patterns.append((_TRAILING_DIGITS, "digits"))
    patterns.append((_TRAILING_OFFER, "offer"))
    for pattern, kind in patterns:
        m = pattern.search(text)
        if not m:
            continue
        token = m.group(1)
        if kind == "digits":
            said = re.search(rf"(?<!\d){re.escape(token)}(?!\d)", customer_text or "")
            backed = token.lower() in keep or bool(said)
        elif kind == "offer":
            backed = not guardrails.unbacked_offers(token, grounding, customer_text)
        else:
            backed = token.lower() in keep or token.lower() in customer_lower
        if backed:
            continue
        if any(u.end() >= m.start(1) for u in _URL_RE.finditer(text)):
            continue                     # never chew the tail off a payment link
        return text[:m.start()].rstrip()
    return text


# What sits between two branch names in a list, in either language. A bare space counts:
# Thai drops the conjunction freely ("ตอนนี้เรามีสาขาสีลม สาขาทองหล่อค่ะ") and requiring a
# comma or "และ" let exactly that shape through uncorrected. The optional trailing "สาขา"
# is the word that usually prefixes the next name.
_BRANCH_JOIN = (r"(?:\s*(?:,|、|/|·|และ|กับ|หรือ|and|or)\s*|\s+)"
                r"(?:สาขา\s*|branch\s+)?")


def _correct_branch_list(db, conversation, text: str) -> str:
    """Strike out branches that cannot serve the treatment the reply is about.

    Every earlier layer identifies the treatment from what the CUSTOMER typed, and that
    has one blind spot the model does not: spelling. A customer answering "ไฮฟู" never
    matches a catalog "Hifu", so nothing narrowed the question and the assistant offered
    all three branches for a treatment that exists at two — while its own draft opened
    with "สนใจ Hifu ใช่ไหมคะ". The draft is the one place the treatment is always named
    canonically, whatever the customer called it, so the last check reads that.

    Only an ENUMERATION of two or more branch names is rewritten. A lone mention is left
    exactly as written, because the sentence naming a single branch is usually the
    correct one ("this treatment is not available at X"), and editing it would invert
    its meaning.

    **LINE by line, because a menu holds several answers at once.** Taking one allowed
    set for the whole reply meant intersecting the branch sets of every treatment named
    in it, and an opening menu names them all: Test (วัดพระศรี+วัดเสมียนนารี) and Hifu
    (วัดเสมียนนารี+สยามพารากอน) intersect to วัดเสมียนนารี alone, so both lines — each
    correct as written — were rewritten to that single branch. A line naming one
    treatment is judged against THAT treatment; a line naming several is left alone;
    and a line naming none falls back to the reply's treatment only when the whole reply
    is about one. Same unit as tools._figures_already_quoted uses to attribute prices.
    """
    from app.ai.tools import active_services, branches_offering, services_named_in

    if not text or not conversation:
        return text
    services = active_services(db, conversation.clinic_id)
    whole = services_named_in(text, services)
    branches = scoped(db, models.Branch, conversation.clinic_id).order_by(models.Branch.id).all()
    # Longest first so "North Aurora" wins over a branch merely called "Aurora".
    any_branch = "|".join(re.escape(b.name) for b in
                          sorted(branches, key=lambda b: len(b.name or ""), reverse=True))
    if not any_branch:
        return text
    run = re.compile(f"(?:{any_branch})(?:{_BRANCH_JOIN}(?:{any_branch}))+")
    # The branch NAMES are Thai even in an English reply, so measure the script of what
    # is left once they are taken out — same reason _decisive_script discounts them.
    joiner = " และ " if script_of(re.sub(any_branch, " ", text)) == "th" else " and "

    def _fix_line(line: str) -> str:
        here = services_named_in(line, services)
        scope = here if here else (whole if len(whole) == 1 else [])
        if len(scope) != 1:
            return line               # a menu line naming several has no single answer
        allowed = branches_offering(db, conversation.clinic_id, scope)
        if not allowed:
            return line               # offered everywhere - nothing to narrow
        ok_names = [b.name for b in branches if b.id in allowed]
        if not ok_names or len(ok_names) == len(branches):
            return line
        fixed = ((", ".join(ok_names[:-1]) + joiner + ok_names[-1])
                 if len(ok_names) > 1 else ok_names[0])

        def _swap(m):
            listed = [b.name for b in branches if b.name in m.group(0)]
            return fixed if any(n not in ok_names for n in listed) else m.group(0)

        return run.sub(_swap, line)

    return "\n".join(_fix_line(ln) for ln in text.split("\n"))



def script_of(text: str) -> str:
    """Which script a message is written in: 'th', 'en', or '' for neither.

    Compared by character count rather than presence, so a Thai sentence quoting
    "Signature Facial" is still Thai and an English one naming a Thai branch is still
    English. '' covers a bare time, price or phone number, which says nothing about
    the writer's language.
    """
    clean = _URL_RE.sub(" ", text or "")
    thai = len(_THAI_RE.findall(clean))
    latin = sum(len(w) for w in _LATIN_WORD_RE.findall(clean))
    if not thai and not latin:
        return ""
    return "th" if thai >= latin else "en"


# English words that do NOT prove the customer wants English: greetings and fillers a
# Thai customer types just as readily ("Hello", "ok", "thanks"). A message made only of
# these is skipped, so a Thai speaker opening with "Hello" is still answered in Thai.
_AMBIGUOUS_LATIN = {
    "hello", "hey", "helo", "hallo", "okay", "yes", "yep", "yeah", "sure", "fine",
    "thanks", "thank", "you", "please", "good", "morning", "afternoon", "evening",
    "sawasdee", "sawaddee", "krub", "krap", "kha", "cool", "nice", "welcome",
}


def _decisive_script(text: str, names: frozenset = frozenset()) -> str:
    """``script_of``, except a Latin message that is ONLY greetings/fillers decides
    nothing and returns '' so an earlier, more telling message is used instead.

    ``names`` extends that with the clinic's own Latin-script proper nouns. This is
    load-bearing here: the branches and treatments are NAMED in Latin ("South Aurora",
    "HIFU Lifting"), so answering the branch question with "South Aurora" — the single
    most common one-word reply a Thai customer sends — otherwise reads as English and
    flips the whole conversation.
    """
    clean = _URL_RE.sub(" ", text or "")
    if names:
        # Drop the clinic's own Latin names BEFORE counting scripts, not after: in
        # "Botox Jaw Slimming ราคาเท่าไหร่คะ" the treatment name alone out-counts the Thai
        # question around it, so the message read as English and was then thrown away
        # as "only names" — correct by accident, and one older English "Hi" away from
        # flipping the reply. With the names gone it is simply a Thai question.
        clean = _LATIN_WORD_RE.sub(lambda m: " " if m.group(0).lower() in names else m.group(0),
                                   clean)
    s = script_of(clean)
    if s != "en":
        return s
    words = [w.lower() for w in _LATIN_WORD_RE.findall(clean)]
    return "" if words and all(w in _AMBIGUOUS_LATIN for w in words) else "en"


def clinic_name_words(db, clinic_id) -> frozenset:
    """Lowercased Latin words making up this clinic's branch, treatment, staff and
    promotion names.

    Words that are also ordinary English ("skin", "lifting") are kept: a message made
    ONLY of them is the customer naming something off the menu, not writing English.
    """
    out: set[str] = set()
    for model in (models.Branch, models.Service, models.StaffMember):
        for row in scoped(db, model, clinic_id).all():
            out.update(w.lower() for w in _LATIN_WORD_RE.findall(row.name or ""))
    # Promotions are named in Latin too ("Glow Season", "First Visit Offer"), and a
    # customer answering "Glow Season" is naming something off the menu, not switching
    # to English.
    for row in scoped(db, models.Promotion, clinic_id).all():
        out.update(w.lower() for w in _LATIN_WORD_RE.findall(row.title or ""))
    return frozenset(out)


def customer_language(texts, names: frozenset = frozenset()) -> str:
    """Which language to answer this customer in: 'th' or 'en'.

    Newest message first, taking the first one that actually settles it. That makes
    the choice sticky in the useful direction: "ok" or "thanks" after an English
    conversation stays English, while "Hello" from someone who has been writing Thai
    stays Thai. Defaults to Thai — the clinic is in Thailand, and a lone English
    greeting is not evidence. ``names`` — see ``_decisive_script``.
    """
    return next((s for s in (_decisive_script(t, names) for t in reversed(list(texts))) if s),
                "th")


def _language_directive(convo, names: frozenset = frozenset()) -> str:
    """Tell the model, as a computed fact, which language to answer in.

    The prompt rule alone loses: nearly all of CLINIC INFORMATION (treatments, KB,
    aftercare) is Thai, so an English "Hello" still drew a fully Thai reply. Deciding
    it here from the customer's own messages — the same way the booking checklist is
    stated rather than inferred — is what actually holds.
    """
    lang = customer_language((m.text for m in convo if m.sender == "customer"), names)
    name = "English" if lang == "en" else "Thai"
    return (f"REPLY LANGUAGE: this customer is writing in {name}. Write your ENTIRE reply "
            f"in {name} - every sentence, including anything you take from the examples in "
            "these instructions. Do not mix in another language (clinic, treatment, branch "
            "and doctor names keep their own spelling). If their next message switches "
            "language, switch with it.")


def _contact_grounding(convo, customer) -> str:
    """Contact details the customer supplied, folded into the grounding text.

    The booking summary repeats the customer's own phone number back to them, and the
    hallucination guard flags every 3+ digit number it cannot find in the context — so
    without this, each booking summary would be marked ungrounded. Deliberately narrow:
    only phone/email-shaped text counts (as typed AND normalised), so a bare price the
    customer proposed is still caught by the guard.

    The guard splits on non-digit characters (``\\d{3,}``), so a normalised number is
    also folded in through its STANDARD GROUPED form (091-123-4567), not just the raw
    digits — the AI is now told to always SAY the number that way (see
    ``_booking_hint``), never in whatever shape the customer originally typed it (e.g.
    a "+66" prefix), so the grounding string must carry the same dash positions the
    reply will, or a perfectly legitimate confirmation gets flagged as hallucinated.
    """
    from app.ai.sales import _EMAIL_RE, _PHONE_RE, _extract_phone, format_thai_mobile

    parts: list[str] = []
    for m in convo:
        if m.sender != "customer":
            continue
        text = m.text or ""
        parts += [mt.group(1) for mt in _PHONE_RE.finditer(text)]
        parts += re.findall(r"\+66[\s\-]?[\d\-\s]{7,11}\d", text)
        parts += _EMAIL_RE.findall(text)
        extracted = _extract_phone(text)
        parts.append(extracted)
        if extracted:
            parts.append(format_thai_mobile(extracted))
    if customer:
        parts += [customer.phone or "", customer.email or ""]
        if customer.phone:
            parts.append(format_thai_mobile(customer.phone))
    return " ".join(p for p in parts if p)


def _booking_hint(db, conversation, customer, asked=None, allowed=None) -> str:
    """State of the booking checklist that the SYSTEM can answer authoritatively.

    Branch (on the conversation) and name/phone (on the customer record) are facts we
    hold in the DB. The model is unreliable at tracking them across turns, which is
    exactly what makes it re-ask questions the customer already answered, so we spell
    out what is known and what is still missing every turn. Treatment and date/time
    live only in the transcript, so those stay the model's job.
    """
    from app.ai.sales import _is_placeholder_name, format_thai_mobile

    branches = (scoped(db, models.Branch, conversation.clinic_id)
                .order_by(models.Branch.id).all())
    # Which branches may even be offered: a treatment restricted to a subset of them
    # narrows the question. ``respond`` resolves this from the transcript + the DB and
    # passes it in, so the catalog block and this checklist cannot state different
    # branches; the fallback keeps direct callers (tests) working.
    if asked is None:
        from app.ai.tools import branches_offering, treatments_named_by_customer
        asked = treatments_named_by_customer(db, conversation)
        allowed = branches_offering(db, conversation.clinic_id, asked)
    current = next((b for b in branches if b.id == conversation.branch_id), None)
    if current:
        # Confidence matters: conversation.branch_id can be written from the model's
        # OWN tool-call argument, so a hallucinated branch used to come back one turn
        # later labelled authoritative ("KNOWN — never ask again") and the assistant
        # confirmed a branch the customer never picked. Only call it KNOWN when the
        # customer's own words plausibly contain it; otherwise require the assistant
        # to STATE it once so the customer can correct it (statement, not a re-ask).
        # One corroboration definition for the whole system: the same check the
        # tools use to accept/reject a model-passed branch (tools._branch_said_by_customer).
        from app.ai.tools import _branch_said_by_customer
        verified = _branch_said_by_customer(db, conversation, current, None)
        if verified:
            branch_line = (f"2. Branch: KNOWN = {current.name}. Never ask which branch again; "
                           "pass this branch to every tool call.")
        else:
            branch_line = (f"2. Branch: currently set to {current.name}, but the customer has "
                           "not clearly named it in this chat. Do NOT present it as their "
                           f"choice silently: state it once in your next reply (e.g. 'สาขา "
                           f"{current.name} นะคะ') so they can correct you, and switch "
                           "immediately if they name a different branch. Do not ask an open "
                           "which-branch question — just state it.")
        # They chose a branch that does not have what they came for. Saying nothing and
        # listing that branch's other treatments reads as an answer, so the customer
        # never learns why the one they asked for vanished.
        off_menu = [s for s in asked if allowed is not None and current.id not in allowed]
        if off_menu:
            elsewhere = [b.name for b in branches if allowed and b.id in allowed]
            branch_line += (f" {', '.join(s.name for s in off_menu)} is NOT offered at "
                            f"{current.name} — it is available at {', '.join(elsewhere)}. Say that "
                            "plainly in your next reply and offer to switch branch. Do not answer "
                            "with a different treatment as if nothing happened, and do not say the "
                            "team will check: the clinic system already knows.")
    elif len(branches) > 1:
        # "Name every one" is right until the customer names a treatment that only some
        # branches offer: then every one includes branches that cannot serve them, and
        # picking one of those sends the whole conversation back to the start. The
        # branches a treatment runs at are in the DB, so the list is computed, not left
        # to the model to remember — same reader the list_treatments tool uses.
        offer = [b for b in branches if allowed is None or b.id in allowed] or branches
        scope_note = ""
        if len(offer) < len(branches):
            scope_note = (f" {', '.join(s.name for s in asked)} is NOT offered at the other "
                          "branches, so do not name them — if the customer asks for one, say "
                          "plainly that this treatment is not available there.")
        branch_line = ("2. Branch: NOT chosen yet. Ask it as soon as a TREATMENT is in play, "
                       "never in the opening reply — someone who has only said hello has "
                       "nothing to choose a branch for. When you do ask, name every branch "
                       "that offers what they asked for, and only those: "
                       + ", ".join(b.name for b in offer) + "." + scope_note)
        usual = next((b for b in offer
                      if customer and b.id == customer.branch_id), None)
        if usual:
            branch_line += (f". The customer's USUAL branch from past visits is {usual.name}: "
                            "suggest it ('สะดวกสาขา " + usual.name + " เหมือนเดิมไหมคะ') but let "
                            "them confirm — never assume it, they may want a different branch "
                            "this time.")
    else:
        branch_line = "2. Branch: this clinic has one branch, nothing to ask."

    name = (customer.name if customer else "") or ""
    if name and not _is_placeholder_name(name):
        name_line = f"4. Name: KNOWN = {name}. Do not ask for it again."
    else:
        name_line = ("4. Name: NOT on file (only a channel placeholder) — ask for it before "
                     "the booking summary.")
    phone = (customer.phone if customer else "") or ""
    if phone:
        phone_line = (f"5. Phone: KNOWN = {phone}. Do not ask for it again. When you write it "
                      f"back to the customer (in the summary or a confirmation), use the "
                      f"standard grouped form {format_thai_mobile(phone)} — never raw digits "
                      "with no separators, and never the customer's own typed formatting.")
    elif customer and customer.phone_declined:
        phone_line = ("5. Phone: the customer confirmed they have none — write '-' for phone "
                      "in the booking summary and when calling book_appointment. Do not ask "
                      "again.")
    else:
        phone_line = "5. Phone: NOT on file — ask for it before the booking summary."

    # The CRM only learns the name/phone AFTER this reply (sales.analyze runs
    # post-reply, _capture_contact at booking time), so on the very turn the
    # customer types their contact the lines above still say NOT on file — and the
    # model, told the block was authoritative, re-asked for a name sitting right
    # there in the transcript. Scan the customer's own messages so freshly-typed
    # contact counts as KNOWN immediately.
    from app.ai.sales import _extract_phone, phone_digits, phone_problem, phone_rejection_say_it_like
    chat_blob = "\n".join(m.text or "" for m in
                          scoped(db, models.Message, conversation.clinic_id)
                          .filter_by(conversation_id=conversation.id, sender="customer")
                          .order_by(models.Message.id).all())
    if "NOT on file" in phone_line:
        typed_phone = _extract_phone(chat_blob)
        if typed_phone:
            phone_line = (f"5. Phone: the customer already TYPED it in this chat — it is "
                          f"{format_thai_mobile(typed_phone)}. Write it back in EXACTLY that "
                          "grouped form (never their raw typed text — no +66 prefix, no "
                          "missing dashes), thank them once, and never ask again (pass it to "
                          "book_appointment as phone).")
        elif phone_problem(chat_blob):
            # They DID answer; the number is simply unusable. Without this the line still
            # read "NOT on file", the assistant filled the silence with "บันทึกเบอร์
            # 09545626666 ให้แล้วนะคะ", and the customer only found out at payment time.
            #
            # Told only the FACT in prose, the model would still paraphrase it on its
            # own — sometimes stating the wrong digit count, sometimes reverting to
            # the "a Thai phone number has 10 digits" framing this wording deliberately
            # drops. Same fix as everywhere else in this codebase a precise fact must
            # survive contact with the model: hand it the finished sentence (shared
            # with tools.py::_phone_rejection so pre- and post-tool-call wording can
            # never disagree) and tell it to use that verbatim, not describe the
            # situation and hope.
            digits = phone_digits(chat_blob)
            problem = phone_problem(chat_blob)
            say_it_like, say_it_like_en = phone_rejection_say_it_like(problem, digits)
            phone_line = (f"5. Phone: the customer gave {digits}, which is not a valid Thai "
                          "mobile number — the clinic system did NOT store it. Say EXACTLY "
                          "this, word for word, never your own paraphrase and never a different "
                          f"digit count — Thai: \"{say_it_like}\" / English: \"{say_it_like_en}\" "
                          "(pick whichever matches the language you are replying in). Do NOT say "
                          "it was saved, and do NOT put it in a booking summary as though it were "
                          "on file.")
    if "NOT on file" in name_line and re.search(r"ชื่อ\s*\S+|(?:ผม|ฉัน|หนู)ชื่อ", chat_blob):
        name_line = ("4. Name: the customer already stated it in this chat — read it from "
                     "the transcript, and never ask again (pass it to book_appointment "
                     "as customer_name).")

    return ("BOOKING CHECKLIST STATUS (what the clinic system has SAVED. For branch it is "
            "authoritative. For name/phone the transcript can be AHEAD of it: anything the "
            "customer already typed in this chat wins over a NOT-on-file line below):\n"
            f"{branch_line}\n{name_line}\n{phone_line}\n"
            "1. Treatment and 3. date/time: take them from this chat — anything the "
            "customer has already said counts as known, so never ask for it twice."
            + _hold_hint(db, conversation, customer)
            + _bookings_elsewhere_hint(db, conversation, customer, current))


def _hold_hint(db, conversation, customer) -> str:
    """An unpaid booking is HELD, not confirmed, and only until a deadline.

    A hold is a fact with a clock on it, so it cannot be something the model remembers
    from an earlier turn — the minutes remaining are different every turn, and the worst
    thing it can do is tell someone at minute 25 that their appointment is confirmed.
    Recomputed here each reply, from the same column day_availability reads.
    """
    if not customer:
        return ""
    from app.services.booking import EXPIRED, _now_local

    now = _now_local()
    lines = []
    for b in (scoped(db, models.Booking, conversation.clinic_id)
              .filter(models.Booking.customer_id == customer.id,
                      models.Booking.hold_expires_at.isnot(None),
                      models.Booking.status.in_(["pending", EXPIRED]))
              .order_by(models.Booking.slot_at).all()[:3]):
        svc = db.get(models.Service, b.service_id)
        br = db.get(models.Branch, b.branch_id) if b.branch_id else None
        what = (f"{svc.name if svc else 'treatment'}"
                + (f" at {br.name}" if br else "")
                + f", {b.slot_at:%d/%m %H:%M}")
        if b.status == EXPIRED or b.hold_expires_at <= now:
            lines.append(f"- {what} — the hold LAPSED at {b.hold_expires_at:%H:%M} and the "
                         "slot was released. The customer has already been told. Say so "
                         "plainly if they refer to it; never describe it as still booked.")
        else:
            left = max(1, int((b.hold_expires_at - now).total_seconds() // 60))
            lines.append(f"- {what} — HELD until {b.hold_expires_at:%H:%M}, {left} minutes "
                         f"left, ฿{int(b.deposit_required or 0):,} deposit still unpaid.")
    # A slip waiting for staff pauses the hold (services/slips.py): hold_expires_at is
    # NULL, so the loop above never sees it, and without this line the assistant would
    # carry on asking for a payment the customer has just sent proof of.
    for p in (scoped(db, models.Payment, conversation.clinic_id)
              .filter(models.Payment.customer_id == customer.id,
                      models.Payment.status == "pending",
                      models.Payment.slip_received_at.isnot(None))
              .order_by(models.Payment.id.desc()).all()[:3]):
        b = db.get(models.Booking, p.booking_id) if p.booking_id else None
        svc = db.get(models.Service, b.service_id) if b else None
        what = (f"{svc.name if svc else 'treatment'}, {b.slot_at:%d/%m %H:%M}" if b
                else "a payment")
        from app.services.slips import amounts_match
        if p.slip_amount is not None and not amounts_match(p.slip_amount, p.amount):
            lines.append(f"- {what} — the customer SENT A TRANSFER SLIP, but the amount on it "
                         f"(฿{p.slip_amount:,.2f}) does NOT match the ฿{p.amount:,.2f} due, and "
                         "they have been told an admin will contact them. Do NOT say the "
                         "payment is received or the booking confirmed, do not send another "
                         "payment QR and do not settle the difference yourself: if they ask, "
                         "say the admin will contact them shortly to check it.")
            continue
        lines.append(f"- {what} — the customer SENT A TRANSFER SLIP and the clinic team is "
                     "checking it; the slot stays held meanwhile. Do NOT ask them to pay "
                     "again and do NOT say the payment is received or the booking confirmed: "
                     "if they ask, say the team is checking and will tell them shortly.")
    if not lines:
        return ""
    return ("\nHOLD ON AN UNPAID BOOKING — held only until the time shown, not confirmed:\n"
            + "\n".join(lines)
            + "\nIf you mention one of these bookings at all, say it is HELD, state how long "
              "is left and what has to be paid. Never call it confirmed, secured or complete "
              "while it is unpaid. Use the minutes on this line, not a number from an earlier "
              "message: they change every turn.")


def _bookings_elsewhere_hint(db, conversation, customer, current) -> str:
    """Bookings this customer already holds at a DIFFERENT branch from this chat's.

    A customer booked and PAID for HIFU at South Aurora, then asked about a treatment
    South does not offer; the assistant moved the conversation to Central and carried on
    quoting Central's prices. The paid booking does not move with the conversation, and
    the same treatment is dearer at Central — so the figures on screen no longer matched
    the appointment they had bought, and nobody said so. Two branches also cannot be
    attended at one time, which the assistant offered outright.
    """
    if not (customer and current):
        return ""
    from app.services.booking import resolved_price
    from app.services.billing import _paid_total_for_booking

    lines = []
    for b in (scoped(db, models.Booking, conversation.clinic_id)
              .filter(models.Booking.customer_id == customer.id,
                      models.Booking.status.in_(["pending", "confirmed"]),
                      models.Booking.branch_id.isnot(None),
                      models.Booking.branch_id != current.id)
              .order_by(models.Booking.slot_at).all()):
        svc = db.get(models.Service, b.service_id)
        br = db.get(models.Branch, b.branch_id)
        if not (svc and br):
            continue
        paid = _paid_total_for_booking(db, b)
        here = resolved_price(db, conversation.clinic_id, svc, current.id)
        gap = ""
        if here and int(here) != int(b.price or 0):
            gap = (f" That treatment costs ฿{int(here):,} at {current.name}, NOT the "
                   f"฿{int(b.price or 0):,} they are booked and billed at — say so before "
                   "they assume the price they paid follows them.")
        lines.append(
            f"- {svc.name} at {br.name}, {b.slot_at:%d/%m %H:%M}, ฿{int(b.price or 0):,} "
            f"(paid so far ฿{int(paid):,}). It stays at {br.name}: choosing a branch in "
            f"this chat does NOT move it.{gap}")
    out = ""
    if lines:
        out = ("\nBOOKINGS AT ANOTHER BRANCH — the customer already holds these, and this chat "
               f"is now on {current.name}:\n" + "\n".join(lines)
               + "\nTell them plainly rather than letting them find out later, and never offer a "
                 "time that clashes with one of these: they cannot be at two branches at once.")
    return out + _same_branch_queue_hint(db, conversation, customer, current)


def _same_branch_queue_hint(db, conversation, customer, current) -> str:
    """When they already have an appointment HERE, adding another is a queue.

    "ขอทำ Acne Clear ต่อเลยได้ไหมคะ" should be answered with a time — their first
    treatment ends at 10:40, so the next one starts at 11:00 — not with "which day
    would you like?", and certainly not by handing the whole thing to a human, which
    is what happened when the booking tool refused the clashing slot without saying
    the clash was their own appointment.
    """
    from app.services.booking import _duration_of, _now_local, available_slots

    lines = []
    for b in (scoped(db, models.Booking, conversation.clinic_id)
              .filter(models.Booking.customer_id == customer.id,
                      models.Booking.branch_id == current.id,
                      models.Booking.status.in_(["pending", "confirmed"]),
                      models.Booking.slot_at >= _now_local())
              .order_by(models.Booking.slot_at).all()[:3]):
        svc = db.get(models.Service, b.service_id)
        ends = b.slot_at + timedelta(minutes=_duration_of(db, b))
        free = [s for s in available_slots(db, current.id, b.slot_at) if s >= ends]
        lines.append(
            f"- {svc.name if svc else 'a treatment'} on {b.slot_at:%d/%m} at "
            f"{b.slot_at:%H:%M}, finishing {ends:%H:%M}"
            + (f". The first time a treatment can START after it is {free[0]:%H:%M}"
               if free else ". Nothing is free after it that day"))
    if not lines:
        return ""
    return ("\nTHEIR APPOINTMENTS AT THIS BRANCH:\n" + "\n".join(lines)
            + "\nIf they ask to add a treatment straight after one of these ('ต่อเลย', 'ต่อจาก"
              "คิวเดิม', 'right after'), do NOT ask which day: say when that treatment finishes "
              "and offer the first time the new one can start, for them to confirm. Check the "
              "new treatment's own length against that time before you promise it. A different "
              "day is a normal booking - ask as usual.")


_SIGNUP_WORDS_RE = re.compile(r"สมัครสมาชิก|เข้าสู่ระบบ|sign[ -]?up|sign[ -]?in|log[ -]?in", re.I)


def _shows_signup(conversation, customer, text: str, refused: bool) -> bool:
    """Whether the widget puts the sign-up button under this reply. Read off the
    tool result when there is one; otherwise off the reply itself, because the hint
    has the model send a visitor to sign up without calling book_appointment at all."""
    from app.ai.tools import booking_requires_signup
    if not booking_requires_signup(conversation, customer):
        return False
    return refused or bool(_SIGNUP_WORDS_RE.search(text or ""))


def _signup_hint(conversation, customer) -> str:
    """Members-only booking, stated before the checklist so the model never walks an
    anonymous visitor through branch/treatment/time/name/phone only for
    book_appointment to refuse at the end."""
    from app.ai.tools import SIGNUP_SAY_EN, SIGNUP_SAY_TH, booking_requires_signup
    if not booking_requires_signup(conversation, customer):
        return ""
    return ("MEMBERS-ONLY BOOKING (overrides the BOOKING CHECKLIST below): this visitor is NOT "
            "signed in, and booking on the website is for members only. Answer every question "
            "about treatments, prices, promotions, branches, hours and free slots as usual. But "
            "the moment they want to book or reserve, do not run the checklist, do not ask for "
            "their name or phone and do not call book_appointment: tell them booking needs a "
            f"member account, in these words: \"{SIGNUP_SAY_TH}\" (English chat: "
            f"\"{SIGNUP_SAY_EN}\"). The widget shows the sign-up button under that reply.\n")


def _identity_hint(db, conversation, customer) -> str:
    """Whose record the customer is talking about — stated, not inferred.

    The unverifiable-identity HARD RULE exists for a returning customer writing from a
    NEW account and claiming a booking the clinic cannot see is theirs. Its trigger,
    though, reads as "the customer typed a name and a phone number" — so it also fired
    on someone correcting their OWN details mid-booking ("บอกเบอร์ผิดค่ะ 08... ชื่อ..."),
    and the assistant stopped selling and handed off instead of just saving the fix.
    Nothing in the transcript separates the two cases, but the DB does: a booking on
    THIS customer_id is theirs by construction.
    """
    if not customer:
        return ""
    own = (scoped(db, models.Booking, conversation.clinic_id)
           .filter(models.Booking.customer_id == customer.id,
                   models.Booking.status.in_(["pending", "confirmed"])).count())
    here = (scoped(db, models.Booking, conversation.clinic_id)
            .filter(models.Booking.conversation_id == conversation.id).count())
    if own or here:
        return ("IDENTITY: the booking(s) in CUSTOMER MEMORY are on THIS account"
                + (" and were made in this very chat" if here else "")
                + ". Nothing here is an unverified claim about someone else's booking, so "
                  "the unverifiable-identity HARD RULE does NOT apply. When this customer "
                  "corrects their own name or phone, that is a routine fix to their own "
                  "record: save it, confirm the corrected value once, and carry straight on "
                  "with the booking and the payment. Do not hand off, and do not tell them "
                  "the team will check their details.\n"
                  "A booking always shows this customer's CURRENT name and phone — it holds "
                  "no separate copy — so the correction has already reached it the moment "
                  "they told you. There is nothing for a human to update, so never say the "
                  "team will amend the booking, and never call request_human_help for a "
                  "changed name or phone number.")
    return ("IDENTITY: this account has NO booking on file. If the customer refers to an "
            "appointment, a deposit or a past visit, it is not on this record and you cannot "
            "verify it is theirs — apply the unverifiable-identity HARD RULE. Giving you a "
            "name or a phone number is NOT such a claim on its own: someone simply telling "
            "you their details, or correcting them, is normal and you carry on as usual.")


# How much of the thread the model sees. A flat 18-message window used to cut the
# start of any real chat: 16 customer turns = 32 messages, so the treatment and
# branch agreed at the beginning scrolled out and the assistant asked for them
# again ("ถามวนไปวนมา"). Budget by size instead of count, so short Thai turns —
# the common case — keep the whole conversation in view.
HISTORY_MAX_MESSAGES = 80
HISTORY_CHAR_BUDGET = 24000      # ~6-8k tokens of Thai; the model's window is far larger
HISTORY_MIN_MESSAGES = 18        # never show less than the old window


def _recent(convo: list) -> list:
    """The tail of the conversation that fits the budget (oldest trimmed first)."""
    kept = convo[-HISTORY_MAX_MESSAGES:]
    total = sum(len(m.text or "") for m in kept)
    while len(kept) > HISTORY_MIN_MESSAGES and total > HISTORY_CHAR_BUDGET:
        total -= len(kept[0].text or "")
        kept = kept[1:]
    return kept


def _image_part(url: str):
    """An OpenAI ``image_url`` content part for a stored chat photo, or None.

    Only files under CHAT_UPLOAD_DIR are ever read (the path comes from our own
    message meta, but a path is still resolved and checked, never trusted)."""
    import base64
    from app.avatars import CHAT_UPLOAD_DIR
    try:
        path = (CHAT_UPLOAD_DIR / Path(str(url)).name).resolve()
        if CHAT_UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
            return None
        mime = {"png": "image/png", "webp": "image/webp"}.get(path.suffix[1:].lower(), "image/jpeg")
        b64 = base64.b64encode(path.read_bytes()).decode()
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    except Exception:
        return None


def respond(db, conversation, on_token=None) -> dict:
    """Generate the AI reply, streaming tokens to ``on_token`` as they arrive.

    ``on_token`` receives the full accumulated text so far. Returns {'text', 'meta'}.
    """
    customer = db.get(models.Customer, conversation.customer_id)
    msgs = (scoped(db, models.Message, conversation.clinic_id)
            .filter_by(conversation_id=conversation.id)
            .order_by(models.Message.created_at).all())
    last_customer = next((m for m in reversed(msgs) if m.sender == "customer"), None)
    query = last_customer.text if last_customer else ""

    # What the customer asked for, and the branches that can actually serve it. Resolved
    # ONCE here and handed to everything that needs it (the catalog block, the booking
    # checklist), because two places deriving the same fact is how they end up
    # disagreeing — and the one that disagrees is the one the model happens to read.
    from app.ai.tools import branches_offering, treatments_named_by_customer
    asked = treatments_named_by_customer(db, conversation)
    allowed_branches = branches_offering(db, conversation.clinic_id, asked)

    # Hybrid context: the COMPLETE structured catalog (branches/treatments/promotions/
    # doctors) every time, plus KB articles (all while small, else RAG). Nothing is
    # silently dropped the way similarity top-k could.
    kb_context, kb_sources = build_context(db, conversation.clinic_id,
                                           conversation.branch_id, query,
                                           asked_names=[s.name for s in asked],
                                           allowed_branch_ids=allowed_branches)

    if not is_configured():
        return {"text": FALLBACK_TH, "meta": {"grounded": True, "kb": [], "tools": []}}

    bkk_now = datetime.utcnow() + timedelta(hours=7)  # clinic timezone (Asia/Bangkok, UTC+7)
    # Which treatments were ALREADY presented in this chat — the model is unreliable at
    # remembering this, so for "what else?" we tell it exactly which ones are still new.
    svc_names = sorted([s.name for s in scoped(db, models.Service, conversation.clinic_id)
                        .filter_by(active=True).all()], key=len, reverse=True)
    shown_blob = " ".join(m.text or "" for m in msgs if m.sender in ("ai", "admin"))
    shown, _work = [], shown_blob
    for _n in svc_names:                       # longest first, consume to avoid substring matches
        if _n and _n in _work:
            shown.append(_n)
            _work = _work.replace(_n, " ")
    not_shown = [n for n in svc_names if n not in shown]
    menu_hint = ""
    if shown and not_shown:
        menu_hint = (f"Treatments ALREADY presented to this customer in this chat: {', '.join(shown)}. "
                     f"Treatments NOT yet presented: {', '.join(not_shown)} — if they ask for other / "
                     "more options, show THESE, never the ones already presented.\n")
    elif shown and not not_shown:
        menu_hint = ("You have already presented the whole treatment menu to this customer; if they ask "
                     "for more, say that is the full menu and help them choose.\n")
    clinic = db.get(models.Clinic, conversation.clinic_id)
    memory_block = (f"{customer_memory(db, customer)}\n{workflow_state(conversation, db)}\n"
                    f"{past_conversations(db, customer, conversation.id)}")
    # The clinic's own Latin words: they decide the reply language AND which trailing
    # Latin word is a real name rather than glitch text, so read them once.
    name_words = clinic_name_words(db, conversation.clinic_id)
    system = build_system_prompt(
        kb_context, clinic=clinic,
        now_line=f"{bkk_now:%A %d %B %Y, %H:%M}",
        memory_block=memory_block, menu_hint=menu_hint,
        booking_hint=(_signup_hint(conversation, customer)
                      + _booking_hint(db, conversation, customer, asked, allowed_branches) + "\n"
                      + _identity_hint(db, conversation, customer)),
        language_line=_language_directive(msgs, name_words),
        custom_instructions=getattr(clinic, "ai_instructions", "") or "")

    # Full recent context — INCLUDING any messages a human admin wrote during a
    # takeover (treated as the assistant's own turns) so the AI resumes with the
    # thread intact. Drop system notices first so they don't eat the window.
    convo = [m for m in msgs if m.sender != "system"]
    history = []
    # Only the NEWEST customer photo is sent to the model: older ones stay in the
    # transcript as their caption, so a long chat does not re-pay for every image.
    last_photo = next((m.id for m in reversed(convo)
                       if m.sender == "customer" and (m.meta or {}).get("image")), None)
    for m in _recent(convo):
        if m.sender == "customer":
            part = _image_part(m.meta["image"]) if m.id == last_photo and (m.meta or {}).get("image") else None
            sent_photo = bool((m.meta or {}).get("image"))
            history.append({"role": "user", "content": (
                [{"type": "text", "text": m.text}, part] if part
                else (f"{m.text} (the customer sent a photo here)" if sent_photo else m.text))})
        elif m.sender == "admin":
            # Mark human-teammate turns so the AI knows a real colleague (not itself)
            # wrote them and must honour what they told the customer.
            history.append({"role": "assistant",
                            "content": f"(human teammate replied to the customer) {m.text}"})
        else:  # ai
            history.append({"role": "assistant", "content": m.text})
    if not history:
        history = [{"role": "user", "content": query or "สวัสดีค่ะ"}]

    messages = [{"role": "system", "content": system}] + history
    # A human teammate's messages are authoritative context the AI may quote (e.g. a
    # promo price they offered), so the grounding guard accepts those numbers too.
    # kb_context is BRANCH-scoped, so once the customer picks a branch the clinic's
    # standard starting prices vanish from it — yet the pricing rules require the AI to
    # restate one when explaining why a branch price differs ("9,500 is our standard
    # price, South Aurora's is 9,000"). Without the catalog figures here the guard flags
    # that correct answer as an unsupported number, training admins to ignore the flag.
    catalog_prices = " ".join(
        f"{s.base_price} {deposit_for(s, float(s.base_price or 0))}"
        for s in scoped(db, models.Service, conversation.clinic_id).filter_by(active=True).all()
        if s.base_price)
    grounding = (kb_context + " " + catalog_prices + " "
                 + " ".join(m.text for m in convo if m.sender == "admin")
                 + " " + _contact_grounding(convo, customer)).strip()
    used_tools: list[str] = []
    payment_meta: dict | None = None
    signup_asked = False   # book_appointment refused this visitor: members only
    text = ""
    usage_prompt = usage_completion = 0  # accumulate token usage across tool-loop turns

    try:
        for _ in range(MAX_TOOL_LOOPS):
            stream = chat_completion(messages, tools=TOOLS, temperature=0.5,
                                     max_tokens=620, stream=True)
            content = ""
            tool_calls: dict[int, dict] = {}
            for chunk in stream:
                if getattr(chunk, "usage", None):  # final chunk reports token usage
                    usage_prompt += chunk.usage.prompt_tokens or 0
                    usage_completion += chunk.usage.completion_tokens or 0
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    content += delta.content
                    if on_token:
                        try:
                            on_token(_no_emdash(content))
                        except Exception:
                            pass
                for tc in (getattr(delta, "tool_calls", None) or []):
                    slot = tool_calls.setdefault(
                        tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments

            if tool_calls:
                calls = list(tool_calls.values())
                messages.append({
                    "role": "assistant", "content": content or "",
                    "tool_calls": [
                        {"id": c["id"], "type": "function",
                         "function": {"name": c["name"], "arguments": c["arguments"]}}
                        for c in calls],
                })
                for c in calls:
                    used_tools.append(c["name"])
                    try:
                        args = json.loads(c["arguments"] or "{}")
                    except Exception:
                        args = {}
                    result = execute_tool(db, conversation, customer, c["name"], args)
                    if isinstance(result, dict) and result.get("need_signup"):
                        signup_asked = True
                    if (c["name"] in ("create_payment_link", "book_appointment")
                            and isinstance(result, dict) and result.get("payment_qr")):
                        # The widget renders the transfer QR under the reply. `url` carries
                        # it so every reader that keys off payment.url (msg_dict, the paid
                        # flip, channel delivery) works unchanged; the hold deadline drives
                        # the card's live countdown.
                        payment_meta = {
                            "url": result["payment_qr"], "kind": "qr",
                            "amount": result.get("amount_value"),
                            "label": result.get("label", "ชำระเงิน"),
                            "payment_id": result.get("payment_id"),
                            "hold_expires_at": result.get("hold_expires_at"),
                        }
                    grounding += " " + json.dumps(result, ensure_ascii=False)
                    messages.append({"role": "tool", "tool_call_id": c["id"],
                                     "content": json.dumps(result, ensure_ascii=False)})
                continue

            said_by_customer = " ".join(m.text or "" for m in convo
                                        if m.sender == "customer")
            crm_names = " ".join(filter(None, [getattr(customer, "name", None),
                                               getattr(customer, "nickname", None)]))
            cleaned = _drop_unbacked_cjk(
                _drop_alien_scripts(_drop_invisible(_no_emdash(content.strip())),
                                    said_by_customer),
                said_by_customer, crm_names)
            text = _drop_trailing_gibberish(cleaned, name_words, said_by_customer, grounding)
            fixed = _correct_branch_list(db, conversation, text)
            if fixed != text and on_token:
                on_token(fixed)   # end the stream on the corrected list, not the wrong one
            text = fixed
            break
    except Exception as exc:  # pragma: no cover
        print("[ai] orchestrator error:", exc)
        usage.record(conversation.clinic_id, "chat", settings.chat_model, usage_prompt, usage_completion)
        return {"text": FALLBACK_TH, "meta": {"grounded": True, "kb": [], "tools": []}}

    if not text:
        text = FALLBACK_TH
    usage.record(conversation.clinic_id, "chat", settings.chat_model, usage_prompt, usage_completion)
    grounding_check = guard.check(text, grounding)
    from app.ai import guardrails
    payment_unverified = not guardrails.payment_claim_ok(db, conversation, customer, text)
    customer_said = " ".join(m.text for m in convo if m.sender == "customer")
    discount_flags = guardrails.undercuts_catalog(text, grounding, customer_said)
    offer_flags = guardrails.unbacked_offers(text, grounding, customer_said)
    # Persisted verbatim so a flagged reply (or any reply) can be debugged later: exactly
    # what the model had in front of it (KB context, catalog prices, admin messages, every
    # tool result) — not just the "Knowledge Base"/"Booking" source LABELS `kb`/`tools`
    # already carry. Tail-kept, not head-kept: tool results (the specific evidence for a
    # specific claim) are appended LAST, so a head-preserving cut would silently drop
    # exactly the evidence a reviewer needs most from exactly the multi-tool-call turns
    # most likely to approach the cap. Marked visibly when actually truncated, so a partial
    # trail is never mistaken for the complete picture.
    grounding_trail = grounding if len(grounding) <= GROUNDING_TRAIL_MAX_CHARS else (
        "…[earlier grounding trail truncated]… " + grounding[-GROUNDING_TRAIL_MAX_CHARS:])
    return {"text": text, "meta": {
        "grounded": grounding_check["grounded"],
        "unsupported": grounding_check["unsupported"],
        "payment_unverified": payment_unverified,
        "discount_flags": discount_flags,
        "offer_flags": offer_flags,
        "tools": used_tools,
        "kb": kb_sources,
        "payment": payment_meta,
        "signup": _shows_signup(conversation, customer, text, signup_asked),
        "prompt_version": PROMPT_VERSION,
        "grounding": grounding_trail,
    }}
