"""AI tool definitions and execution for the chat orchestrator.

Every tool runs within the conversation's clinic — the AI can only ever see or
act on its own clinic's catalog, availability and bookings.
"""
import re
from datetime import datetime, timedelta

from app import models, realtime
from app.ai import rag
from app.ai.prompts import ACK_EN, ACK_TH
from app.scope import scoped
from app.services.booking import (BOOKED_OR_PAST, CLOSED, EXPIRED, FULLY_BOOKED,
                                  HOLD_MINUTES, PAST, SLOT_TAKEN, available_slots,
                                  claim_slot, create_booking, day_availability,
                                  deposit_for, next_available, resolved_hold_minutes,
                                  _now_local)
from app.services.promotions import (exhausted_promo_ids, promo_branch_ids,
                                     promo_date_ok, promo_runs_at)
from app.services.emailer import send_booking_email_async

# horizon for "next available" scans — far enough that a next-month request is reachable
NEXT_AVAILABLE_DAYS = 45

# Booking on the website is for members. The anonymous widget (home page, /chat/<slug>)
# still answers questions, but a slot is only taken by a customer signed in through the
# portal, whose chat runs on their own record (portal.py::my_chat). Read off the record,
# not the conversation, because the portal and the anonymous widget share channel "web".
SIGNUP_PATH = "/portal?tab=register&next=book"
SIGNUP_SAY_TH = ("การจองคิวผ่านเว็บไซต์เปิดให้เฉพาะสมาชิกค่ะ รบกวนสมัครสมาชิกหรือเข้าสู่ระบบก่อนนะคะ "
                 "(กดปุ่มด้านล่างได้เลยค่ะ) จากนั้นคุยกับผู้ช่วยต่อในหน้าบัญชีของคุณเพื่อจองคิวได้ทันทีค่ะ")
SIGNUP_SAY_EN = ("Booking on our website is for members. Please sign up or sign in first "
                 "(tap the button below), then carry on chatting from your account to book "
                 "straight away.")


def booking_requires_signup(conversation, customer) -> bool:
    """True for an anonymous web-chat visitor: no portal password on their record."""
    if not conversation or conversation.channel != "web":
        return False
    return not (customer and customer.password_hash)


def signup_required_result() -> dict:
    return {"booked": False, "need_signup": True, "signup_path": SIGNUP_PATH,
            "say_it_like": SIGNUP_SAY_TH, "say_it_like_en": SIGNUP_SAY_EN,
            "note": "This visitor is not signed in, and bookings on the website are for "
                    "members only. Nothing was booked and no slot is held. Tell them so with "
                    "say_it_like (or say_it_like_en for an English chat); the widget shows "
                    "the sign-up button under your reply. Do not collect their name or "
                    "phone, do not send a payment QR, and do not call book_appointment "
                    "again in this chat. Keep answering their questions as usual."}

# Shared by every tool that takes a `branch`: the model must show its work, quoting what
# the customer actually typed. A branch nobody in the transcript named is discarded
# (execute_tool -> _branch_said_by_customer), so the AI cannot silently pick one.
_BRANCH_SAID = {
    "type": "string",
    "description": "The CUSTOMER's own words naming that branch, copied verbatim from their "
                   "message (e.g. \"ทองหล่อ\", \"สาขาสยาม\", \"Phuket\"). Pass this whenever you "
                   "pass 'branch' — a branch the customer never named is ignored.",
}

