"""Regression tests for ``evals.checks.single_language``.

The eval harness itself needs the real model, but this check is pure logic and it
is the one that catches half-translated replies ("ติดต่อกลับ shortly ค่ะ"), which the
model produced by copying wording out of the English system prompt. Its allowlist
has to let through the things that are legitimately Latin inside a Thai sentence —
treatment/branch/doctor names, the customer's own name, a Stripe link — or it would
fail every booking case and get switched off.

(``evals/__init__`` only ``setdefault``s DB_PATH, so importing it here cannot steal
the throwaway DB conftest already bound.)
"""
from types import SimpleNamespace

from app import models
from evals.checks import ALWAYS_ON, matches_customer_language, single_language


def _ctx(db, clinic, text, turns=("สวัสดีค่ะ",)):
    return SimpleNamespace(db=db, clinic=clinic, turns=list(turns),
                           result={"text": text}, text=text, meta={})


def _service(db, clinic, name):
    s = models.Service(clinic_id=clinic.id, name=name, category="facial",
                       base_price=2800.0, active=True)
    db.add(s)
    db.commit()
    return s


def test_flags_english_left_inside_a_thai_reply(db, clinic):
    res = single_language()(_ctx(db, clinic, "ทางทีมจะตรวจสอบและติดต่อกลับ shortly ค่ะ 🙏"))
    assert res.ok is False
    assert "shortly" in res.detail


def test_passes_a_fully_thai_reply(db, clinic):
    assert single_language()(
        _ctx(db, clinic, "ทางทีมจะตรวจสอบและติดต่อกลับโดยเร็วที่สุดค่ะ")).ok is True


def test_treatment_and_branch_names_are_not_flagged(db, clinic):
    _service(db, clinic, "Signature Facial")
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    text = f"ที่สาขา {branch.name} มี Signature Facial ราคาเริ่มต้น ฿2,800 ค่ะ"
    assert single_language()(_ctx(db, clinic, text)).ok is True


def test_payment_link_is_not_mistaken_for_prose(db, clinic):
    text = ("กรุณาชำระมัดจำผ่านลิงก์นี้ค่ะ "
            "https://checkout.stripe.com/c/pay/cs_test_a1UdVo90OtGJI4wdz2etcfMTstG1Bk")
    assert single_language()(_ctx(db, clinic, text)).ok is True


def test_the_customers_own_name_is_kept_verbatim(db, clinic):
    """The prompt orders the AI to echo a name exactly as typed, so this check must
    not punish it for doing so."""
    ctx = _ctx(db, clinic, "ขอบคุณค่ะ คุณ Toy บันทึกให้แล้วนะคะ",
               turns=["ชื่อ Toy เบอร์ 0811111111"])
    assert single_language()(ctx).ok is True


def test_an_all_english_reply_is_left_alone(db, clinic):
    """English customers get English — the check only governs Thai replies."""
    assert single_language()(
        _ctx(db, clinic, "Our team will check your booking and get back to you shortly.")).ok is True


def test_stray_thai_in_an_english_reply_is_flagged(db, clinic):
    res = single_language()(
        _ctx(db, clinic, "Our team will check your booking and contact you ค่ะ",
             turns=["Could you check my booking?"]))
    assert res.ok is False
    assert "ค่ะ" in res.detail


# --------------------------------------------------------------------------
# matches_customer_language — Thai in, Thai out; English in, English out
# --------------------------------------------------------------------------
def test_thai_customer_must_get_thai(db, clinic):
    thai_turn = ["ราคาเท่าไหร่คะ"]
    assert matches_customer_language()(
        _ctx(db, clinic, "Signature Facial ราคาเริ่มต้น ฿2,800 ค่ะ", thai_turn)).ok is True
    assert matches_customer_language()(
        _ctx(db, clinic, "The Signature Facial starts at 2,800 baht.", thai_turn)).ok is False


def test_english_customer_must_get_english(db, clinic):
    en_turn = ["How much is the Signature Facial?"]
    assert matches_customer_language()(
        _ctx(db, clinic, "The Signature Facial starts at 2,800 baht.", en_turn)).ok is True
    assert matches_customer_language()(
        _ctx(db, clinic, "Signature Facial ราคาเริ่มต้น ฿2,800 ค่ะ", en_turn)).ok is False


def test_language_follows_the_latest_message(db, clinic):
    """A customer who opens in Thai and switches to English gets English."""
    turns = ["สวัสดีค่ะ", "Could you tell me about HIFU in English?"]
    assert matches_customer_language()(
        _ctx(db, clinic, "HIFU Lifting is a non-surgical lifting treatment.", turns)).ok is True


