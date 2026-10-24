"""Sales intelligence — lead scoring, conversation analysis, CRM sync, escalation."""
import json
import re

from app import models
from app.ai import usage
from app.ai.client import chat_completion, is_configured
from app.config import settings
from app.scope import scoped

MEDICAL_WORDS = [
    "แพ้", "ผลข้างเคียง", "อันตราย", "บวมมาก", "ติดเชื้อ", "ไม่พอใจ", "ร้องเรียน", "ฟ้อง",
    "side effect", "allergic", "infection", "complication", "refund", "คืนเงิน", "lawyer",
]
STAGE_BONUS = {"new_lead": 0, "interested": 22, "booked": 48,
               "paid": 58, "followup": 50, "lost": -8}
INTENT_BONUS = {"high": 46, "medium": 24, "low": 2}

# --- contact capture: pull name / nickname / phone / email out of what a customer types ---
_PHONE_RE = re.compile(r"(?<!\d)(0\d[\d\-\s.]{7,12}\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PLACEHOLDER_NAMES = {"", "line user", "web visitor", "messenger user", "unknown",
                      "guest", "new lead", "ลูกค้า", "ผู้ใช้"}
# The second digit of every real Thai mobile number, whichever operator issued it. A
# Bangkok/provincial LANDLINE (02-xxx-xxxx, 9 digits) or plain garbage that merely
# starts with 0 is never one of these, even at the right length.
_MOBILE_PREFIXES = ("6", "8", "9")


def _is_valid_mobile_digits(digits: str) -> bool:
    """True only for a genuine Thai MOBILE number: exactly 10 digits, leading 0, second
    digit 6/8/9. A landline is still "0" + 9 digits and would pass a bare length check,
    which is exactly why this clinic's booking flow was accepting one as if it were a
    customer's own mobile."""
    return len(digits) == 10 and digits[0] == "0" and digits[1] in _MOBILE_PREFIXES


def _normalize_intl_prefix(text: str) -> str:
    """Fold a "+66" country code into the local leading-0 form BEFORE any other phone
    matching runs — whether the customer wrote it correctly, dropping the 0
    ("+66912345678"), or kept it by mistake ("+660912345678"); both name the same
    number. Without this, the kept-0 form was invisible to every check below: that 0
    sits immediately after "+66"'s own digits, so the lookbehind that (rightly) refuses
    to start a match in the middle of an unrelated digit run also blocked this genuine
    one — the customer's number was silently treated as if they had said nothing at
    all, which is worse than a wrong prefix or a missing digit, since no reason was
    ever given for it.
    """
    return re.sub(r"\+66[\s\-]?0?", "0", text or "")


def _extract_phone(text: str) -> str:
    """First Thai MOBILE number in free text, normalised to local 0XXXXXXXXX, else ''.

    A landline, or any digit run that merely starts with 0 but isn't a real mobile
    prefix, is deliberately NOT extracted here — see phone_problem for telling the
    customer why, instead of silently booking a number the clinic can never reach them
    on, or (worse) a fabricated wrong reason for refusing it.
    """
    text = _normalize_intl_prefix(text)
    for m in _PHONE_RE.finditer(text):
        d = re.sub(r"\D", "", m.group(1))
        if _is_valid_mobile_digits(d):
            return d
    return ""


def phone_problem(text: str) -> str:
    """Why the phone-shaped thing in ``text`` was not accepted: 'too_long', 'too_short',
    'invalid_prefix', or '' when there is a usable number (or nothing that looks like
    one at all).

    ``_extract_phone`` returns an empty string for both "they gave nothing" and "they
    gave 09545626666", and the whole system then behaved as if the customer had simply
    not answered: the assistant said "บันทึกเบอร์ 09545626666 ให้แล้วนะคะ", summarised the
    booking with it, and only at payment time refused — with no reason, so the customer
    had to ask "อ่าวทำไมอะคะ". The two cases are different facts and are told apart here.

    A THIRD case is the same species of bug: a number that is exactly 10 digits and
    starts with 0 but is a landline (02-xxx-xxxx, caught below as 9 real digits — see
    'too_short') or is simply not a real mobile prefix ("041-223-4444") was previously
    accepted as "fine" by a bare length check, so the model was left to notice something
    was wrong on its own and invented a reason — once, a genuinely 10-digit number was
    told back to the customer as "11 หลัก" (11 digits), a fabricated fact nobody could
    act on. 'invalid_prefix' names the real reason instead.
    """
    if _extract_phone(text):
        return ""
    for run in re.findall(r"(?<!\d)0[\d\-\s.]{4,}\d", _normalize_intl_prefix(text)):
        digits = re.sub(r"\D", "", run)
        if len(digits) > 10:
            return "too_long"
        if len(digits) < 10:
            return "too_short"
        if digits[1] not in _MOBILE_PREFIXES:
            return "invalid_prefix"
    return ""