TOOLS = [
    {"type": "function", "function": {
        "name": "search_knowledge_base",
        "description": "Search the clinic knowledge base for facts about treatments, "
                       "prices, promotions, preparation, aftercare and policies. Use this "
                       "whenever the customer asks something factual.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look up"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "list_treatments",
        "description": "List the clinic's treatments with their starting prices. If the clinic "
                       "has more than one branch and the customer already said which one, pass "
                       "it here to get that branch's exact price instead of the standard price.",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string", "description": "Optional category filter"},
            "branch": {"type": "string",
                       "description": "Which branch the customer wants (pass this once known — "
                                      "prices can differ per branch)"},
            "branch_said": _BRANCH_SAID}}}},
    {"type": "function", "function": {
        "name": "list_promotions",
        "description": "List the clinic's current active promotions. If the clinic has more than "
                       "one branch and the customer already said which one, pass it here so "
                       "branch-specific promotions and prices are exact.",
        "parameters": {"type": "object", "properties": {
            "branch": {"type": "string",
                       "description": "Which branch the customer wants (pass this once known — "
                                      "promotions and prices can differ per branch)"},
            "branch_said": _BRANCH_SAID}}}},
    {"type": "function", "function": {
        "name": "check_availability",
        "description": "Check available appointment time slots for the clinic. If the clinic has "
                       "more than one branch, ASK which branch first and pass it here.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string",
                     "description": "Optional preferred date YYYY-MM-DD; omit for next available"},
            "time": {"type": "string",
                     "description": "The time the customer asked for, HH:MM, if they named one. "
                                    "Pass it so the answer can tell them whether the branch is "
                                    "even open at that hour."},
            "branch": {"type": "string",
                       "description": "Which branch the customer wants (required when the clinic "
                                      "has more than one branch)"},
            "branch_said": _BRANCH_SAID,
            "doctor": {"type": "string",
                       "description": "Optional doctor name when the customer wants a specific "
                                      "doctor — only their free times are returned"}}}}},
    {"type": "function", "function": {
        "name": "book_appointment",
        "description": "Book an appointment once the customer has chosen a treatment and a time "
                       "slot, given their name and phone number, AND you have summarised the "
                       "name, phone, treatment, branch, date, time, price and deposit and the "
                       "customer told you whether to pay the deposit or the full amount. In a "
                       "multi-branch clinic, you must already know which branch.",
        "parameters": {"type": "object", "properties": {
            "treatment": {"type": "string", "description": "Treatment name"},
            "date": {"type": "string", "description": "Date YYYY-MM-DD"},
            "time": {"type": "string", "description": "Time HH:MM (24-hour)"},
            "branch": {"type": "string",
                       "description": "Which branch the customer wants (required when the clinic "
                                      "has more than one branch)"},
            "branch_said": _BRANCH_SAID,
            "customer_name": {"type": "string",
                              "description": "The name the customer gave for this booking, "
                                             "exactly as they typed it"},
            "phone": {"type": "string",
                      "description": "The phone number the customer gave for this booking"},
            "no_phone_said": {"type": "string",
                              "description": "Only when you ASKED for a phone number and the "
                                             "customer explicitly said they have none — their own "
                                             "words, copied verbatim (e.g. \"ไม่มีเบอร์ค่ะ\"). Leave "
                                             "empty otherwise; a decline nobody actually said is "
                                             "ignored and phone number is still required."},
            "doctor": {"type": "string",
                       "description": "Optional doctor name when the customer asked for a "
                                      "specific doctor"},
            "payment_type": {"type": "string", "enum": ["deposit", "full"],
                             "description": "What the customer ANSWERED after you summarised the "
                                            "booking: 'full' to pay the whole price now, 'deposit' "
                                            "to pay just the deposit now. Required — never guess "
                                            "it; if the customer has not answered that question "
                                            "yet, send the summary and ask, do not call this "
                                            "tool."},
            "payment_said": {"type": "string",
                             "description": "The CUSTOMER's own words choosing how to pay, "
                                            "copied verbatim from their message (e.g. "
                                            "\"มัดจำค่ะ\", \"เต็มจำนวน\", \"full\"). An answer "
                                            "nobody in the transcript gave is ignored and the "
                                            "booking is refused."}},
            "required": ["treatment", "date", "time", "payment_type", "payment_said"]}}},
    {"type": "function", "function": {
        "name": "reschedule_appointment",
        "description": "Move the customer's existing upcoming booking to a different date/time. "
                       "Only allowed when the appointment is still MORE than 24 hours away; if it "
                       "is within 24 hours it cannot be moved here and must go to a human. The "
                       "deposit carries over, so no new payment is needed.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "New date YYYY-MM-DD"},
            "time": {"type": "string", "description": "New time HH:MM (24-hour)"},
            "treatment": {"type": "string",
                          "description": "Which booking to move, if the customer has more than "
                                         "one upcoming booking"}},
            "required": ["date", "time"]}}},
    {"type": "function", "function": {
        "name": "create_payment_link",
        "description": "Show the clinic's payment QR (bank transfer / PromptPay) for one of "
                       "the customer's bookings, outside the normal booking flow — e.g. to "
                       "re-send it, or to "
                       "collect the remaining balance after a deposit. Call this ONLY after you "
                       "have told the customer the exact amount due (deposit, full price, or "
                       "remaining balance — from CUSTOMER MEMORY, never your own calculation) and "
                       "they have confirmed they want to pay it now. The QR is shown to the "
                       "customer under your reply.",
        "parameters": {"type": "object", "properties": {
            "type": {"type": "string", "enum": ["deposit", "full"],
                     "description": "Which payment to collect: 'full' for the whole price, "
                                    "'deposit' (default) for just the deposit. Match whatever "
                                    "the customer already chose for this booking."},
            "treatment": {"type": "string",
                          "description": "Which booking to collect for, by treatment name. "
                                         "REQUIRED when the customer has more than one live "
                                         "booking — without it the tool refuses rather than "
                                         "guessing, because quoting one booking's balance "
                                         "against another tells them a bill is settled when "
                                         "it is not."}}}}},
    {"type": "function", "function": {
        "name": "request_human_help",
        "description": "Hand the conversation to a human admin. Use for medical concerns, "
                       "complaints, or when the customer explicitly asks for a person.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}}, "required": ["reason"]}}},
]


def _service_branch_ids(db, clinic_id: int) -> dict[int, set[int]]:
    """Every service's restricted-branch set, keyed by service id (mirrors
    catalog.py::_branch_ids_by_service). No entry / an empty set = every branch."""
    out: dict[int, set[int]] = {}
    for row in scoped(db, models.ServiceBranch, clinic_id).all():
        out.setdefault(row.service_id, set()).add(row.branch_id)
    return out


def _find_service(db, name: str, clinic_id: int, branch_id: int | None = None):
    name_l = (name or "").lower().strip()
    services = scoped(db, models.Service, clinic_id).filter_by(active=True).all()
    if branch_id:
        # Different branches may now share a treatment name — prefer the customer's
        # own branch (or an unrestricted one) over a same-named treatment offered
        # only at other branches.
        branch_map = _service_branch_ids(db, clinic_id)
        in_scope = [s for s in services
                   if not branch_map.get(s.id) or branch_id in branch_map[s.id]]
        if in_scope:
            services = in_scope
    for s in services:
        if s.name.lower() == name_l:
            return s
    for s in services:
        if name_l and (name_l in s.name.lower() or s.name.lower() in name_l):
            return s
    words = set(name_l.split())
    best, best_score = None, 0
    for s in services:
        overlap = len(words & set(s.name.lower().replace("—", " ").split()))
        if overlap > best_score:
            best, best_score = s, overlap
    return best


def _resolve_branch(db, clinic_id: int, name_str):
    """Match a branch by the name the AI passes when the customer picks one.

    An exact (case-insensitive) match always wins and is checked across every
    branch FIRST — otherwise, with more branches the odds rise that one branch's
    name is a plain substring of another's (e.g. "Silom" inside "Central Silom"),
    and returning on the first substring hit would silently lock the customer
    onto the wrong branch (wrong price, wrong slots, wrong booking). Only when
    there's no exact match do we fall back to substring matching, preferring the
    longest (most specific) branch name among the candidates."""
    n = (name_str or "").strip().lower()
    if not n:
        return None
    all_branches = scoped(db, models.Branch, clinic_id).all()
    for b in all_branches:
        if (b.name or "").strip().lower() == n:
            return b
    best, best_len = None, -1
    for b in all_branches:
        bn = (b.name or "").lower()
        if bn and (n in bn or bn in n) and len(bn) > best_len:
            best, best_len = b, len(bn)
    return best


def _resolve_doctor(db, clinic_id: int, name_str):
    """Match a doctor on the clinic's StaffMember roster by (partial) name —
    'หมอแพร' / 'Dr. Pear' should both find 'พญ. แพรวา …'."""
    n = (name_str or "").strip().lower()
    for prefix in ("dr.", "dr ", "หมอ", "คุณหมอ", "พญ.", "นพ."):
        if n.startswith(prefix):
            n = n[len(prefix):].strip()
    if not n:
        return None
    members = (scoped(db, models.StaffMember, clinic_id)
               .filter_by(active=True).all())
    for m in members:
        mn = (m.name or "").lower()
        if mn and (n == mn or n in mn or mn in n):
            return m
    words = set(n.split())
    best, best_score = None, 0
    for m in members:
        overlap = len(words & set((m.name or "").lower().split()))
        if overlap > best_score:
            best, best_score = m, overlap
    return best


_BRANCH_STOPWORDS = {"clinic", "branch", "the", "and", "สาขา", "คลินิก"}


def _branch_said_by_customer(db, conversation, branch, quote: str | None) -> bool:
    """Did the CUSTOMER actually name this branch, or did the model pick it?

    Same defence-in-depth as ``sales.analyze`` uses for names: a value the model claims
    came from the customer is only accepted when it really appears in the customer's own
    messages. Two ways to corroborate, because the customer may answer in Thai while the
    branch is named in English ("ทองหล่อ" -> "Thonglor Clinic"):
      - ``quote`` (branch_said): the words the model says they used, matched verbatim;
      - the branch's own distinctive name words, for customers who type the name itself.
    """
    said = " ".join(m.text or "" for m in
                    scoped(db, models.Message, conversation.clinic_id)
                    .filter_by(conversation_id=conversation.id, sender="customer").all()).lower()
    if not said:
        return False
    q = (quote or "").strip().lower()
    if q and q in said:
        return True
    words = [w for w in (branch.name or "").lower().replace("-", " ").split()
             if w not in _BRANCH_STOPWORDS and len(w) > 2]
    return any(w in said for w in words)


# Words that settle the deposit-or-full question. Deliberately specific: a bare "เต็ม"
# also matches "คิวเต็มไหมคะ", and "มัดจำ" on its own matches "มัดจำเท่าไหร่คะ" — neither
# is the customer CHOOSING, which is why the scan below only reads messages sent after
# the clinic actually put both options to them.
_DEPOSIT_WORDS = ("มัดจำ", "มัดจํา", "deposit")
_FULL_WORDS = ("เต็มจำนวน", "เต็มจํานวน", "จ่ายเต็ม", "ชำระเต็ม", "ชําระเต็ม",
               "เต็มก่อน", "full amount", "pay in full", "in full")


def _levenshtein(a: str, b: str) -> int:
    """Edit distance (insert/delete/substitute) between two short strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def _typo_tolerant_contains(text: str, word: str, max_dist: int = 1) -> bool:
    """True if ``word`` appears in ``text`` verbatim, or as a substring one keystroke
    away (one inserted/dropped/swapped character) — a real customer reply, caught live:
    "มัดเจำ" (a transposed ตัวอักษร) for "มัดจำ" matched none of the exact keywords, so
    the tool kept reporting "no payment choice yet" to a customer who had just answered
    it, and the model — asked once, answered once, told it still wasn't answered —
    improvised a "the system is having trouble" excuse rather than the actual state.

    A sliding window, not a split-on-whitespace check: Thai does not reliably space-
    delimit words the way "ขอมัดเจำนะคะ" shows (no space at all around the typo), so the
    word boundary has to be discovered by scanning, not assumed. Distance capped at 1 —
    wide enough for a single slipped keystroke, narrow enough that unrelated short words
    do not collide with a 4-5 character keyword by chance.
    """
    if not word:
        return False
    if word in text:
        return True
    n = len(word)
    for length in range(max(1, n - max_dist), n + max_dist + 1):
        for i in range(0, len(text) - length + 1):
            if _levenshtein(text[i:i + length], word) <= max_dist:
                return True
    return False


def _payment_choice_by_customer(db, conversation, payment_type: str, quote: str = "") -> bool:
    """True when the CUSTOMER really answered the deposit-or-full question.

    ``payment_type`` being a required argument was supposed to be the checkpoint, but
    the model can satisfy a required argument by simply filling it in — and it did:
    a customer sent nothing but their phone number and got back a confirmed booking
    and a payment link, never having been asked how they wanted to pay. So the answer
    has to be visible in the transcript, the same way a branch must be (see
    ``_branch_said_by_customer``): the clinic must have PUT both options to them, and
    the customer must have picked one afterwards.
    """
    if not conversation:
        return False
    msgs = (scoped(db, models.Message, conversation.clinic_id)
            .filter_by(conversation_id=conversation.id)
            .order_by(models.Message.created_at, models.Message.id).all())
    asked_at = None
    for i, m in enumerate(msgs):
        if m.sender not in ("ai", "admin"):
            continue
        low = (m.text or "").lower()
        if any(w in low for w in _DEPOSIT_WORDS) and any(w in low for w in _FULL_WORDS):
            asked_at = i                       # the clinic offered both options here
    if asked_at is None:
        return False                           # never asked -> nothing to have answered
    said = " ".join(m.text or "" for m in msgs[asked_at + 1:]
                    if m.sender == "customer").lower()
    if not said:
        return False
    q = (quote or "").strip().lower()
    # Narrow to the quote ONLY when the quote is itself an answer. It exists to settle
    # a transcript containing both words ("ไม่เอาเต็มจำนวน ขอมัดจำ") — but on a retry the
    # model tends to quote the customer's LATEST message, and after a phone correction
    # that message is a phone number. Narrowing to it then deleted the "มัดจำค่ะ" sitting
    # earlier in the same transcript, and a customer who had answered, corrected their
    # number and asked to pay was told the booking could not be made.
    if q and q in said and any(_typo_tolerant_contains(q, w)
                               for w in _DEPOSIT_WORDS + _FULL_WORDS):
        said = q
    # Typo-tolerant on the CUSTOMER's own words only — asked_at above stays an exact
    # match, since the clinic's own text is never misspelled by construction.
    chose_full = any(_typo_tolerant_contains(said, w) for w in _FULL_WORDS)
    chose_deposit = any(_typo_tolerant_contains(said, w) for w in _DEPOSIT_WORDS)
    if chose_full == chose_deposit:            # both or neither -> not a clear answer
        return False
    return (payment_type == "full") == chose_full


# Words that show the clinic actually raised the topic, and words that show the
# customer actually declined it — same ask-then-answer shape as the deposit/full check
# above. A bare "ไม่มี" means nothing on its own (it answers all kinds of questions); it
# only counts as declining a phone number when it follows a message that asked for one.
_PHONE_ASK_WORDS = ("เบอร์", "โทรศัพท์", "phone")
_PHONE_DECLINE_WORDS = ("ไม่มีเบอร์", "ไม่มีโทรศัพท์", "ไม่สะดวกให้เบอร์", "ไม่สะดวกบอกเบอร์",
                       "no phone", "don't have a phone", "dont have a phone", "no number")


def _no_phone_confirmed_by_customer(db, conversation, quote: str = "") -> bool:
    """True only when the clinic actually ASKED for a phone number and the CUSTOMER's own
    reply after that actually declined it — never the model deciding on its own that the
    customer probably has none. Same shape as ``_payment_choice_by_customer``: silence
    (see ``phone_problem``) is a different fact from an explicit decline, and only the
    second one is allowed to skip the field forever.
    """
    if not conversation:
        return False
    msgs = (scoped(db, models.Message, conversation.clinic_id)
            .filter_by(conversation_id=conversation.id)
            .order_by(models.Message.created_at, models.Message.id).all())
    asked_at = None
    for i, m in enumerate(msgs):
        if m.sender not in ("ai", "admin"):
            continue
        if any(w in (m.text or "").lower() for w in _PHONE_ASK_WORDS):
            asked_at = i                       # the clinic raised the topic here
    if asked_at is None:
        return False                           # never asked -> nothing to have declined
    said = " ".join(m.text or "" for m in msgs[asked_at + 1:]
                    if m.sender == "customer").lower()
    if not said:
        return False
    q = (quote or "").strip().lower()
    # Narrow to the quote only when the quote itself is a decline — the same misquote
    # guard _payment_choice_by_customer uses, so a stale quote from an earlier turn
    # can't stand in for one the customer never actually said.
    if q and q in said and any(w in q for w in _PHONE_DECLINE_WORDS):
        said = q
    return any(w in said for w in _PHONE_DECLINE_WORDS)


def _capture_contact(db, customer, name_arg, phone_arg, conversation=None,
                     no_phone_said=None) -> list[str]:
    """Save the name/phone the AI collected for a booking; report what is still missing.

    The booking flow asks for both, so persist them here rather than relying on the
    post-reply CRM extraction (``sales.analyze``) having run yet. Returns the list of
    still-missing fields ([] when the booking may proceed).
    """
    from app.ai.sales import _extract_phone, _is_placeholder_name

    if not customer:
        return []
    changed = False
    given_name = (name_arg or "").strip()
    # Only fill a channel placeholder ("Web Visitor"); a real name already on file stays, and sales.analyze handles nickname moves.
    if given_name and _is_placeholder_name(customer.name):
        customer.name = given_name[:120]
        changed = True
    given_phone = _extract_phone(phone_arg or "")
    if given_phone and given_phone != (customer.phone or ""):
        customer.phone = given_phone
        # A real number just arrived — any earlier "no phone" confirmation no longer
        # applies (e.g. a customer who said they had none, then found their number).
        customer.phone_declined = False
        changed = True
    if changed:
        db.commit()

    missing = []
    if _is_placeholder_name(customer.name):
        missing.append("name")
    if not (customer.phone or "").strip():
        if customer.phone_declined:
            pass                               # already confirmed on an earlier turn
        elif _no_phone_confirmed_by_customer(db, conversation, no_phone_said):
            customer.phone_declined = True
            db.commit()
        else:
            missing.append("phone number")
    return missing


def _phone_rejection(db, conversation, phone_arg: str) -> dict:
    """The reason a phone-shaped answer was not usable, with the sentence to say.

    ``_extract_phone`` returns "" both for "they gave nothing" and for "they gave
    09545626666", so everything downstream treated an eleven-digit number as silence:
    the assistant announced "บันทึกเบอร์ 09545626666 ให้แล้วนะคะ", put it in the booking
    summary, and only at payment time refused — with no reason, leaving the customer to
    ask "อ่าวทำไมอะคะ". The number is checked here and the problem is stated.
    """
    from app.ai.sales import phone_digits, phone_problem, phone_rejection_say_it_like

    blob = phone_arg or ""
    if not phone_problem(blob) and conversation:
        # The model may not have passed it; the customer's own words are the source.
        for m in reversed(scoped(db, models.Message, conversation.clinic_id)
                          .filter_by(conversation_id=conversation.id, sender="customer")
                          .order_by(models.Message.id).all()):
            if phone_problem(m.text or ""):
                blob = m.text or ""
                break
    problem = phone_problem(blob)
    if not problem:
        return {}
    digits = phone_digits(blob)
    say_it_like, say_it_like_en = phone_rejection_say_it_like(problem, digits)
    if problem == "invalid_prefix":
        phone_note = ("The number they gave does not match a real Thai mobile number (it may be "
                      "a landline, or simply not a real number), so the clinic system did not "
                      "store it. Say EXACTLY say_it_like, word for word, in their language: they "
                      "cannot fix a problem nobody named. NEVER tell them the number was saved, "
                      "never repeat it in a booking summary as if it were on file, and never "
                      "give a different reason for the booking not going through.")
    else:
        long = problem == "too_long"
        phone_note = (f"The number they gave is {'too long' if long else 'too short'}, so the "
                     "clinic system did not store it. Say EXACTLY say_it_like, word for word, in "
                     "their language: they cannot fix a problem nobody named. NEVER tell them "
                     "the number was saved, never repeat it in a booking summary as if it were "
                     "on file, and never give a different reason for the booking not going "
                     "through.")
    return {
        "phone_problem": problem,
        "phone_given": digits,
        "say_it_like": say_it_like,
        "say_it_like_en": say_it_like_en,
        "phone_note": phone_note,
    }


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# The clock times a customer actually types. Thai writes the hour a dozen ways, so this
# covers the ones that appear in practice and gives up on the rest rather than guessing.
_TIME_RES = (
    (re.compile(r"(\d{1,2})[:.](\d{2})"), lambda h, m: (int(h), int(m))),
    (re.compile(r"(\d{1,2})\s*โมงเช้า"), lambda h, _m: (int(h), 0)),
    (re.compile(r"(\d{1,2})\s*โมงเย็น"), lambda h, _m: (int(h) + 12, 0)),
    (re.compile(r"(\d{1,2})\s*ทุ่ม"), lambda h, _m: (int(h) + 18, 0)),
    (re.compile(r"บ่าย\s*(\d{1,2})"), lambda h, _m: (int(h) + 12, 0)),
    (re.compile(r"(\d{1,2})\s*โมง"), lambda h, _m: (int(h), 0)),
    (re.compile(r"(\d{1,2})\s*(?:am|AM)"), lambda h, _m: (int(h), 0)),
    (re.compile(r"(\d{1,2})\s*(?:pm|PM)"), lambda h, _m: (int(h) % 12 + 12, 0)),
)


def _parse_clock(text: str):
    """Minutes past midnight for the first clock time in ``text``, else None."""
    for pat, to_hm in _TIME_RES:
        m = pat.search(text or "")
        if not m:
            continue
        h, mi = to_hm(m.group(1), m.group(2) if m.re.groups > 1 else 0)
        if 0 <= h < 24 and 0 <= mi < 60:
            return h * 60 + mi
    return None


def _time_asked_by_customer(db, conversation):
    """The clock time the CUSTOMER named, newest message first.

    Read off the transcript rather than trusting the model to pass it, the same way
    `_branch_said_by_customer` reads the branch: this decides whether the answer is
    "that hour is booked" or "the branch is not open yet", and those must never be
    swapped. Newest first so a corrected time wins over the one they opened with.
    """
    if not conversation:
        return None
    for m in reversed(scoped(db, models.Message, conversation.clinic_id)
                      .filter_by(conversation_id=conversation.id, sender="customer")
                      .order_by(models.Message.id).all()):
        got = _parse_clock(m.text or "")
        if got is not None:
            return got
    return None


def _figures_already_quoted(db, conversation, service=None) -> set[int]:
    """The 3+ digit figures the CLINIC side already stated — for ``service`` when one is
    given, otherwise every figure in the conversation.

    Used to tell whether a branch price contradicts a number the customer has already
    been given. Reading it off the transcript (rather than trusting the model to
    remember) is the same trick as _branch_said_by_customer.

    **Per treatment, because a flat set answers the wrong question.** The opening menu
    lists several treatments and several prices; when Hifu's branch price turned out to
    be ฿5,000 — the same figure the menu had just quoted for a DIFFERENT treatment — the
    flat set read it as "already told them" and the price-moved announcement never fired,
    so the customer went from a quoted ฿10,000 to ฿5,000 with no word about it.

    Attribution follows how a person reads the thread: a message naming NO treatment is
    about whatever is in play, so its figures count for any of them ("ที่สาขา North Aurora
    ราคาอยู่ที่ 10,000 บาทค่ะ" is how the announcement itself is worded, and it has to be
    able to retire the note); a message naming exactly one treatment gives it every
    figure; and a message naming several — a menu — is split line by line, which is the
    only case that ever went wrong.
    """
    if not conversation:
        return set()
    msgs = (scoped(db, models.Message, conversation.clinic_id)
            .filter_by(conversation_id=conversation.id)
            .filter(models.Message.sender.in_(["ai", "admin"])).all())
    nums = lambda t: {int(n) for n in re.findall(r"\d{3,}", re.sub(r"[,\s]", "", t or ""))}
    if service is None:
        return {n for m in msgs for n in nums(m.text)}

    services = active_services(db, conversation.clinic_id)
    out: set[int] = set()
    for m in msgs:
        text = m.text or ""
        named_here = {s.id for s in services_named_in(text, services)}
        if not named_here or named_here == {service.id}:
            out |= nums(text)         # about this treatment, or about no other
            continue
        if service.id not in named_here:
            continue
        for line in text.splitlines():   # a menu: one treatment (and its price) per line
            if any(s.id == service.id for s in services_named_in(line, services)):
                out |= nums(line)
    return out


def active_services(db, clinic_id: int) -> list:
    """This clinic's active treatments, LONGEST NAME FIRST — the order every name match
    must use, so "Acne Clear Program test2" is never read as the different treatment
    "Acne Clear Program test" whose name is a prefix of it."""
    return sorted(scoped(db, models.Service, clinic_id).filter_by(active=True).all(),
                  key=lambda s: len(s.name or ""), reverse=True)


# Thai marks that hang off a base letter. A real catalog name is "็Hifu" — a stray
# mai taikhu typed before the H, invisible in the admin form, so nobody sees it — and
# the assistant naturally writes "Hifu". Matching on a key that drops these makes a
# name typed with a slip still findable; both sides are normalised, so a genuinely
# Thai treatment name still matches itself.
_TH_COMBINING = re.compile("[ัิ-ฺ็-๎]")


def _match_key(s: str) -> str:
    return _TH_COMBINING.sub("", (s or "").lower())


def services_named_in(text: str, services) -> list:
    """Which of ``services`` (longest-first) appear in ``text``, consuming each match."""
    blob = _match_key(text)
    out = []
    for s in services:
        n = _match_key((s.name or "").strip())
        if not n:
            continue
        pat = re.compile(re.escape(n))
        if pat.search(blob):
            out.append(s)
            blob = pat.sub(" ", blob)
    return out


def treatments_named_by_customer(db, conversation) -> list:
    """The active treatments the CUSTOMER themselves has named in this chat.

    Same read-it-off-the-transcript trick as ``_branch_said_by_customer``: what the
    customer asked for decides which branches we may offer them, and that must not
    depend on the model choosing to pass an argument.

    Its blind spot is spelling — a customer typing "ไฮฟู" does not match a catalog
    "Hifu", and then nothing narrows the branch question at all. Only the model can
    bridge that, and it does; ``chat._correct_branch_list`` therefore re-runs the same
    match over the model's OWN draft, where the treatment is always named canonically.
    """
    if not conversation:
        return []
    blob = " ".join(m.text or "" for m in
                    scoped(db, models.Message, conversation.clinic_id)
                    .filter_by(conversation_id=conversation.id, sender="customer")
                    .order_by(models.Message.id).all())
    return services_named_in(blob, active_services(db, conversation.clinic_id))


def branches_offering(db, clinic_id: int, services) -> set[int] | None:
    """Branch ids where EVERY one of ``services`` is offered, or None for "no restriction".

    None also covers an empty intersection: if the customer named two treatments that
    share no branch, no single branch answers the question, so narrowing it would be a
    lie — better to name them all and let the tools reject the impossible combination.
    """
    if not services:
        return None
    restricted = _service_branch_ids(db, clinic_id)
    ids: set[int] | None = None
    for s in services:
        r = restricted.get(s.id)
        if not r:
            continue          # offered everywhere - narrows nothing
        ids = set(r) if ids is None else (ids & r)
    return ids or None


def _own_booking_clash(db, customer, branch_id, slot, svc) -> dict:
    """The customer asked to add a treatment on top of their OWN appointment.

    "ขอทำ Acne Clear ต่อเลย" lands on the time they are already booked for, and the
    bare "that time isn't available" said nothing about why — so the assistant could
    neither explain it nor work out what to offer instead, and handed the whole thing
    to a human. It is not a conflict at all, it is a queue: say when the first treatment
    finishes and offer the nearest slots either side for them to confirm.
    """
    from app.services.booking import (SLOT_MINUTES, _duration_of, _now_local,
                                      available_slots)

    if not customer:
        return {}
    same_day = [b for b in scoped(db, models.Booking, customer.clinic_id)
                .filter(models.Booking.customer_id == customer.id,
                        models.Booking.branch_id == branch_id,
                        models.Booking.status.in_(["pending", "confirmed"])).all()
                if b.slot_at.date() == slot.date()]
    want = max(int(svc.duration_min or 0), SLOT_MINUTES)
    hit = next((b for b in same_day
                if b.slot_at < slot + timedelta(minutes=want)
                and slot < b.slot_at + timedelta(minutes=_duration_of(db, b))), None)
    if not hit:
        return {}
    theirs = db.get(models.Service, hit.service_id)
    ends = hit.slot_at + timedelta(minutes=_duration_of(db, hit))
    free = [s for s in available_slots(db, branch_id, slot, service_id=svc.id)
            if s > _now_local()]
    after = next((s for s in free if s >= ends), None)
    before = next((s for s in reversed(free) if s + timedelta(minutes=want) <= hit.slot_at), None)
    options = [s for s in (after, before) if s]
    if not options:
        return {"error": f"{svc.name} cannot fit around the customer's existing "
                         f"{theirs.name if theirs else 'booking'} that day — offer another date."}
    joined = " หรือ ".join(f"{s:%H:%M} น." for s in options)
    return {
        "own_booking_clash": _booking_line(db, hit),
        "first_treatment_ends": f"{ends:%H:%M}",
        "nearest_slots": [f"{s:%Y-%m-%d %H:%M}" for s in options],
        "say_it_like": (f"คิว {theirs.name if theirs else 'ทรีตเมนต์แรก'} ของคุณจบเวลา "
                        f"{ends:%H:%M} น. ค่ะ {svc.name} จึงเริ่มได้เวลา {joined} "
                        "สะดวกเวลาไหนคะ"),
        "say_it_like_en": (f"Your {theirs.name if theirs else 'first treatment'} finishes at "
                           f"{ends:%H:%M}, so {svc.name} can start at "
                           + " or ".join(f"{s:%H:%M}" for s in options) + ". Which suits you?"),
        "note": "This is NOT a clash with another customer — the time is taken by THIS "
                "customer's own appointment, and the treatments simply have to run one "
                "after the other. Say say_it_like (in their language), let them confirm a "
                "time, then call book_appointment again with it. Never tell them the slot "
                "is full, and never hand this to a human: the answer is right here.",
    }


def _booking_line(db, booking) -> str:
    """How a booking is named back to the customer: treatment, branch and when."""
    svc = db.get(models.Service, booking.service_id)
    br = db.get(models.Branch, booking.branch_id) if booking.branch_id else None
    return (f"{svc.name if svc else 'treatment'}"
            + (f" at {br.name}" if br else "")
            + f" on {booking.slot_at:%d/%m %H:%M}")


def _booking_being_paid(db, conversation, customer, live, treatment_arg):
    """Which of the customer's live bookings this payment is for, or None if unclear.

    It used to be "the newest one, always". With two bookings that silently answers a
    question nobody asked: a customer who had just paid a second treatment in full asked
    to settle the balance on the FIRST, and the tool looked at the second, found nothing
    outstanding, and reported "already paid" — so they were told a ฿19,200 balance was
    settled. One booking is unambiguous; more than one has to be named, by the model's
    `treatment` argument or by the customer's own most recent words.
    """
    if len(live) == 1:
        return live[0]
    # Candidates are the treatments THESE bookings are for, not the whole catalog: the
    # question is only ever "which of your bookings", and matching catalog-wide would
    # also stumble over two services sharing a name at different branches.
    by_service = {}
    for b in live:
        svc = db.get(models.Service, b.service_id)
        if svc:
            by_service.setdefault(svc.id, (svc, b))
    candidates = sorted((s for s, _b in by_service.values()),
                        key=lambda s: len(s.name or ""), reverse=True)
    for text in (treatment_arg or "", _last_customer_text(db, conversation)):
        named = services_named_in(text, candidates)
        if len(named) == 1:
            return by_service[named[0].id][1]
    return None


def _last_customer_text(db, conversation) -> str:
    if not conversation:
        return ""
    m = (scoped(db, models.Message, conversation.clinic_id)
         .filter_by(conversation_id=conversation.id, sender="customer")
         .order_by(models.Message.id.desc()).first())
    return (m.text or "") if m else ""


def _price_change_note(branch_name: str, standard: float, branch_price: float) -> dict:
    """The fields that make the AI announce a branch price that moved.

    The prompt already carried this rule and the model kept skipping it: asked for a
    branch it would simply state the new number, leaving the customer to notice that
    9,500 had become 10,000. When the branch is DEARER that is the customer finding
    out at the counter. So the tool now hands over the finished sentence instead of
    asking the model to remember to compose one.
    """
    direction = "higher" if branch_price > standard else "lower"
    gap = abs(int(branch_price - standard))
    word = "สูงกว่า" if direction == "higher" else "ต่ำกว่า"
    return {
        "standard_price": f"฿{int(standard):,}",
        "price_moved": direction,
        "say_it_like": (f"ที่สาขา {branch_name} ราคาอยู่ที่ ฿{int(branch_price):,} ค่ะ "
                        f"{word}ราคาเริ่มต้น ฿{int(standard):,} ที่แจ้งไว้ก่อนหน้าอยู่ ฿{gap:,} "
                        "เพราะแต่ละสาขาราคาต่างกันค่ะ"),
        "say_it_like_en": (f"At {branch_name} it is ฿{int(branch_price):,}, ฿{gap:,} "
                           f"{direction} than the ฿{int(standard):,} starting price I quoted "
                           "earlier, as prices vary by branch."),
    }


def _unavailable_reason(reason: str, day: datetime, window, now: datetime, doctor) -> str:
    """One plain sentence saying WHY a requested date has no openings.

    check_availability used to return an empty slot list with no explanation, so the
    model filled the gap itself — it told a customer at 00:02 that 10:30 the same
    morning "had already passed" when the real reason was a branch closed on Saturdays.
    The reason now travels with the result, and the prompt forbids inventing another.
    """
    who = f" with {doctor.name}" if doctor else ""
    hours = f"{_hhmm(window[0])}-{_hhmm(window[1])}" if window else ""
    weekday = day.strftime("%A")
    if reason == CLOSED:
        return (f"The branch is CLOSED all day on that date — it is a {weekday} and the "
                f"branch never opens on {weekday}s, so NO time on that date exists. The "
                f"time of day has nothing to do with it.")
    if day.date() < now.date():
        return (f"That date is in the past — it was {weekday} {day:%d %B %Y} and it is "
                f"now {now:%A %d %B %Y, %H:%M}.")
    if reason == FULLY_BOOKED:
        return (f"The branch IS open that {weekday} ({hours}) but every single slot is "
                f"already booked{who} — the day is full, whatever time they ask for.")
    same_day = day.date() == now.date()
    when = (f"it is already {now:%H:%M} today" if same_day
            else f"the current clinic time is {now:%A %d %B %Y, %H:%M}")
    if reason == PAST:
        return (f"The branch is open that {weekday} ({hours}), but {when}, so every slot "
                f"of that day is already behind us.")
    if reason == BOOKED_OR_PAST:
        return (f"On that {weekday} ({hours}) the slots that are still ahead of now are "
                f"already booked{who}, and the rest are behind us ({when}).")
    return f"There are no openings on that date{who}."


# Thai weekday names, indexed by datetime.weekday() (Mon=0).
_TH_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def _soft_phrasing(reason: str, day: datetime, now: datetime) -> str:
    """How to SAY the refusal to a Thai customer — gentle, in service language.

    The reason above is written to be blunt so the model cannot waver on the fact;
    left to translate it freely the model produced "สาขาปิดทั้งวันค่ะ เพราะเป็นวันเสาร์",
    which reads like a door shut in the customer's face. This gives it the wording
    the clinic actually wants: the branch's service days, not a refusal.
    """
    th_day = _TH_DAYS[day.weekday()]
    if reason == CLOSED:
        return f"สาขานี้ปิดให้บริการในวัน{th_day}ค่ะ"
    if day.date() < now.date():
        return f"วันที่ {day:%d/%m} ผ่านมาแล้วค่ะ"
    if reason == FULLY_BOOKED:
        return f"วัน{th_day}ที่ {day:%d/%m} คิวเต็มแล้วค่ะ"
    if reason == PAST:
        return f"วัน{th_day}ที่ {day:%d/%m} ปิดรับคิวแล้วค่ะ"
    if reason == BOOKED_OR_PAST:
        return f"คิวที่เหลือของวัน{th_day}ที่ {day:%d/%m} เต็มแล้วค่ะ"
    return f"วัน{th_day}ที่ {day:%d/%m} ไม่มีคิวว่างค่ะ"


def _branch_move_note(db, conversation, customer) -> dict:
    """What the customer must be told the moment this chat changes branch on them.

    A customer booked and paid a deposit on HIFU at South Aurora, then asked for a
    treatment South does not sell; the chat moved to Central and carried on in Central's
    prices. The paid booking does not move with the conversation and the same treatment
    is dearer at Central, so the figures on screen no longer described the appointment
    they had bought — and nobody said so. Said on the turn the branch changes, which is
    before anything is quoted or booked against it.
    """
    if not (customer and conversation and conversation.branch_id):
        return {}
    from app.services.booking import resolved_price
    from app.services.billing import _paid_total_for_booking

    here = db.get(models.Branch, conversation.branch_id)
    if not here:
        return {}
    lines, sentences = [], []
    for b in (scoped(db, models.Booking, conversation.clinic_id)
              .filter(models.Booking.customer_id == customer.id,
                      models.Booking.status.in_(["pending", "confirmed"]),
                      models.Booking.branch_id.isnot(None),
                      models.Booking.branch_id != here.id)
              .order_by(models.Booking.slot_at).all()):
        svc, br = db.get(models.Service, b.service_id), db.get(models.Branch, b.branch_id)
        if not (svc and br):
            continue
        lines.append(f"{svc.name} at {br.name}, {b.slot_at:%d/%m %H:%M}, ฿{int(b.price or 0):,} "
                     f"(paid so far ฿{int(_paid_total_for_booking(db, b)):,})")
        s = (f"คิว {svc.name} ของคุณยังอยู่ที่สาขา {br.name} วันที่ {b.slot_at:%d/%m} "
             f"เวลา {b.slot_at:%H:%M} น. ราคา ฿{int(b.price or 0):,} เหมือนเดิมนะคะ "
             "การเลือกสาขาใหม่ในแชทนี้ไม่ได้ย้ายคิวนั้นค่ะ")
        moved = resolved_price(db, conversation.clinic_id, svc, here.id)
        if moved and int(moved) != int(b.price or 0):
            s += (f" (ถ้าย้ายไปทำที่ {here.name} ราคา {svc.name} จะเป็น ฿{int(moved):,} "
                  f"ไม่ใช่ ฿{int(b.price or 0):,} ที่จองไว้ค่ะ)")
        sentences.append(s)
    if not lines:
        return {}
    return {
        "existing_booking_elsewhere": lines,
        "branch_move_say_it_like": " ".join(sentences),
        "branch_move_note": (
            "This chat has just moved to a different branch from a booking the customer "
            "ALREADY holds. Say branch_move_say_it_like (in their language) in this reply, "
            "before quoting or booking anything here: their existing appointment does not "
            "move with the conversation, its price does not follow them, and they cannot "
            "be at two branches at the same time. Never offer a slot that clashes with it."),
    }


def _slot_taken_result(slot: datetime, reason: str) -> dict:
    """Somebody else took the slot between the availability check and the write.

    The customer has just answered the deposit-or-full question and is expecting the payment QR,
    so "nothing has been charged" is load-bearing: without it, the natural reading of a
    failure arriving right after agreeing to pay is that something went wrong with their
    money. Nothing was booked and no payment was created — say both.
    """
    return {
        "slot_taken": True,
        "reason_code": reason,
        "say_it_like": (f"ขออภัยค่ะ เวลา {slot:%H:%M} น. วันที่ {slot:%d/%m} "
                        "เพิ่งมีลูกค้าท่านอื่นจองไปพอดีตอนนี้เลยค่ะ "
                        "ยังไม่ได้ทำการจองและยังไม่มีการเรียกเก็บเงินนะคะ "
                        "เดี๋ยวเช็กเวลาที่ยังว่างให้ใหม่ค่ะ"),
        "say_it_like_en": (f"I'm sorry — {slot:%H:%M} on {slot:%d %b} was taken by another "
                           "customer just now. Nothing has been booked and nothing has "
                           "been charged. Let me find you another time."),
        "note": ("The booking did NOT happen and no payment was created. Say say_it_like in "
                 "the customer's language, then call check_availability for that day and "
                 "offer real alternatives. Do NOT call create_payment_link — there is no "
                 "booking to pay for — and do not retry book_appointment on the same time."),
    }


def _hold_expired_result(db, booking) -> dict:
    """They are trying to pay for a booking whose hold already ran out.

    Two sub-cases, because "just say the word and I'll rebook it" when the time is gone is
    the same dead end as the old branch-restriction message: offer only what is real. The
    old behaviour here was to report no booking at all, which is a flat contradiction to
    someone who booked forty minutes ago and is now clicking pay.
    """
    svc = db.get(models.Service, booking.service_id) if booking.service_id else None
    sname = svc.name if svc else "ทรีตเมนต์"
    still_free = booking.slot_at in available_slots(
        db, booking.branch_id, booking.slot_at, service_id=booking.service_id,
        doctor_id=booking.doctor_id, exclude_booking_id=booking.id)
    when_th = f"วันที่ {booking.slot_at:%d/%m} เวลา {booking.slot_at:%H:%M} น."
    when_en = f"on {booking.slot_at:%d %b} at {booking.slot_at:%H:%M}"
    # The number THIS booking was actually held for, not whatever the clinic/service
    # setting says now — booking.hold_minutes or HOLD_MINUTES covers rows written
    # before this column existed, where it is still 0.
    held_for = booking.hold_minutes or HOLD_MINUTES
    if still_free:
        say = (f"คิว {sname} {when_th} หมดเวลาถือคิวแล้วค่ะ เพราะยังไม่ได้ชำระภายใน "
               f"{held_for} นาที ตอนนี้เวลานั้นยังว่างอยู่ ให้จองใหม่ให้เลยไหมคะ")
        say_en = (f"The hold on your {sname} appointment {when_en} has run out — the payment "
                  f"didn't come through within {held_for} minutes. That time is still "
                  "free; would you like me to book it again?")
    else:
        say = (f"คิว {sname} {when_th} หมดเวลาถือคิวแล้ว และเวลานั้นมีลูกค้าท่านอื่นจองไปแล้วค่ะ "
               "ขออภัยด้วยนะคะ เดี๋ยวเช็กเวลาที่ว่างให้ใหม่ค่ะ")
        say_en = (f"The hold on your {sname} appointment {when_en} has run out, and that time "
                  "has since been taken by someone else. I'm sorry about that — let me find "
                  "you another time.")
    return {
        "hold_expired": _booking_line(db, booking),
        "slot_still_free": still_free,
        "say_it_like": say,
        "say_it_like_en": say_en,
        "note": ("This booking no longer holds a slot, so do NOT send the payment QR for it. "
                 "Say say_it_like in the customer's language. If slot_still_free is true and "
                 "they want that time, call book_appointment for it again; if it is false, "
                 "call check_availability and offer real alternatives. Never tell them there "
                 "is no booking — there was one, and its hold lapsed."),
    }


def _qr_payment(payment, ptype: str, which: str) -> dict | None:
    """The clinic's payment QR, as tool-result fields, for what this payment owes.

    None when there is nothing to collect (already paid, or ฿0) or no QR is set up."""
    from app.services.promptpay import qr_image_url

    if not payment or payment.status == "paid" or float(payment.amount or 0) <= 0:
        return None
    qr = qr_image_url()
    if not qr:
        return None
    amount_txt = f"฿{int(payment.amount):,}"
    what_th = "ยอดชำระเต็มจำนวน" if ptype == "full" else "ยอดมัดจำ"
    what_en = "the full amount" if ptype == "full" else "the deposit"
    return {
        "payment_qr": qr, "amount": amount_txt, "amount_value": float(payment.amount),
        "payment_id": payment.id,
        "label": "ชำระเต็มจำนวน" if ptype == "full" else "ชำระมัดจำ",
        "booking": which,
        "qr_say_it_like": (f"รบกวนสแกน QR ด้านล่างเพื่อโอน{what_th} {amount_txt} "
                           "แล้วส่งรูปสลิปในแชทนี้ได้เลยค่ะ ทีมงานจะตรวจสอบและยืนยันคิวให้นะคะ"),
        "qr_say_it_like_en": (f"Please scan the QR code below to transfer {what_en} of "
                              f"{amount_txt}, then send a photo of the slip here. Our team "
                              "will check it and confirm your booking."),
        "note": ("The clinic's payment QR (bank transfer / PromptPay) is now shown to the "
                 f"customer under your reply, for {which}. Say qr_say_it_like in their "
                 "language. Do NOT paste the QR address or a link, and do NOT say the "
                 "payment is done: a slip they send is checked by the team, never confirmed "
                 "by you."),
    }


def execute_tool(db, conversation, customer, name: str, args: dict) -> dict:
    """Run a tool, then add anything the customer must hear about a branch change it made."""
    before = conversation.branch_id if conversation else None
    res = _run_tool(db, conversation, customer, name, args)
    if isinstance(res, dict) and conversation and conversation.branch_id != before:
        res.update(_branch_move_note(db, conversation, customer))
    return res


def _run_tool(db, conversation, customer, name: str, args: dict) -> dict:
    """Run a tool call and return a JSON-serialisable result."""
    # Before anything else, so not even a branch gets written for a booking that
    # cannot happen in this chat.
    if name == "book_appointment" and booking_requires_signup(conversation, customer):
        return signup_required_result()
    clinic_id = conversation.clinic_id
    branch_count = scoped(db, models.Branch, clinic_id).count()
    # If the AI passed a branch name, lock it onto the conversation so every downstream
    # lookup (slots, price, promotions) uses the branch the customer actually chose —
    # but only once we can see the customer really chose it. A branch the model invented
    # would otherwise defeat the need_branch guard below and book them somewhere they
    # never asked for.
    arg_branch = _resolve_branch(db, clinic_id, args.get("branch"))
    rejected_branch = ""
    if arg_branch and branch_count > 1 and not _branch_said_by_customer(
            db, conversation, arg_branch, args.get("branch_said")):
        rejected_branch, arg_branch = arg_branch.name, None
    if arg_branch and conversation.branch_id != arg_branch.id:
        conversation.branch_id = arg_branch.id
        if customer and not customer.branch_id:
            customer.branch_id = arg_branch.id   # so per-branch customer views find them
        db.commit()
    unconfirmed_note = ""
    if rejected_branch:
        unconfirmed_note = (
            f" You passed branch '{rejected_branch}', but nothing the CUSTOMER wrote names it, "
            "so it was ignored — never choose a branch on their behalf. If they really did name "
            "one, call this tool again with branch_said set to their exact words.")
    # The branch chosen IN THIS CONVERSATION only. The customer's home branch
    # (customer.branch_id — just where they went last time) must NOT silently flavour
    # prices/slots: that made the AI confirm a branch the customer never picked this
    # chat, sometimes the wrong one. It is offered as a suggestion to confirm instead.
    known_branch = conversation.branch_id
    usual_branch = None
    if not known_branch and customer and customer.branch_id:
        ub = db.get(models.Branch, customer.branch_id)
        usual_branch = ub.name if ub else None
    usual_note = (f" The customer's USUAL branch from past visits is {usual_branch} — "
                  "suggest it ('สะดวกสาขา " + (usual_branch or "") + " เหมือนเดิมไหมคะ') but "
                  "let them confirm; never assume it." if usual_branch else "")
    branch_id = known_branch
    if not branch_id:
        fb = scoped(db, models.Branch, clinic_id).order_by(models.Branch.id).first()
        branch_id = fb.id if fb else None
    # A definite branch for pricing/promotions: the known one, or the only branch when there
    # is just one (no ambiguity). None only in the multi-branch, branch-unknown case.
    price_branch = known_branch or (branch_id if branch_count == 1 else None)

    # Hard guard: in a multi-branch clinic, never check availability or book until the
    # customer has actually chosen a branch — otherwise we'd silently use the first one.
    if name in ("check_availability", "book_appointment") and branch_count > 1 and not known_branch:
        names = [b.name for b in scoped(db, models.Branch, clinic_id)
                 .order_by(models.Branch.id).all()]
        return {"need_branch": True, "branches": names,
                "note": "This clinic has multiple branches. ASK the customer which branch they "
                        "want first (availability, price and promotions differ per branch), then "
                        "call this tool again with the chosen branch." + usual_note + unconfirmed_note}

    if name == "search_knowledge_base":
        # price_branch, not branch_id: with several branches and none chosen yet, the
        # first-branch fallback would quietly answer as if the customer were at branch #1
        # (and hide the other branches' content). Unknown branch = search them all.
        chunks = rag.retrieve(db, args.get("query", ""), clinic_id, branch_id=price_branch, k=5)
        res = {"results": [{"title": c["title"], "info": c["text"]} for c in chunks]}
        if branch_count > 1 and not known_branch:
            # Results span every branch and may name one. That name is NOT the customer's
            # branch — without this the model adopts the first one it reads.
            res["branch_note"] = ("The customer has not chosen a branch, so these results cover "
                                  "ALL branches. Any branch named in them is not the customer's "
                                  "branch: do not attach a branch name to your answer, and ask "
                                  "which branch they want." + usual_note + unconfirmed_note)
        return res

    if name == "list_treatments":
        cat = (args.get("category") or "").lower()
        # branch-specific prices override the base price when the branch is known
        price_by_service = {}
        if price_branch:
            for sp in (scoped(db, models.ServicePrice, clinic_id)
                       .filter_by(branch_id=price_branch).all()):
                if sp.price:   # a falsy row is no override — mirror resolved_price
                    price_by_service[sp.service_id] = sp.price
        service_branches = _service_branch_ids(db, clinic_id)
        branch_names = {b.id: b.name for b in scoped(db, models.Branch, clinic_id).all()}
        # What the CUSTOMER asked for decides which branches we may name. A treatment they
        # asked about by name is never silently dropped: it either comes back with the
        # branches that have it, or with a sentence saying this branch does not.
        asked = treatments_named_by_customer(db, conversation)
        asked_ids = {s.id for s in asked}
        out, moved, missing = [], [], []
        scoped_any = False                   # some treatment here is branch-restricted
        served_elsewhere: set[int] = set()   # branches holding what this one doesn't
        for s in scoped(db, models.Service, clinic_id).filter_by(active=True).all():
            if cat and cat not in s.category.lower():
                continue
            restricted = service_branches.get(s.id)
            only_at = []
            if restricted:                        # offered only at specific branches
                if not price_branch:
                    # It used to be hidden until a branch was known, which is what left
                    # the assistant asking "which branch?" across branches that do not
                    # have it. Say WHERE it is instead — and the same way the always-on
                    # catalog block does it, so the two cannot contradict each other.
                    only_at = [branch_names[b] for b in sorted(restricted) if b in branch_names]
                    scoped_any = True
                elif price_branch not in restricted:
                    served_elsewhere |= set(restricted)
                    if s.id in asked_ids:
                        elsewhere = [branch_names[b] for b in sorted(restricted) if b in branch_names]
                        here = branch_names.get(price_branch, "")
                        missing.append({
                            "name": s.name,
                            "available_at": elsewhere,
                            "say_it_like": (f"ทรีตเมนต์ {s.name} ยังไม่เปิดให้บริการที่สาขา {here} ค่ะ "
                                            f"ตอนนี้มีที่สาขา {' และ '.join(elsewhere)} ค่ะ"),
                            "say_it_like_en": (f"{s.name} is not offered at {here}. It is available "
                                               f"at {' and '.join(elsewhere)}."),
                        })
                    continue                      # wrong branch for this customer
            price = price_by_service.get(s.id, s.base_price)
            item = {"name": s.name, "category": s.category,
                    "price_from": f"฿{int(price):,}",
                    "deposit_from": f"฿{int(deposit_for(s, price)):,}",
                    "duration_min": s.duration_min}
            if only_at:
                item["only_at"] = only_at
                # A finished sentence, because "write the catalog spelling" as a rule
                # loses to the pull of echoing the customer: they typed "ไฮฟู่ว" and the
                # reply came back "ไฮฟู่วมีที่สาขา...", which leaves the customer unsure
                # which item on the menu they are getting AND switches off the branch
                # check in chat._correct_branch_list, since that matches on the catalog
                # name. Handed a sentence, the model copies it (see _price_change_note).
                #
                # A STATEMENT, never a question. Ending it with "สะดวกสาขาไหนคะ" got it
                # pasted straight into an opening menu — three treatments, three
                # which-branch questions, and the prices pushed off their own lines. As a
                # bare fact it reads correctly wherever it lands: in a menu it is the
                # "(available at ...)" note the clinic wants, and when the branch question
                # is actually due the model writes the question itself, in the ครับ/ค่ะ of
                # that conversation rather than the template's.
                item["say_it_like"] = f"{s.name} มีที่สาขา {' และ '.join(only_at)} ค่ะ"
                item["say_it_like_en"] = (f"{s.name} is available at "
                                          f"{' and '.join(only_at)}.")
            # This branch costs something OTHER than the starting price the customer was
            # already given — spell out the difference so the AI cannot just state the new
            # number and let them discover it.
            std = float(s.base_price or 0)
            # `int(price) not in quoted` retires the note once the branch figure has been
            # said: without it every later list_treatments call re-armed it and the model
            # dutifully repeated the whole price paragraph, even to a bare "ครับ".
            # Scoped to THIS treatment — another treatment's price happening to equal
            # this branch's price used to silence the announcement entirely.
            quoted = (_figures_already_quoted(db, conversation, s)
                      if price_branch and std and int(price) != int(std) else set())
            if (price_branch and std and int(price) != int(std)
                    and int(std) in quoted and int(price) not in quoted):
                item.update(_price_change_note(branch_names.get(price_branch, ""), std,
                                               float(price)))
                moved.append(s.name)
            out.append(item)
        res = {"treatments": out}
        if not out:
            # An empty list is a GAP, and the model fills a gap with whatever it read a
            # moment ago: a branch opened last week with nothing on its menu yet drew
            # "สาขาเปิดใหม่มีทรีตเมนต์ผิวหน้าให้เลือก 2 ตัวค่ะ" — both of them belonging to the
            # OTHER branch and named earlier in the same chat. Same rule as an empty
            # availability day (booking.day_availability): say WHY there is nothing.
            elsewhere = [branch_names[b] for b in sorted(served_elsewhere) if b in branch_names]
            here = branch_names.get(price_branch, "")
            if price_branch and elsewhere:
                res["empty_reason"] = "no_treatments_at_this_branch"
                res["available_at"] = elsewhere
                res["say_it_like"] = (f"ตอนนี้สาขา {here} ยังไม่มีทรีตเมนต์เปิดให้บริการในระบบค่ะ "
                                      f"ทรีตเมนต์ของเรามีที่สาขา {' และ '.join(elsewhere)} ค่ะ")
                res["say_it_like_en"] = (f"{here} has no treatments listed yet. Ours are available "
                                         f"at {' and '.join(elsewhere)}.")
            elif price_branch:
                res["empty_reason"] = "catalog_empty"
                res["say_it_like"] = ("ขออภัยค่ะ ตอนนี้ยังไม่มีรายการทรีตเมนต์ในระบบ "
                                      "เดี๋ยวทีมงานติดต่อกลับเพื่อให้ข้อมูลนะคะ")
                res["say_it_like_en"] = ("We have no treatments listed yet. The team will follow up "
                                         "with the details.")
            else:
                res["empty_reason"] = "hidden_until_branch_known"
            res["empty_note"] = (
                "There are NO treatments to present. Say so using say_it_like (in the customer's "
                "language). Do NOT name any treatment: anything mentioned earlier in this chat "
                "belongs to a DIFFERENT branch and repeating it here would promise something this "
                "branch cannot deliver.")
        if missing:
            res["not_at_this_branch"] = missing
            res["not_at_this_branch_note"] = (
                "The customer asked for these by name and this branch does not have them. Lead "
                "with say_it_like (in their language) BEFORE anything else: say plainly that the "
                "branch does not offer it and name the branches that do, so they can switch "
                "branch if they want. Never quietly answer with a different treatment instead, "
                "and never say the team will check — the answer is right here.")
        if moved:
            res["price_change_note"] = (
                f"The branch price of {', '.join(moved)} is NOT the starting price this "
                "customer was already quoted. Lead with that treatment's say_it_like (in "
                "their language) as its own short message and ask them to confirm the new "
                "price BEFORE you ask for a date, check availability or summarise. Never "
                "just state the new number and move on, and never call the earlier figure "
                "a mistake - neither was wrong, branches simply differ.")
        if branch_count > 1 and not known_branch:
            # Only the branches that actually have what they asked for. Offering the
            # others is how a customer ends up choosing a branch, being told the
            # treatment is not there, and having to start again.
            allowed = branches_offering(db, clinic_id, asked)
            offer = [branch_names[b] for b in sorted(allowed) if b in branch_names] if allowed else []
            res["branch_note"] = ("This clinic has multiple branches and prices can differ by branch. "
                                  "These are standard prices valid clinic-wide, NOT one branch's menu: "
                                  "do not name a branch when presenting them. Ask which branch the "
                                  "customer wants, then call this tool again for the exact price."
                                  + (f" The treatment they asked about is offered ONLY at: "
                                     f"{', '.join(offer)}. Name ONLY these branches when you ask — "
                                     "offering one that does not have it wastes their choice."
                                     if offer and len(offer) < branch_count else "")
                                  + usual_note
                                  + (" A treatment carrying 'only_at' exists at THOSE branches only. "
                                     "When YOU pick what to present, prefer treatments without it; "
                                     "use one that has it when there are not enough others or the "
                                     "customer named it. Its say_it_like (in the customer's language) "
                                     "is the FACT of where it runs, written with the treatment named "
                                     "the way the CLINIC spells it - use it whenever you mention that "
                                     "treatment, and never answer with the customer's own spelling. "
                                     "It is a statement, not a whole turn: add the which-branch "
                                     "question yourself, once, only when it is actually due."
                                     if scoped_any else "") + usual_note + unconfirmed_note)
        return res

    if name == "list_promotions":
        branches = {b.id: b.name for b in scoped(db, models.Branch, clinic_id).all()}
        inactive_sids = {s.id for s in scoped(db, models.Service, clinic_id)
                         .filter_by(active=False).all()}
        promos = scoped(db, models.Promotion, clinic_id).filter_by(active=True).all()
        now = _now_local()
        dead = exhausted_promo_ids(db, clinic_id) if promos else set()
        promo_bmap = promo_branch_ids(db, clinic_id) if promos else {}
        out = []
        hidden = False
        for p in promos:
            if not promo_date_ok(p, now):
                continue                          # expired or not yet started
            if p.id in dead:
                continue                          # quota fully redeemed
            if p.service_id and p.service_id in inactive_sids:
                continue                          # the promoted treatment is switched off
            pb = promo_bmap.get(p.id)
            if pb:                                # runs at specific branches only
                if not price_branch:
                    hidden = True
                    continue                      # don't surface it for an unknown branch
                if not promo_runs_at(pb, price_branch):
                    continue                      # wrong branch for this customer
            out.append({
                "title": p.title, "detail": p.detail, "discount": p.discount_label,
                "price": (f"฿{int(p.promo_price):,}" if p.promo_price else None),
                "branch": "all branches" if not p.branch_id else f"{branches.get(p.branch_id, 'one branch')} only"})
        res = {"promotions": out}
        if len(branches) > 1 and not known_branch:
            res["branch_note"] = ("The customer's branch is unknown and this clinic has multiple branches. "
                                  "Promotions and prices can differ by branch, so ask which branch they want "
                                  "before presenting any promotion as final." + usual_note
                                  + (" Some branch-specific promotions are hidden until the branch is known."
                                     if hidden else "") + usual_note + unconfirmed_note)
        return res

    if name == "check_availability":
        date_s = args.get("date")
        doctor = _resolve_doctor(db, clinic_id, args.get("doctor")) if args.get("doctor") else None
        if args.get("doctor") and not doctor:
            return {"error": f"No doctor named '{args.get('doctor')}' at this clinic — "
                             "ask the customer to clarify or offer any available doctor."}
        did = doctor.id if doctor else None
        requested_day = None
        if date_s:
            try:
                requested_day = datetime.fromisoformat(date_s)
            except Exception:
                requested_day = None
        now = _now_local()
        if requested_day:
            slots, reason, window = day_availability(db, branch_id, requested_day,
                                                     doctor_id=did)
            if not slots:
                # Never silently substitute other days for the asked date — say so, and
                # say WHY, so the AI states the real reason instead of guessing one.
                others = next_available(db, branch_id, days_ahead=NEXT_AVAILABLE_DAYS,
                                        doctor_id=did)
                # The branch name and that day's hours ride along so the reply itself
                # shows WHICH branch's calendar produced the answer — a refusal that
                # contradicts Settings -> Branches is then visible in the transcript
                # instead of having to be reconstructed from it afterwards.
                br_row = db.get(models.Branch, branch_id)
                return {"available_slots": [],
                        "requested_date_unavailable": date_s,
                        "requested_date_is": requested_day.strftime("%A %d %B %Y"),
                        "branch": br_row.name if br_row else None,
                        "branch_hours_that_day": (f"{_hhmm(window[0])}-{_hhmm(window[1])}"
                                                  if window else "closed"),
                        "now": now.strftime("%A %d %B %Y, %H:%M"),
                        "reason_code": reason,
                        "reason": _unavailable_reason(reason, requested_day, window,
                                                      now, doctor),
                        "say_it_like": _soft_phrasing(reason, requested_day, now),
                        "other_days": [s.strftime("%Y-%m-%d %H:%M") for s in others],
                        "note": "No openings on the requested date. The REASON is the fact; "
                                "say_it_like is HOW to say it - it is written for a Thai "
                                "customer, so an English-speaking one gets the same thing in "
                                "English, never the Thai sentence. Open with it: gentle, in "
                                "service language, no blunt 'ปิดทั้งวัน' / 'we are closed all "
                                "day' and no lecturing them about why. If you already told "
                                "them this earlier in the chat, do NOT paste the same sentence "
                                f'again: open with the standard acknowledgement ("{ACK_TH}" / '
                                f'"{ACK_EN}") and re-word it. Keep the fact of the reason: '
                                "never add a second reason "
                                "of your own, and never tell them a time has already passed "
                                "unless the reason says so. Then offer the alternatives from "
                                "other_days, saying clearly which date each slot is on. Never "
                                "name a time that is not in other_days, even if the customer "
                                "pushes back - stay warm, but stay on the facts."}
        else:
            slots = next_available(db, branch_id, days_ahead=NEXT_AVAILABLE_DAYS,
                                   doctor_id=did)
        # return the WHOLE day's openings (morning/afternoon/evening), not just the
        # first few, so the AI can answer about any part of the day.
        out = [s.strftime("%Y-%m-%d %H:%M") for s in slots[:30]]
        # `now` travels with every result: these slots are ALREADY filtered against it,
        # so the AI must never re-judge one as "too late" from its own sense of time.
        res = {"available_slots": out, "now": now.strftime("%A %d %B %Y, %H:%M"),
               "slots_note": "Every time listed above is genuinely open and still in the "
                             "future. Offer only these times — never invent one and never "
                             "tell the customer a listed time has already passed."}
        if doctor:
            res["doctor"] = doctor.name
        # The day HAS openings, but the hour they asked for is one the branch is shut.
        # Nothing here used to say so — the hours only travelled when a day had no slots
        # at all — so the model answered "8:30 ยังไม่ว่างค่ะ", which tells the customer
        # that hour is BOOKED when the clinic simply had not opened. The reason is in the
        # branch's schedule, so it is stated, never inferred.
        if requested_day and window:
            want = _parse_clock(args.get("time") or "")
            if want is None:
                want = _time_asked_by_customer(db, conversation)
            br_row = db.get(models.Branch, branch_id)
            hours = f"{_hhmm(window[0])}-{_hhmm(window[1])}"
            res["branch"] = br_row.name if br_row else None
            res["branch_hours_that_day"] = hours
            if want is not None and not (window[0] <= want < window[1]):
                early = want < window[0]
                res["requested_time_outside_hours"] = _hhmm(want)
                # Don't write "สาขา สาขาเปิดใหม่" — plenty of branches are named "สาขา…"
                # already, and the doubled word reads as a typo in the customer's chat.
                where = (res["branch"] if (res["branch"] or "").startswith("สาขา")
                         else f"สาขา {res['branch']}")
                res["say_it_like"] = (
                    f"{where} เปิดให้บริการ {hours} น. ค่ะ "
                    f"เวลา {_hhmm(want)} น. จึง{'ยังไม่เปิด' if early else 'เลยเวลาปิด'}ทำการนะคะ")
                res["say_it_like_en"] = (
                    f"{res['branch']} is open {hours}, so {_hhmm(want)} is "
                    f"{'before we open' if early else 'after we close'}.")
                res["outside_hours_note"] = (
                    "The customer asked for a time this branch is NOT OPEN. Open with "
                    "say_it_like (in their language): the reason is the opening hours, and it "
                    "is the only reason you may give. Never say that time is 'not available' / "
                    "'ยังไม่ว่าง' / 'คิวเต็ม' - that tells them it is booked when the clinic is "
                    "shut, and never invent any other reason. Then offer times from "
                    "available_slots.")
        # A slot this customer has ALREADY booked is missing from available_slots — without
        # this the AI reads its own booking as "that time is taken" and tells the customer
        # their confirmed appointment is unavailable.
        if customer:
            mine = []
            for b in (scoped(db, models.Booking, clinic_id).filter_by(customer_id=customer.id)
                      .filter(models.Booking.status.in_(["pending", "confirmed"]),
                              models.Booking.slot_at > now)
                      .order_by(models.Booking.slot_at).all()):
                if requested_day and b.slot_at.date() != requested_day.date():
                    continue
                svc_b = db.get(models.Service, b.service_id)
                mine.append(f"{b.slot_at:%Y-%m-%d %H:%M} {svc_b.name if svc_b else 'treatment'} "
                            f"({b.status})")
            if mine:
                res["customers_own_bookings"] = mine
                res["own_booking_note"] = (
                    "These times are missing from available_slots because THIS customer already "
                    "booked them. They are the customer's own confirmed appointments — never say "
                    "that time is unavailable or full, and never offer to rebook it.")
        if len(out) > 8:
            # Only prompt for a time preference when the customer has not named one yet —
            # otherwise this note makes the AI re-offer time options it already gave and
            # the conversation loops on a question the customer has answered.
            res["note"] = ("Open across the whole day. If the customer has NOT yet named a time, "
                           "tell them which parts of the day are free (morning / afternoon / "
                           "evening) and ask which they prefer, rather than listing every single "
                           "time. If they ALREADY named a time and it appears in available_slots, "
                           "that time is settled: confirm it once and move straight to the next "
                           "missing booking-checklist item — do not offer time options again and "
                           "do not repeat that the day is open.")
        return res

    if name == "book_appointment":
        svc = _find_service(db, args.get("treatment"), clinic_id, branch_id)
        if not svc:
            return {"error": "Treatment not recognised — ask the customer to clarify."}
        svc_branches = _service_branch_ids(db, clinic_id).get(svc.id)
        if svc_branches and branch_id not in svc_branches:
            return {"error": "This treatment is not offered at the customer's branch."}
        try:
            slot = datetime.fromisoformat(f"{args['date']}T{args['time']}")
        except Exception:
            return {"error": "Invalid date/time. Use date YYYY-MM-DD and time HH:MM."}
        doctor = _resolve_doctor(db, clinic_id, args.get("doctor")) if args.get("doctor") else None
        did = doctor.id if doctor else None
        # Only allow a genuinely open slot: day_availability excludes past times,
        # out-of-hours times, already-taken slots and (with a doctor) that doctor's
        # other bookings — so this blocks past-dated bookings and double-booking.
        # Called directly (not via available_slots) so a failure carries the SAME
        # reason/window check_availability already knows how to explain — a bare
        # "not available, call check_availability first" was seen sending the model
        # around a second tool-call loop that landed on the same unexplained refusal,
        # and it improvised a "the system is having trouble" excuse rather than the
        # real reason (the slot's own day had simply run out, hours after the
        # appointment time asked for had already passed).
        day_slots, day_reason, day_window = day_availability(
            db, branch_id, slot, service_id=svc.id, doctor_id=did)
        if slot not in day_slots:
            clash = _own_booking_clash(db, customer, branch_id, slot, svc)
            if clash:
                return clash
            requested = f"{args['date']} {args['time']}"
            now = _now_local()
            if day_reason:
                # The whole day has nothing open — same reason vocabulary
                # check_availability uses, so the model has the real "why" on THIS
                # call instead of needing a second one to learn it.
                others = next_available(db, branch_id, service_id=svc.id,
                                        days_ahead=NEXT_AVAILABLE_DAYS, doctor_id=did)
                return {"booked": False, "requested_time_unavailable": requested,
                       "reason_code": day_reason,
                       "reason": _unavailable_reason(day_reason, slot, day_window,
                                                     now, doctor),
                       "say_it_like": _soft_phrasing(day_reason, slot, now),
                       "other_days": [s.strftime("%Y-%m-%d %H:%M") for s in others],
                       "note": "That exact request has no opening at all that day — "
                               "say_it_like is how to say so, gently, with no second "
                               "reason of your own. Then offer from other_days, naming "
                               "which date each is on. Do not call book_appointment "
                               "again for this same date/time."}
            # The day itself has other openings — just not this exact time (outside
            # hours, or someone else has this specific slot while others are free).
            same_day = [s.strftime("%H:%M") for s in day_slots
                       if s.date() == slot.date()][:8]
            return {"booked": False, "requested_time_unavailable": requested,
                   "other_times_same_day": same_day,
                   "note": "That exact time is not open, but other times that same "
                           "day are — listed in other_times_same_day. Offer a few of "
                           f"them{' with ' + doctor.name if doctor else ''}. Do not "
                           "call book_appointment again for this same time."}
        # Checklist order: contact first, then the deposit-or-full answer. Both are checked
        # after the slot/branch validation so a genuinely bad request still gets the precise
        # error instead of being told to go collect a phone number.
        missing = _capture_contact(db, customer, args.get("customer_name"), args.get("phone"),
                                   conversation, args.get("no_phone_said"))
        if missing:
            res = {"need_contact": missing,
                   "note": "The clinic needs the customer's " + " and ".join(missing)
                           + " before a booking can be made. Ask for "
                           + ("them" if len(missing) > 1 else "it")
                           + " in one short message, then call book_appointment again "
                             "passing customer_name and phone. If the customer will not "
                             "give it, use request_human_help instead of booking."}
            if "phone number" in missing:
                res.update(_phone_rejection(db, conversation, args.get("phone")))
            return res
        # The deposit-or-full answer is the ONE confirmation checkpoint before booking.
        # Refusing the call without it stops the model summarising and booking in the same
        # breath, which hands the customer a payment link they never agreed to.
        if args.get("payment_type") not in ("deposit", "full") or not \
                _payment_choice_by_customer(db, conversation, args["payment_type"],
                                            args.get("payment_said")):
            return {"need_payment_choice": True,
                    "note": "Do not book yet, and do not send the payment QR. Nothing the "
                            "CUSTOMER has written picks the deposit or the full amount. Send "
                            "the booking summary (name, phone, treatment, branch, date, time, "
                            "price, deposit) as its own message ending in that one question, "
                            "wait for their reply, then call this tool again with payment_type "
                            "set to their answer and payment_said set to their exact words. "
                            "Giving them their phone number back is not an answer to it."}
        # What list_treatments would have quoted: the branch price, or the catalog price
        # — resolved_price_detail's first step, BEFORE it looks for a promotion.
        _sp = (db.query(models.ServicePrice)
               .filter_by(clinic_id=clinic_id, service_id=svc.id, branch_id=branch_id).first())
        quoted_price = float(_sp.price) if _sp and _sp.price else float(svc.base_price or 0)
        # Service override, else clinic override, else the .env default — resolved ONCE
        # here so create_booking, the tool result and the say_it_like text all agree on
        # the same number for this booking.
        resolved_hold = resolved_hold_minutes(db, clinic_id, svc)
        # The availability check above is the FRIENDLY one — it is what produces
        # _own_booking_clash and the doctor-named error. claim_slot is the GUARANTEE: it
        # re-checks and writes under this clinic's claim lock, so two customers answering
        # "มัดจำค่ะ" at the same moment cannot both take the slot. Keep both.
        def _write():
            b = create_booking(db, customer=customer, service=svc, branch_id=branch_id,
                               slot_at=slot, doctor_id=did,
                               conversation_id=conversation.id, created_by="ai",
                               hold_minutes=resolved_hold)
            conversation.status = "booked"
            conversation.sales_stage = "booking"
            if customer:
                customer.pipeline_stage = "booked"
            return b

        booking, lost = claim_slot(db, clinic_id=clinic_id, branch_id=branch_id,
                                   slot_at=slot, service_id=svc.id, doctor_id=did,
                                   write=_write)
        if booking is None:
            return _slot_taken_result(slot, lost)
        send_booking_email_async(booking.id)  # after commit — emailer opens its own session
        ptype = args.get("payment_type") if args.get("payment_type") in ("full", "deposit") else "deposit"
        res = {"booked": True, "booking_id": booking.id, "treatment": svc.name,
               "when": slot.strftime("%d %b %Y, %H:%M"),
               "price": f"฿{int(booking.price):,}",
               "deposit": f"฿{int(booking.deposit_required):,}"}
        if doctor:
            res["doctor"] = doctor.name
        # The hold, stated as BOTH a duration and a clock time. "ถึงเวลา 00:05 น." alone is
        # ambiguous for a booking held at 23:55; "ภายใน 10 นาที" never is — and this app
        # really is used at that hour (see tests/test_availability_reason.py).
        until = f"{booking.hold_expires_at:%H:%M}" if booking.hold_expires_at else ""
        if until:
            res.update({"hold_minutes": resolved_hold, "hold_until": until,
                        "hold_expires_at": booking.hold_expires_at.isoformat()})
        # create_booking applies an active promotion automatically, while list_treatments
        # deliberately does not (promotions are only offered when the customer asks). So
        # the booked price can undercut the figure they just agreed to — good news, but
        # silently changing an agreed number is the same fault as silently raising one.
        # Say the discount out loud instead.
        if booking.promo_id and int(booking.price) != int(quoted_price or 0):
            promo = db.get(models.Promotion, booking.promo_id)
            res.update({
                "promo_applied": promo.title if promo else "",
                "price_before_promo": f"฿{int(quoted_price):,}",
                "promo_say_it_like": (
                    f"มีโปรโมชั่น {promo.title if promo else 'ส่วนลด'} ใช้ได้พอดีค่ะ "
                    f"ราคาจึงลดจาก ฿{int(quoted_price):,} เหลือ ฿{int(booking.price):,} "
                    f"และมัดจำเหลือ ฿{int(booking.deposit_required):,} ค่ะ"),
                "promo_say_it_like_en": (
                    f"The {promo.title if promo else 'current'} promotion applies, so the "
                    f"price comes down from ฿{int(quoted_price):,} to ฿{int(booking.price):,} "
                    f"and the deposit to ฿{int(booking.deposit_required):,}."),
                "promo_note": "The booked price is LOWER than the figure the customer agreed "
                              "to, because a promotion applied automatically. Say so with "
                              "promo_say_it_like before the payment instructions - never let "
                              "an agreed number change without telling them, even in their "
                              "favour, and never present the drop as something you negotiated.",
            })
        # Auto-issue THIS booking's own payment QR (matching what the customer chose:
        # full or deposit) so every booking gets a payment prompt — even when the
        # customer already paid for an earlier booking.
        try:
            from app.services.billing import create_payment
            payment = create_payment(db, booking=booking, ptype=ptype)
            qr = _qr_payment(payment, ptype, _booking_line(db, booking))
            if qr:
                if booking.hold_expires_at:
                    qr["hold_expires_at"] = booking.hold_expires_at.isoformat()
                res.update({**qr,
                            "hold_say_it_like": (
                                f"ตอนนี้ระบบถือคิวนี้ไว้ให้ {resolved_hold} นาที ถึงเวลา {until} น. ค่ะ "
                                "หากเลยเวลานี้แล้วยังไม่ได้ชำระ ระบบจะปล่อยคิวนี้ให้ลูกค้าท่านอื่นค่ะ"),
                            "hold_say_it_like_en": (
                                f"We're holding this slot for {resolved_hold} minutes, until "
                                f"{until}. If it isn't paid by then the slot is released for "
                                "other customers."),
                            "note": (f"The slot is HELD until {until}, NOT confirmed. Say "
                                     "hold_say_it_like (deadline included: the hold IS the "
                                     "reason to pay now), then " + qr["note"] + " Do not call "
                                     "the booking confirmed or secured while it is unpaid.")})
            else:
                res.update({"hold_say_it_like": (
                                f"ตอนนี้ระบบถือคิวนี้ไว้ให้ {resolved_hold} นาที ถึงเวลา {until} น. ค่ะ "
                                "หากเลยเวลานี้แล้วยังไม่ได้ชำระ ระบบจะปล่อยคิวนี้ให้ลูกค้าท่านอื่นค่ะ"),
                            "hold_say_it_like_en": (
                                f"We're holding this slot for {resolved_hold} minutes, until "
                                f"{until}. If it isn't paid by then the slot is released for "
                                "other customers."),
                            "note": (f"The slot is HELD until {until}, not confirmed. Say "
                                     "hold_say_it_like, then call create_payment_link with "
                                     f"type=\"{ptype}\" to collect THIS booking's payment "
                                     "(every booking needs its own, even if an earlier one "
                                     "was already paid).")})
        except Exception as exc:  # pragma: no cover
            print("[tools] auto payment QR error:", exc)
            res["note"] = (f"The slot is HELD until {until}, not confirmed. Now call "
                           f"create_payment_link with type=\"{ptype}\".")
        return res

    if name == "reschedule_appointment":
        if not customer:
            return {"error": "No customer on this conversation."}
        now = _now_local()
        # The customer's upcoming bookings (soonest first); optionally narrow by treatment.
        bookings = (scoped(db, models.Booking, clinic_id).filter_by(customer_id=customer.id)
                    .filter(models.Booking.status.in_(["pending", "confirmed"]),
                            models.Booking.slot_at > now)
                    .order_by(models.Booking.slot_at.asc()).all())
        if args.get("treatment"):
            svc_pick = _find_service(db, args.get("treatment"), clinic_id)
            if svc_pick:
                bookings = [b for b in bookings if b.service_id == svc_pick.id]
        if not bookings:
            return {"error": "No upcoming booking to reschedule."}
        booking = bookings[0]
        # 24-hour policy: only move it when there are still MORE than 24 hours to go.
        if booking.slot_at - now < timedelta(hours=24):
            return {"too_late": True,
                    "note": "This appointment is less than 24 hours away, so it cannot be "
                            "rescheduled here. Apologise, tell the customer to contact the clinic "
                            "directly, and use request_human_help to hand off."}
        try:
            new_slot = datetime.fromisoformat(f"{args['date']}T{args['time']}")
        except Exception:
            return {"error": "Invalid date/time. Use date YYYY-MM-DD and time HH:MM."}
        # exclude the booking itself so it can move within its own day; keep its
        # doctor conflict-checked at the new time. service_id travels too, or a 90-minute
        # treatment can be moved into a 30-minute gap — the check only knows how long the
        # chair is needed for when it is told which treatment.
        if new_slot not in available_slots(db, booking.branch_id, new_slot,
                                           service_id=booking.service_id,
                                           doctor_id=booking.doctor_id,
                                           exclude_booking_id=booking.id):
            return {"error": "That new time isn't available — call check_availability first and "
                             "pick one of the exact open slots it returns."}
        svc = db.get(models.Service, booking.service_id)
        sname = svc.name if svc else "treatment"
        old = booking.slot_at

        def _move():
            booking.slot_at = new_slot
            db.add(models.Activity(
                clinic_id=clinic_id, customer_id=customer.id, type="booking",
                summary=f"Rescheduled {sname} from {old:%d %b %H:%M} to {new_slot:%d %b %H:%M}",
                ref_type="booking", ref_id=booking.id))
            return booking

        moved, lost = claim_slot(db, clinic_id=clinic_id, branch_id=booking.branch_id,
                                 slot_at=new_slot, service_id=booking.service_id,
                                 doctor_id=booking.doctor_id,
                                 exclude_booking_id=booking.id, write=_move)
        if moved is None:
            return {"error": ("That new time was taken while we were moving the appointment."
                              if lost == SLOT_TAKEN else
                              "That new time isn't available.")
                             + " The appointment has NOT moved and is still at its original "
                               "time. Call check_availability and offer the customer another."}
        realtime.publish({"type": "booking", "booking_id": booking.id, "clinic_id": clinic_id})
        send_booking_email_async(booking.id, kind="reschedule")
        return {"rescheduled": True, "booking_id": booking.id, "treatment": sname,
                "from": old.strftime("%d %b %Y, %H:%M"),
                "to": new_slot.strftime("%d %b %Y, %H:%M"),
                "note": "Confirm the new date and time. The existing deposit carries over, so do "
                        "NOT ask for a new payment."}

    if name == "create_payment_link":
        if not customer:
            return {"error": "No customer on this conversation."}
        from app.ai.guardrails import booking_belongs_to
        from app.services.billing import _paid_total_for_booking, create_payment

        live = (scoped(db, models.Booking, clinic_id).filter_by(customer_id=customer.id)
                .filter(models.Booking.status.in_(["pending", "confirmed"]))
                .order_by(models.Booking.id.desc()).all())
        if not live:
            # A hold that lapsed is not "no booking". Saying so to someone who booked
            # forty minutes ago and is now clicking pay contradicts what they just did,
            # and leaves the model to invent a reason.
            lapsed = (scoped(db, models.Booking, clinic_id).filter_by(customer_id=customer.id)
                      .filter(models.Booking.status == EXPIRED,
                              models.Booking.hold_expires_at.isnot(None),
                              models.Booking.hold_expires_at >= _now_local() - timedelta(days=1))
                      .order_by(models.Booking.id.desc()).first())
            if lapsed:
                return _hold_expired_result(db, lapsed)
            return {"error": "No pending booking — book an appointment first."}
        booking = _booking_being_paid(db, conversation, customer, live, args.get("treatment"))
        if booking is None:
            # Two bookings, and nothing says which one they mean. Guessing "the newest"
            # is what told a customer their HIFU was paid in full when the figure came
            # from a DIFFERENT booking they had settled minutes earlier.
            return {"need_which_booking": [_booking_line(db, b) for b in live],
                    "note": "This customer has more than one live booking and it is not clear "
                            "which one they want to pay for. Ask which treatment, naming them, "
                            "then call this tool again with `treatment` set. Do NOT guess, and "
                            "do NOT quote a paid/outstanding amount until you know which one."}

        # Ownership guardrail: only ever act on the customer's OWN booking.
        if not booking_belongs_to(booking, customer):
            return {"error": "That booking is not this customer's — do not send the QR."}
        ptype = args.get("type") if args.get("type") in ("full", "deposit") else "deposit"
        payment = create_payment(db, booking=booking, ptype=ptype)
        which = _booking_line(db, booking)
        # Only confirm 'already paid' for a payment that genuinely belongs to THIS
        # customer (defence against a stale/foreign match even if scoping regressed).
        if payment and payment.status == "paid" and payment.customer_id == customer.id:
            return {"already_paid": True, "booking": which,
                    "paid_total": f"฿{int(_paid_total_for_booking(db, booking)):,}",
                    "note": f"The {ptype} for {which} is already paid — do NOT ask for it "
                            "again. Name THAT treatment when you say so: this customer has other "
                            "bookings, and saying it about the wrong one tells them a bill is "
                            "settled when it is not."}
        qr = _qr_payment(payment, ptype, which)
        if not qr:
            return {"error": "No payment QR is set up for this clinic.",
                    "note": "Tell the customer the team will contact them to arrange payment, "
                            "and call request_human_help. Do not invent a way to pay."}
        # The pay-card's live countdown reads this — a lapsed hold isn't "no booking"
        # (see the lapsed-hold branch above), so only a still-live hold gets one.
        if booking.status == "pending" and booking.hold_expires_at:
            qr["hold_expires_at"] = booking.hold_expires_at.isoformat()
        return qr

    if name == "request_human_help":
        conversation.escalation_reason = (args.get("reason") or "Customer asked for a person")[:240]
        db.commit()
        return {"ok": True, "note": "A clinic team member will join the chat shortly."}

    return {"error": f"unknown tool {name}"}
