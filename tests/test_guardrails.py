"""Tests for app/ai/guardrails.py — the runtime safety checks.

Covers the three critical guardrails:
  - payment confirmation (never claim a payment is done unless it really is)
  - booking ownership    (a payment action targets only the customer's own booking)
  - discount floor        (flag a quoted price below the catalog/promo floor)
"""
from datetime import datetime

from app import models
from app.ai import guardrails


# --------------------------- payment confirmation ---------------------------
def test_claims_payment_done_detects_thai_and_english():
    assert guardrails.claims_payment_done("ชำระเงินเรียบร้อยแล้วค่ะ")
    assert guardrails.claims_payment_done("มัดจำของนัดนี้ชำระเรียบร้อยแล้ว ไม่ต้องชำระเพิ่ม")
    assert guardrails.claims_payment_done("จ่ายเงินสำเร็จแล้วนะคะ")
    assert guardrails.claims_payment_done("Your payment was received")
    assert guardrails.claims_payment_done("already paid")


def test_claims_payment_done_ignores_neutral_text():
    # offering / asking to pay is NOT a confirmation
    assert not guardrails.claims_payment_done("รบกวนชำระมัดจำ ฿600 เพื่อยืนยันคิวนะคะ")
    assert not guardrails.claims_payment_done("ส่งลิงก์ชำระเงินให้ได้เลยค่ะ")
    assert not guardrails.claims_payment_done("สวัสดีค่ะ สนใจ Botox ไหมคะ")


def test_claims_payment_done_ignores_negated_and_conditional_phrasing():
    """Telling the customer a payment has NOT arrived is the desired refusal, not a
    claim — the flag used to fire on the assistant's own correct answer because
    "ยังไม่แสดงว่าได้รับชำระ" contains "ได้รับชำระ"."""
    assert not guardrails.claims_payment_done(
        "ตอนนี้ระบบยังไม่แสดงว่าได้รับชำระมัดจำแล้วนะคะ ทีมจะตรวจสอบให้ค่ะ")
    assert not guardrails.claims_payment_done("ระบบยังไม่ได้รับชำระเงินค่ะ")
    assert not guardrails.claims_payment_done("เรายังไม่พบการชำระเงินนะคะ")
    assert not guardrails.claims_payment_done("We have not yet received payment")
    assert not guardrails.claims_payment_done("ถ้าชำระเรียบร้อยแล้ว แจ้งได้เลยค่ะ")
    # a real confirmation still trips it
    assert guardrails.claims_payment_done("ได้รับชำระเงินเรียบร้อยแล้วค่ะ")


def test_claims_payment_done_ignores_failure_reports():
    """Reporting that payment/link creation FAILED is the opposite of a claim. The
    negator sits inside the phrase ("ชำระเงิน-ไม่-สำเร็จ"), so the match gap itself
    has to stop at "ไม่" — otherwise honest error handling was flagged."""
    assert not guardrails.claims_payment_done(
        "ตอนนี้ระบบสร้างลิงก์ชำระเงินไม่สำเร็จ เดี๋ยวทีมจะช่วยตรวจสอบให้นะคะ")
    assert not guardrails.claims_payment_done("ระบบยังสร้างลิงก์ชำระเงินไม่ได้ค่ะ")
    assert not guardrails.claims_payment_done("The payment was not successful")
    # and the genuine success wording is still caught
    assert guardrails.claims_payment_done("ชำระเงินสำเร็จแล้วค่ะ")


def _setup_customer(db, make_clinic):
    clinic = make_clinic()
    cust = models.Customer(clinic_id=clinic.id, name="A", channel="web", channel_user_id="w1")
    db.add(cust)
    db.flush()
    conv = models.Conversation(clinic_id=clinic.id, customer_id=cust.id, channel="web")
    db.add(conv)
    db.commit()
    return clinic, cust, conv


def test_payment_claim_blocked_when_no_paid_payment(db, make_clinic):
    """The reply claims paid but there is NO paid payment → guardrail says NOT ok."""
    _clinic, cust, conv = _setup_customer(db, make_clinic)
    assert guardrails.payment_claim_ok(db, conv, cust, "ชำระมัดจำเรียบร้อยแล้วค่ะ") is False


def test_payment_claim_ok_with_a_real_paid_payment(db, make_clinic):
    clinic, cust, conv = _setup_customer(db, make_clinic)
    db.add(models.Payment(clinic_id=clinic.id, customer_id=cust.id, type="deposit",
                          amount=600, status="paid"))
    db.commit()
    assert guardrails.payment_claim_ok(db, conv, cust, "ชำระมัดจำเรียบร้อยแล้วค่ะ") is True


def test_payment_claim_ok_when_reply_makes_no_claim(db, make_clinic):
    _clinic, cust, conv = _setup_customer(db, make_clinic)
    # no paid payment, but the reply doesn't claim one → fine
    assert guardrails.payment_claim_ok(db, conv, cust, "รบกวนชำระมัดจำเพื่อยืนยันคิวนะคะ") is True


def test_payment_claim_pending_payment_is_not_enough(db, make_clinic):
    """A pending (unpaid) payment must NOT satisfy a 'paid' claim."""
    clinic, cust, conv = _setup_customer(db, make_clinic)
    db.add(models.Payment(clinic_id=clinic.id, customer_id=cust.id, type="deposit",
                          amount=600, status="pending"))
    db.commit()
    assert guardrails.payment_claim_ok(db, conv, cust, "จ่ายเงินเรียบร้อยแล้วค่ะ") is False