def phone_digits(text: str) -> str:
    """The digits of the phone-shaped run in ``text`` — for quoting it back to them."""
    for run in re.findall(r"(?<!\d)0[\d\-\s.]{4,}\d", _normalize_intl_prefix(text)):
        return re.sub(r"\D", "", run)
    return ""


def format_thai_mobile(digits: str) -> str:
    """0XX-XXX-XXXX, the standard grouping for SAYING a number back to a customer.

    A number can arrive in the transcript in any shape the customer typed it in
    (unformatted, dashed, spaced, or with a +66 prefix the model was told to copy
    VERBATIM) — which once produced a booking summary reading "เบอร์โทร:
    +660911234567" as though that raw text were the clinic's own record. The DB
    (``Customer.phone``) already stores clean, unformatted digits (``_extract_phone``
    strips everything else); this is the one place that turns them back into the
    grouped form customers actually expect to read, so the model is never asked to
    reformat digits itself. Only ever called on a value that already passed
    ``_is_valid_mobile_digits``; anything else is returned unchanged rather than
    sliced into a misleading shape.
    """
    if len(digits) == 10 and digits.isdigit():
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    return digits


def phone_rejection_say_it_like(problem: str, digits: str) -> tuple[str, str]:
    """(Thai, English) sentence stating why a phone-shaped answer was not usable.

    Shared verbatim between ``tools.py::_phone_rejection`` (once the model has called
    a tool) and ``chat.py::_booking_hint`` (on the turn BEFORE it does, reading the
    number straight off the transcript) — a live check found the model would still
    paraphrase this on its own when only told the fact in prose (sometimes stating the
    wrong digit count, sometimes reverting to the "a Thai phone number has 10 digits"
    framing this wording deliberately drops), so both call sites now hand it this exact
    sentence to say rather than describing the situation and hoping.
    """
    if problem == "invalid_prefix":
        # Exactly 10 digits, starts with 0 — a bare length check called this "fine",
        # so the model had to notice on its own that something was wrong and invented
        # a reason (a genuinely 10-digit number was once told back as "11 หลัก"). This
        # covers a landline typed out to 10 digits and plain garbage alike; neither is
        # a real Thai mobile number, so there's one honest reason for both.
        th = (f"เบอร์ {digits} ไม่ใช่รูปแบบเบอร์มือถือไทยที่ถูกต้องค่ะ เบอร์มือถือไทยขึ้นต้นด้วย "
              "06, 08 หรือ 09 และมี 10 หลัก รบกวนตรวจสอบแล้วส่งมาอีกครั้งนะคะ")
        en = (f"{digits} isn't a valid Thai mobile number — Thai mobile numbers "
              "start with 06, 08, or 09 and have 10 digits. Could you check it and "
              "send it again?")
    else:
        long = problem == "too_long"
        # Just the fact (N digits, not 10) — no "a Thai phone number has 10 digits"
        # framing, which read like the assistant reciting a rule rather than pointing
        # out the problem with what was actually typed.
        th = (f"เบอร์ {digits} มี {len(digits)} หลักค่ะ "
              f"{'เกิน' if long else 'ไม่ครบ'} 10 หลัก รบกวนส่งมาอีกครั้งนะคะ")
        en = (f"{digits} has {len(digits)} digits, "
              f"{'more than' if long else 'not'} 10. Could you send it again?")
    return th, en


def _valid_email(s: str) -> bool:
    return bool(_EMAIL_RE.fullmatch((s or "").strip()))


def _extract_email(text: str) -> str:
    m = _EMAIL_RE.search(text or "")
    return m.group(0) if m else ""


def _is_placeholder_name(name: str) -> bool:
    """True when the stored name is a channel default we may safely replace."""
    return (name or "").strip().lower() in _PLACEHOLDER_NAMES