def test_a_scriptless_turn_does_not_decide_the_language(db, clinic):
    """"11:00" carries no script, so the Thai turn before it still rules."""
    turns = ["พรุ่งนี้ว่างกี่โมงคะ", "11:00"]
    assert matches_customer_language()(
        _ctx(db, clinic, "11:00 น. ว่างค่ะ", turns)).ok is True


def test_an_english_greeting_alone_still_expects_thai(db, clinic):
    """Thai customers open with "Hello" all the time — it is not a language choice."""
    assert matches_customer_language()(
        _ctx(db, clinic, "สวัสดีค่ะ 😊 สนใจทรีตเมนต์ไหนคะ", ["Hello"])).ok is True
    assert matches_customer_language()(
        _ctx(db, clinic, "Hello! How can I help you today?", ["Hello"])).ok is False


def test_always_on_carries_both_language_checks(db, clinic):
    """The harness appends ALWAYS_ON to every case; if it were empty they would
    silently never run."""
    names = {chk(_ctx(db, clinic, "ติดต่อกลับ shortly ค่ะ")).name for chk in ALWAYS_ON}
    assert {"single_language", "matches_customer_language"} <= names


def test_a_price_in_baht_is_not_thai_left_in_an_english_reply(db, clinic):
    """U+0E3F (฿) is inside the Thai Unicode block; an English reply quoting the
    clinic's currency was graded as half-translated. Seen on english_customer_gets_english."""
    text = "Botox Jaw Slimming starts at ฿2,800 per session. Would you like to book?"
    assert single_language()(_ctx(db, clinic, text, turns=("Hi, how much is Botox?",))).ok is True


def test_promotion_titles_are_catalog_names_too(db, clinic):
    """A reply that surfaces a promotion has to be able to say what it is called."""
    db.add(models.Promotion(clinic_id=clinic.id, title="Glow Season — 20% off Pico Laser",
                            detail="", active=True))
    db.commit()
    text = "ตอนนี้มีโปร Glow Season ลด 20% ค่ะ สนใจไหมคะ"
    assert single_language()(_ctx(db, clinic, text)).ok is True


def test_a_thai_question_naming_a_long_treatment_expects_thai(db, clinic):
    """matches_customer_language must resolve the customer's language exactly as the
    app does — clinic names included — or "Botox Jaw Slimming ราคาเท่าไหร่คะ" grades as
    an English customer while the app correctly answered in Thai."""
    _service(db, clinic, "Botox Jaw Slimming")
    ctx = _ctx(db, clinic, "Botox Jaw Slimming ราคา 8,900 บาทค่ะ", turns=("Botox Jaw Slimming ราคาเท่าไหร่คะ",))
    assert matches_customer_language()(ctx).ok is True


def test_names_are_removed_before_the_reply_script_is_decided(db, clinic):
    """Two catalog names out-count the Thai around them; the reply is still Thai, and
    it must not pass only because a stray ฿ happened to tip the count."""
    _service(db, clinic, "Signature Facial")
    branch = db.query(models.Branch).filter_by(clinic_id=clinic.id).first()
    text = f"ที่สาขา {branch.name} มี Signature Facial ราคาเริ่มต้น 2,800 บาทค่ะ"
    assert single_language()(_ctx(db, clinic, text)).ok is True


# --------------------------------------------------------------------------
# single_language now also catches a stray CJK/other-script run the customer never
# typed themselves -- previously invisible to this check, which only compared Thai
# against Latin.
# --------------------------------------------------------------------------
def test_stray_cjk_in_a_thai_reply_is_flagged(db, clinic):
    cjk = "".join(chr(c) for c in range(0x4E50, 0x4E54))   # arbitrary CJK Unified run
    res = single_language()(_ctx(db, clinic, f"ที่สาขานี้ {cjk} มีทรีตเมนต์ให้เลือกค่ะ"))
    assert res.ok is False


def test_a_customers_own_cjk_name_is_not_flagged(db, clinic):
    cjk = "".join(chr(c) for c in range(0x7530, 0x7533))
    res = single_language()(_ctx(db, clinic, f"ขอบคุณค่ะคุณ{cjk} บันทึกให้แล้วนะคะ",
                                 turns=(f"ชื่อ{cjk}ค่ะ",)))
    assert res.ok is True


def test_a_script_beyond_thai_latin_cjk_is_flagged_in_an_english_reply(db, clinic):
    cyrillic = "".join(chr(c) for c in range(0x0430, 0x0434))
    res = single_language()(
        _ctx(db, clinic, f"Your appointment is confirmed {cyrillic}",
             turns=("Can you confirm my appointment?",)))
    assert res.ok is False
