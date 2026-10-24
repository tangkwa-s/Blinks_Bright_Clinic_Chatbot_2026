"""Runtime guardrails — defence-in-depth checks on the AI's actions and replies.

These COMPLEMENT (do not replace) the deterministic booking/pricing logic and the
grounding guard. They target the three failure modes that hurt most in a clinic:

  - payment_claim_ok   never tell a customer their payment is done unless it really is
  - booking_belongs_to a payment action must target the customer's OWN booking
  - undercuts_catalog  flag a quoted price below the catalog/promo floor (unauthorised discount)

All functions are small + pure-ish so they are easy to unit-test.
"""
import re

from app import models
from app.scope import scoped

# Phrases that assert a payment / deposit has actually gone through. The gap after
# "ชำระ"/"จ่าย" is a bounded char class (not a fixed word list) so any qualifier —
# เงิน, มัดจำ, เต็มจำนวน, ค่าทรีตเมนต์ — in front of เรียบร้อย/สำเร็จ/แล้ว is caught.
    # The gap must not swallow a negator: "ชำระเงินไม่สำเร็จ" ("creating the payment
    # link FAILED") once matched "ชำระ…สำเร็จ" because "ไม่" sat inside [^.\n]{0,12},
    # so the assistant honestly reporting a failure was flagged as claiming the
    # payment was done. ``(?:(?!ไม่)[^.\n])`` is the same gap, tempered to stop at "ไม่".
_PAID_CLAIM_RE = re.compile(
    r"ชำระ(?:(?!ไม่)[^.\n]){0,12}(?:เรียบร้อย|สำเร็จ|แล้ว)"
    r"|จ่าย(?:(?!ไม่)[^.\n]){0,12}(?:เรียบร้อย|สำเร็จ|แล้ว)"
    r"|มัดจำ(?:(?!ไม่)[^.\n]){0,24}(?:ชำระ|จ่าย)(?:(?!ไม่)[^.\n]){0,14}(?:เรียบร้อย|แล้ว)"
    r"|ได้รับ(?:การ)?ชำระ"
    r"|ไม่ต้องชำระเพิ่ม"
    r"|already\s+paid"
    r"|payment\b(?:(?!\bnot\b|\bun)[^.\n]){0,20}(?:received|confirmed|complete|completed|successful)"
    r"|(?:received|confirmed|completed)\b[^.\n]{0,12}\bpayment",
    re.IGNORECASE)

# A conditional/future lead-in right before the match ("ถ้าชำระแล้ว" = "once you've
# paid", "หากชำระเรียบร้อย" = "if payment is complete") means the sentence is NOT
# claiming payment already happened — it's telling the customer what to do next.
_CONDITIONAL_LEADIN_RE = re.compile(r"(?:ถ้า|หาก|เมื่อ|once)\s*$", re.IGNORECASE)

# A NEGATED lead-in inverts the phrase: "ระบบยังไม่แสดงว่าได้รับชำระ" ("the system
# does not show the payment as received") is the assistant correctly REFUSING to
# confirm — the exact behaviour we want — yet it contains "ได้รับชำระ". Without
# this the guardrail flagged its own desired answer, so a correct reply was
# reported as a false payment claim. The negator may sit a few words back
# ("ยังไม่แสดงว่า" + "ได้รับชำระ"), hence the wider window than the conditional one.
_NEGATED_LEADIN_RE = re.compile(
    r"(?:ยังไม่|ไม่|ไม่พบ|ไม่แสดง|ยังไม่มี|ยังรอ|รอการ"
    r"|not\s+yet|not|no\b|hasn'?t|haven'?t|unable\s+to|cannot|can'?t)"
    r"[^.\n]{0,16}$", re.IGNORECASE)


def claims_payment_done(text: str) -> bool:
    """True if the reply tells the customer a payment/deposit is already settled.

    A conditional lead-in ("ถ้าชำระแล้ว" / "once paid") or a negated one
    ("ยังไม่ได้รับชำระ" / "not yet received") is not a claim — it is the assistant
    telling the customer what still has to happen.
    """
    text = text or ""
    for m in _PAID_CLAIM_RE.finditer(text):
        lead_in = text[max(0, m.start() - 30):m.start()]
        if _CONDITIONAL_LEADIN_RE.search(lead_in) or _NEGATED_LEADIN_RE.search(lead_in):
            continue
        return True
    return False


def customer_has_paid(db, clinic_id, customer_id) -> bool:
    if not customer_id:
        return False
    return (scoped(db, models.Payment, clinic_id)
            .filter(models.Payment.customer_id == customer_id,
                    models.Payment.status == "paid").first() is not None)


def payment_claim_ok(db, conversation, customer, reply: str) -> bool:
    """False ⇒ the reply claims the payment is done, but the DB has NO paid payment
    for this customer — i.e. a hallucinated / wrong confirmation that must be flagged."""
    if not claims_payment_done(reply):
        return True
    cust_id = (customer.id if customer else
               (conversation.customer_id if conversation else None))
    return customer_has_paid(db, conversation.clinic_id, cust_id)


def booking_belongs_to(booking, customer) -> bool:
    """A booking targeted by a payment link / charge must be the customer's own."""
    return bool(booking and customer and booking.customer_id == customer.id)


# Giveaway words. A reply may only contain one when the SAME word is in the grounding
# (a promotion list_promotions returned, a KB line, a teammate's message) or the customer
# raised it themselves. The model once ended a reply with a bare trailing "เครดิตฟรี" that
# corresponded to nothing in the clinic's data — grounding guard missed it because that
# check only looks at 3+ digit numbers.
_OFFER_WORDS = ("เครดิตฟรี", "ฟรี", "แถม", "ของแถม",
                "free credit", "free session", "complimentary", "free")


def unbacked_offers(reply: str, grounding: str, customer_text: str = "") -> list[str]:
    """Giveaway words the AI introduced that nothing in the clinic's data backs.

    Longest match wins, so a grounded "เครดิตฟรี" is not also reported as a bare "ฟรี".
    Returns the offending words (sorted), empty when the reply promises nothing new.
    """
    reply_l = (reply or "").lower()
    backed = ((grounding or "") + " " + (customer_text or "")).lower()
    found, covered = [], ""
    for word in sorted(_OFFER_WORDS, key=len, reverse=True):
        if word in reply_l and word not in backed and word not in covered:
            found.append(word)
            covered += " " + word
    return sorted(found)


def _prices(text: str, floor: int = 1000) -> set[int]:
    """3+ digit numbers that look like prices (>= floor), ignoring thousands commas."""
    out = set()
    for n in re.findall(r"\d{3,}", re.sub(r",", "", text or "")):
        v = int(n)
        if v >= floor:
            out.add(v)
    return out


def undercuts_catalog(reply: str, grounding: str, customer_text: str = "") -> list[int]:
    """Below-floor prices the *AI itself introduced* — a likely unauthorised discount.

    A price is flagged only when it is below the cheapest grounded price, is not itself
    grounded, AND was not a figure the CUSTOMER proposed (echoing the customer's number
    back while refusing is fine — whether the AI *agreed* to it is the judge's job, not
    this deterministic flag). Returns the offending amounts (sorted)."""
    grounded = _prices(grounding)
    if not grounded:
        return []
    floor = min(grounded)
    proposed = _prices(customer_text)        # numbers the customer raised
    return sorted(p for p in _prices(reply)
                  if p < floor and p not in grounded and p not in proposed)