def unverified_identity_match(db, customer):
    """Another ACTIVE customer with the same phone — i.e. this account may be a
    returning customer writing from somewhere new... or someone who simply knows
    their number. Either way a person has to check before any booking is discussed,
    so this returns the record to compare against and the caller escalates.

    Deterministic on purpose: it keys off the captured phone, never off the AI's
    reading of the conversation, so an impersonator cannot phrase their way past it.
    """
    from app.services.inbox import phone_key

    key = phone_key(customer.phone if customer else "")
    if not key:
        return None
    for other in (scoped(db, models.Customer, customer.clinic_id)
                  .filter(models.Customer.id != customer.id,
                          models.Customer.merged_into_id.is_(None)).all()):
        if phone_key(other.phone) == key:
            return other
    return None


_SELF_ID_CUES = ("ชื่อ", "เรียก", "name is", "call me", "i'm ", "im ")


def _has_self_id_cue(msgs) -> bool:
    """True only when the transcript actually raises the topic of a name/nickname
    (customer states one, or someone asks for one). Guards against an LLM mistaking a
    greeting/opener/one-word reply (e.g. 'ดีจั๊ฟ', 'ไม่นะ') typed on a 'customer:' line
    for a self-introduction — without this, that bare text can slip past the
    verbatim-substring check below since it genuinely is what the customer typed."""
    return any(any(c in (m.text or "").lower() for c in _SELF_ID_CUES) for m in msgs)


def score_lead(db, customer, conversation, signals: dict | None = None) -> tuple[int, str]:
    """Deterministic 0-100 lead score → (score, temperature)."""
    signals = signals or {}
    cid = customer.clinic_id
    score = 8 + STAGE_BONUS.get(customer.pipeline_stage, 0)
    msg_count = (scoped(db, models.Message, cid)
                 .filter_by(conversation_id=conversation.id).count())
    score += min(msg_count * 3, 16)
    if customer.budget:
        score += 8
    score += INTENT_BONUS.get(signals.get("buying_intent"), 8)
    if scoped(db, models.Booking, cid).filter_by(customer_id=customer.id).count():
        score += 12
    # treatment value — interest in a higher-ticket treatment scores higher
    if customer.interested:
        il = customer.interested.lower()
        for s in scoped(db, models.Service, cid).all():
            sn = s.name.lower()
            if sn in il or il in sn or any(
                    w in il for w in sn.replace("—", " ").split() if len(w) > 3):
                score += 10 if s.base_price >= 20000 else 5 if s.base_price >= 8000 else 2
                break
    score = max(0, min(100, score))
    temp = "hot" if score >= 70 else "warm" if score >= 42 else "cold"
    return score, temp


ANALYSIS_PROMPT = """You analyse an aesthetic-clinic chat conversation. Read it and return ONLY a JSON object:
{
 "intent": "pricing|booking|promotion|service_info|prep_aftercare|complaint|greeting|other|unknown",
 "interested_service": "treatment name, or empty string",
 "customer_name": "the customer's real or full name, copied EXACTLY (same characters, same script, no translation/transliteration/romanization) from a 'customer:' line ONLY if they explicitly stated it as their name (e.g. 'ชื่อ...', 'หนูชื่อ...', 'my name is...'), else empty string. THE LATEST ONE WINS: if they state a name more than once, or correct one they gave earlier ('ชื่อผิดค่ะ ที่ถูกคือ ...', 'พิมพ์ผิด', 'ขอแก้ชื่อเป็น ...', 'sorry, it is ...'), return the name from their MOST RECENT such line and never the first one — a correction replaces what it corrects. A greeting, salutation, or casual opener ('สวัสดี', 'หวัดดีค่ะ', 'ดีจ้า', 'ดีจั๊ฟ', 'hi', 'hello', 'hey') is NOT a name even though it is the first thing they typed — leave this empty for those. Never take a name from an 'ai:' line, and never guess, shorten, or translate it.",
 "nickname": "the customer's nickname / ชื่อเล่น, copied EXACTLY (same characters, same script, no translation/transliteration/romanization) from a 'customer:' line ONLY if they explicitly stated it as their nickname (e.g. 'ชื่อเล่น...', 'เรียก...ก็ได้', 'call me...'), else empty string. THE LATEST ONE WINS here too: a corrected nickname replaces the one it corrects. A greeting, salutation, casual opener, or one-word reply ('สวัสดี', 'หวัดดีค่ะ', 'ดีจ้า', 'ดีจั๊ฟ', 'hi', 'hello', 'ไม่นะ', 'ok') is NOT a nickname — leave this empty for those, even if it was literally what they typed. Never take a nickname from an 'ai:' line (i.e. how the assistant addressed them does not count), and never invent, shorten, or translate one yourself.",
 "phone": "the customer's phone number if they gave one, else empty string",
 "email": "the customer's email address if they gave one, else empty string",
 "budget": "budget the customer mentioned, or empty string",
 "concern": "beauty concern the customer mentioned, or empty string",
 "sentiment": "positive|neutral|negative",
 "buying_intent": "low|medium|high",
 "needs_human": true or false,
 "human_reason": "short reason if needs_human, else empty string",
 "objection": "the customer's objection if they raised one (price too high, hesitation, timing, trust), else empty string",
 "summary": "1-2 short sentences IN THAI (ภาษาไทย): what the customer wants, where the conversation stands now, and the next step"
}"""