# ------------------------------ booking ownership ---------------------------
def test_booking_belongs_to_own_customer():
    cust = models.Customer(id=5, name="A")
    own = models.Booking(customer_id=5)
    other = models.Booking(customer_id=9)
    assert guardrails.booking_belongs_to(own, cust) is True
    assert guardrails.booking_belongs_to(other, cust) is False
    assert guardrails.booking_belongs_to(None, cust) is False
    assert guardrails.booking_belongs_to(own, None) is False


# ------------------------------- discount floor -----------------------------
def test_undercuts_catalog_flags_below_floor_price():
    grounding = 'Treatment Skin Booster price from 7,900. HIFU price from 25,000.'
    # the model invented a 3,000 price (a discount below the 7,900 floor)
    assert guardrails.undercuts_catalog("ลดให้เหลือ 3,000 บาทค่ะ", grounding) == [3000]


def test_undercuts_catalog_allows_grounded_and_higher_prices():
    grounding = 'price from 7,900. price 25,000.'
    # quoting a grounded price, or a higher number, is fine
    assert guardrails.undercuts_catalog("ราคา 7,900 ค่ะ", grounding) == []
    assert guardrails.undercuts_catalog("HIFU 25,000 ค่ะ", grounding) == []
    assert guardrails.undercuts_catalog("แพ็กเกจ 30,000 ค่ะ", grounding) == []


def test_undercuts_catalog_ignores_small_numbers():
    """Durations / intervals (< 1000) are not treated as discounted prices."""
    grounding = 'price from 7,900. interval every 30 days. 45 minutes.'
    assert guardrails.undercuts_catalog("ใช้เวลา 30 นาที ทำทุก 30 วันค่ะ", grounding) == []


def test_undercuts_catalog_no_grounding_no_flag():
    assert guardrails.undercuts_catalog("ลดเหลือ 3,000 ค่ะ", "") == []


def test_undercuts_catalog_ignores_customer_proposed_price():
    """Echoing the customer's own below-floor number while refusing is NOT a flag;
    a price the AI invents on its own (customer never said it) still is."""
    grounding = "HIFU price from 25,000. Signature Facial 2,800."
    customer = "ขอ HIFU ราคา 1500 ได้ไหม"
    refuse = "ขออภัยค่ะ ราคา HIFU เริ่มต้น 25,000 ไม่สามารถลดเหลือ 1,500 ได้ค่ะ"
    assert guardrails.undercuts_catalog(refuse, grounding, customer) == []
    assert guardrails.undercuts_catalog("ลดให้พิเศษเหลือ 1,200 ค่ะ", grounding, "สนใจ HIFU ค่ะ") == [1200]


# ----------------------------- grounding guard -----------------------------
def test_grounding_guard_exempts_calendar_years():
    """A booking summary naturally contains its own appointment year (2026 CE /
    2569 BE); when the model correctly reuses availability from an earlier turn,
    no tool result in the current turn carries that year — so correct summaries
    were flagged. Years are exempt; real ungrounded prices still flag."""
    from app.ai.guard import check
    ok = check("นัดวันที่ 1 ส.ค. 2026 เวลา 11:00 ราคา 2,800 บาท", "Signature Facial ฿2,800")
    assert ok["grounded"], ok
    ok = check("วันที่ 5 พ.ศ. 2569 ค่ะ ราคา 2,800", "฿2,800")
    assert ok["grounded"], ok
    bad = check("ราคาพิเศษ 1,999 บาทค่ะ", "฿2,800")
    assert not bad["grounded"] and bad["unsupported"] == ["1999"]


# ------------------------------ unbacked offers ------------------------------
def test_unbacked_offers_flags_a_giveaway_nothing_backs():
    """The reported slip: a reply ended with a bare "เครดิตฟรี" that matched nothing in
    the clinic's data. The grounding guard cannot see it — it only reads 3+ digit numbers."""
    reply = "คุณแพรสนใจ HIFU Lifting อยู่ใช่ไหมคะ เครดิตฟรี"
    grounding = "HIFU Lifting ราคาเริ่มต้น 27,000 บาท"
    assert guardrails.unbacked_offers(reply, grounding) == ["เครดิตฟรี"]


def test_unbacked_offers_accepts_a_real_promotion():
    """A giveaway list_promotions actually returned is legitimate — no flag."""
    reply = "ตอนนี้มีโปรวิเคราะห์ผิวฟรีสำหรับลูกค้าใหม่ค่ะ"
    grounding = '{"promotions": [{"title": "วิเคราะห์ผิวฟรี", "detail": "ลูกค้าใหม่"}]}'
    assert guardrails.unbacked_offers(reply, grounding) == []


def test_unbacked_offers_ignores_a_giveaway_the_customer_raised():
    """Echoing the customer's own word back while answering is not a promise."""
    reply = "ตอนนี้ยังไม่มีของแถมสำหรับรายการนี้ค่ะ"
    assert guardrails.unbacked_offers(reply, "HIFU 27,000", "มีของแถมไหมคะ") == []


def test_unbacked_offers_reports_the_longest_match_only():
    """A flagged "เครดิตฟรี" must not also be reported as a bare "ฟรี"."""
    assert guardrails.unbacked_offers("แถมเครดิตฟรีให้ค่ะ", "HIFU 27,000") == \
        ["เครดิตฟรี", "แถม"]


def test_unbacked_offers_quiet_on_an_ordinary_reply():
    assert guardrails.unbacked_offers("HIFU Lifting ราคา 27,000 บาทค่ะ", "HIFU 27,000") == []