def analyze(db, conversation) -> dict:
    """Post-reply analysis — extract signals, sync CRM, score, log intent, escalate."""
    customer = db.get(models.Customer, conversation.customer_id)
    if not customer:
        return {}
    msgs = (scoped(db, models.Message, conversation.clinic_id)
            .filter_by(conversation_id=conversation.id)
            .order_by(models.Message.created_at).all())
    transcript = "\n".join(f"{m.sender}: {m.text}" for m in msgs[-16:] if m.sender != "system")

    signals: dict = {}
    if is_configured() and transcript:
        try:
            resp = chat_completion(
                [{"role": "system", "content": ANALYSIS_PROMPT},
                 {"role": "user", "content": transcript}],
                temperature=0.1, max_tokens=480, response_format={"type": "json_object"})
            signals = json.loads(resp.choices[0].message.content or "{}")
            u = getattr(resp, "usage", None)
            if u:
                usage.record(customer.clinic_id, "analyze", settings.chat_model,
                             getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
        except Exception as exc:  # pragma: no cover
            print("[sales] analysis error:", exc)

    # --- running conversation summary (inbox side panel) ---
    summary = (signals.get("summary") or "").strip()
    if summary:
        conversation.ai_summary = summary[:500]

    # --- CRM sync ---
    if signals.get("interested_service"):
        customer.interested = signals["interested_service"]
    if signals.get("budget"):
        customer.budget = signals["budget"]
    if signals.get("concern"):
        customer.concern = signals["concern"]

    # --- contact capture: name / nickname / phone / email straight from the chat ---
    captured = []
    cust_msgs = [m.text or "" for m in msgs if m.sender == "customer"]
    cust_text = " ".join(cust_msgs)
    # NEWEST message first. Scanning the whole transcript as one string returned the
    # FIRST phone the customer ever typed, so "บอกเบอร์ผิดครับ 0922222222" was ignored —
    # worse, this runs after book_appointment has already saved the corrected number,
    # so it actively put the wrong one back and the profile kept the typo.
    phone = next((p for p in (_extract_phone(t) for t in reversed(cust_msgs)) if p), "") \
        or _extract_phone(signals.get("phone", ""))
    if phone and phone != (customer.phone or ""):
        customer.phone = phone
        captured.append("phone")
    email = next((e for e in (_extract_email(t) for t in reversed(cust_msgs)) if e), "") \
        or (signals.get("email") or "").strip()
    if email and _valid_email(email) and email.lower() != (customer.email or "").lower():
        customer.email = email
        captured.append("email")
    # Defence-in-depth: only accept a name/nickname the LLM claims the customer typed if
    # (a) those exact characters actually appear in the customer's own messages — blocks
    # a hallucinated or translated/transliterated name (e.g. the model quietly
    # "translating" a foreign display name) — and (b) the transcript actually raises the
    # topic of a name/nickname at all — blocks a greeting/opener/one-word reply that
    # technically appears verbatim in the customer's text but isn't a self-introduction.
    id_cue = _has_self_id_cue(msgs)
    nick = (signals.get("nickname") or "").strip()
    if (nick and id_cue and nick.lower() in cust_text.lower()
            and nick.lower() != (customer.nickname or "").lower()):
        customer.nickname = nick[:120]
        captured.append("nickname")
    real_name = (signals.get("customer_name") or "").strip()
    if (real_name and id_cue and real_name.lower() in cust_text.lower()
            and real_name.lower() != (customer.name or "").lower()):
        # The customer explicitly stated their name, so use it. The old name is NOT
        # promoted to nickname: web_start (public, unauthenticated) accepts any
        # client-supplied string as the name, so it was never a nickname anyone chose,
        # and a name they typed themselves and are now replacing is a correction —
        # keeping it would leave the typo in `nickname`, which the assistant uses to
        # address them.
        customer.name = real_name[:120]
        if "name" not in captured:
            captured.append("name")
    if captured:
        db.add(models.Activity(
            clinic_id=conversation.clinic_id, customer_id=customer.id, type="note",
            summary="AI captured from chat: " + ", ".join(captured)))

    # --- lead score ---
    customer.lead_score, customer.temperature = score_lead(db, customer, conversation, signals)

    # --- sales stage / pipeline ---
    intent = signals.get("intent", "")
    buying = signals.get("buying_intent", "")
    if conversation.status not in ("booked", "paid"):
        engaged = (intent in ("pricing", "promotion", "service_info", "booking")
                   or buying in ("medium", "high"))
        if intent == "booking" or buying == "high":
            conversation.sales_stage = "booking"
        elif engaged:
            conversation.sales_stage = "recommending"
        if engaged and customer.pipeline_stage == "new_lead":
            customer.pipeline_stage = "interested"
            conversation.status = "interested"

    # --- intent logging (unknown / unclassified) ---
    if intent in ("unknown", "other") or signals.get("needs_human"):
        last_q = next((m.text for m in reversed(msgs) if m.sender == "customer"), "")
        if last_q:
            db.add(models.IntentLog(
                clinic_id=conversation.clinic_id,
                conversation_id=conversation.id, question=last_q[:500],
                predicted_intent=intent or "unknown",
                confidence=0.3 if intent in ("unknown", "other") else 0.6))

    # --- objection logging (for AI analytics) ---
    objection = (signals.get("objection") or "").strip()
    if objection:
        db.add(models.IntentLog(clinic_id=conversation.clinic_id,
                                conversation_id=conversation.id, question=objection[:300],
                                predicted_intent="objection", confidence=0.5))

    # --- escalation ---
    last_customer = next((m.text for m in reversed(msgs) if m.sender == "customer"), "").lower()
    reason = ""
    serious = False
    twin = unverified_identity_match(db, customer) if "phone" in captured else None
    if any(w in last_customer for w in MEDICAL_WORDS):
        reason, serious = "Possible medical concern or complaint — needs a human.", True
    elif twin:
        # A new account gave a phone the clinic already holds. It is probably the same
        # person on a new device, but nothing here proves that, so a human verifies
        # identity before any booking of the existing record is discussed or merged.
        reason = (f"Same phone as existing customer “{twin.name}” (#{twin.id}) — verify "
                  "identity before discussing or merging their bookings.")
    elif signals.get("needs_human"):
        # A flag for the inbox, NOT a pause: this fires on "the AI didn't know" (a doctor
        # it has no record of), and pausing there left the customer typing into a chat
        # nobody answered until someone pressed Return to AI.
        reason = signals.get("human_reason") or "The AI flagged this for a human."
    elif signals.get("sentiment") == "negative":
        reason = "Customer sentiment turned negative."
    elif customer.lead_score >= 80:
        reason = "VIP / high-value lead — worth a personal touch."
    else:
        last_ai = next((m for m in reversed(msgs) if m.sender == "ai"), None)
        if last_ai and not (last_ai.meta or {}).get("grounded", True):
            reason = "AI reply may not be fully grounded — please review."

    if reason and not conversation.escalation_reason:
        conversation.escalation_reason = reason[:240]
        if serious:
            conversation.ai_enabled = False
            db.add(models.Message(clinic_id=conversation.clinic_id,
                                  conversation_id=conversation.id, sender="system",
                                  text=f"⚠ Escalated to a human — {reason}"))
            db.commit()
            # the system note above is staff-only; the customer must hear it too
            from app.services.inbox import notify_waiting_for_staff
            notify_waiting_for_staff(db, conversation, handoff=True)

    db.commit()
    return signals
