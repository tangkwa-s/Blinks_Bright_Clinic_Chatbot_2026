"""Stray foreign-script gibberish must never reach the customer.

A real LINE reply ended "รบกวนขอเบอร์โทรศัพท์สำหรับการจองด้วยนะคะеfoн" — Cyrillic е,
Latin f, Latin o, Cyrillic н, glued straight onto a Thai sentence. It is rare and
random, so no prompt rule can be trusted to prevent it and no live run can reliably
provoke it; but the assistant only ever writes Thai and English, which makes it
trivial to detect deterministically.
"""
from app.ai.chat import _drop_alien_scripts


def test_the_reported_glitch_is_removed():
    reply = "รบกวนขอเบอร์โทรศัพท์สำหรับการจองด้วยนะคะеfoн"
    assert _drop_alien_scripts(reply) == "รบกวนขอเบอร์โทรศัพท์สำหรับการจองด้วยนะคะ"


def test_a_standalone_gibberish_token_goes_too():
    assert _drop_alien_scripts("ยินดีค่ะ привет") == "ยินดีค่ะ"


def test_an_ordinary_thai_reply_is_untouched():
    reply = "ที่สาขา South Aurora ราคา HIFU Lifting อยู่ที่ ฿24,000 ค่ะ"
    assert _drop_alien_scripts(reply) == reply


def test_an_ordinary_english_reply_is_untouched():
    reply = "At South Aurora, HIFU Lifting starts from 24,000 baht."
    assert _drop_alien_scripts(reply) == reply


def test_a_customers_own_name_is_kept():
    """Their name may genuinely be in one of these scripts — echoing it back is right."""
    reply = "ขอบคุณค่ะ คุณАнна บันทึกให้แล้วนะคะ"
    assert _drop_alien_scripts(reply, customer_text="ชื่อ Анна ค่ะ") == reply


def test_cjk_is_never_touched():
    """A Japanese or Chinese display name is legitimate; the prompt forbids translating it."""
    reply = "ขอบคุณค่ะ คุณ田中 บันทึกให้แล้วนะคะ"
    assert _drop_alien_scripts(reply) == reply


def test_emoji_and_currency_survive():
    reply = "ยินดีค่ะ 😊 ราคา ฿24,000 มัดจำ ฿4,800 ค่ะ"
    assert _drop_alien_scripts(reply) == reply


def test_empty_and_none_are_safe():
    assert _drop_alien_scripts("") == ""
    assert _drop_alien_scripts(None) == ""


# --------------------------------------------------------------------------
# the same glitch in a script you cannot see it in
# --------------------------------------------------------------------------
def test_a_stray_latin_word_on_the_end_of_a_thai_reply_goes(db=None):
    """A real reply ended "ขอเบอร์โทรสำหรับการจองด้วยนะคะ.ones." — Latin letters, so the
    alien-script strip passed it straight through to the customer."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ขอเบอร์โทรสำหรับการจองด้วยนะคะ.ones."
    assert _drop_trailing_gibberish(reply) == "ขอเบอร์โทรสำหรับการจองด้วยนะคะ"


def test_the_clinics_own_names_are_kept():
    from app.ai.chat import _drop_trailing_gibberish

    keep = frozenset({"hifu", "aurora", "booster"})
    for reply in ("ทรีตเมนต์ที่แนะนำคือ Hifu",
                  "สาขาที่สะดวกคือ Aurora"):
        assert _drop_trailing_gibberish(reply, keep) == reply


def test_a_word_the_customer_wrote_is_kept():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ยินดีค่ะ คุณ Kavin"
    assert _drop_trailing_gibberish(reply, frozenset(), "ผมชื่อ Kavin ครับ") == reply


def test_a_reply_ending_in_a_payment_link_is_never_trimmed():
    from app.ai.chat import _drop_trailing_gibberish

    reply = ("กรุณาชำระมัดจำผ่านลิงก์นี้เพื่อยืนยันคิวนะคะ "
             "https://checkout.stripe.com/c/pay/cs_test_a1Z0uPYCQLdazEN")
    assert _drop_trailing_gibberish(reply) == reply


def test_an_english_reply_is_left_alone():
    """This only ever fires on a Thai reply — English ends in English words."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "Which branch would suit you best"
    assert _drop_trailing_gibberish(reply) == reply


# --------------------------------------------------------------------------
# the same glitch again, in the two scripts test_cjk_is_never_touched deliberately
# leaves alone MID-reply — a token glued onto the very tail, with nothing said about
# it before or after, is never a legitimate customer name
# --------------------------------------------------------------------------
def test_a_stray_cjk_token_on_the_end_of_a_thai_reply_goes():
    """A real reply ended "...ไหนคะ 乐彩" — _drop_alien_scripts leaves CJK untouched
    everywhere, so this reached the customer verbatim."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "สะดวกเข้ารับบริการวันที่และเวลาไหนคะ 乐彩"
    assert (_drop_trailing_gibberish(reply)
            == "สะดวกเข้ารับบริการวันที่และเวลาไหนคะ")


def test_a_customers_own_cjk_name_on_the_end_is_kept():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ขอบคุณค่ะคุณ田中"
    assert _drop_trailing_gibberish(reply, customer_text="ชื่อ田中ค่ะ") == reply


def test_a_stray_hangul_token_on_the_end_of_a_thai_reply_goes():
    """No Korean glitch has been reported yet, but the same reasoning as the Chinese/
    Japanese case applies — a run glued onto the tail with nothing said about it is
    never a legitimate customer name, and no live reply contains Hangul at all."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ยืนยันคิวเรียบร้อยค่ะ안녕"
    assert _drop_trailing_gibberish(reply) == "ยืนยันคิวเรียบร้อยค่ะ"


def test_a_customers_own_hangul_name_on_the_end_is_kept():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ขอบคุณค่ะคุณ김민수"
    assert _drop_trailing_gibberish(reply, customer_text="ชื่อ김민수ค่ะ") == reply


def test_a_stray_digit_glued_to_the_end_of_a_thai_reply_goes():
    """A real reply ended "...ด้วยนะคะ1" — a bare digit with no space before it at
    all, which is not a phone number, a price or a time."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ขอเบอร์โทรสำหรับการจองด้วยนะคะ1"
    assert _drop_trailing_gibberish(reply) == "ขอเบอร์โทรสำหรับการจองด้วยนะคะ"


def test_a_digit_the_customer_named_is_kept():
    """Matched on digit boundaries, not substring — a phone number that happens to
    contain the digit somewhere must not excuse a genuinely stray one."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "จองคิวที่โต๊ะ5"
    assert _drop_trailing_gibberish(reply, customer_text="ขอโต๊ะ 5 นะคะ") == reply
    assert (_drop_trailing_gibberish(reply, customer_text="เบอร์ 0912345678 ค่ะ")
            == "จองคิวที่โต๊ะ")


def test_a_real_phone_number_is_untouched():
    """The AI only ever writes a number with a space before it — that space is the
    real safety boundary here, not the number's length. _TRAILING_DIGITS has no length
    cap (a glued run is suspect at any length: measured zero legitimate replies end in
    a digit run glued on with no space, whether it's 1 digit or 10), so what protects a
    real phone number is that it is never written glued in the first place."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "เบอร์ที่บันทึกไว้คือ 0912345678"
    assert _drop_trailing_gibberish(reply) == reply


def test_a_long_digit_run_glued_with_no_space_is_also_a_glitch():
    """Not just the short runs the first reported bug happened to be — any length,
    since the glue (no space at all) is what makes it suspect, not how long it is."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ยืนยันคิวเรียบร้อยค่ะ0912345678"
    assert _drop_trailing_gibberish(reply) == "ยืนยันคิวเรียบร้อยค่ะ"


def test_a_latin_word_glued_with_zero_separator_also_goes():
    """_TRAILING_LATIN used \\b, which treats Thai letters as word characters too — so
    a Latin word glued directly onto Thai with no space or punctuation at all had no
    \\w/\\W transition for \\b to fire on, and slipped through uncaught."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ยืนยันคิวเรียบร้อยค่ะabc"
    assert _drop_trailing_gibberish(reply) == "ยืนยันคิวเรียบร้อยค่ะ"


# --------------------------------------------------------------------------
# _drop_alien_scripts is now built from an ALLOWLIST, not six hand-named scripts — a
# glitch in any script outside Thai/Latin/CJK/currency/punctuation/emoji is alien, not
# just the original Cyrillic/Greek/Armenian/Hebrew/Arabic/Devanagari six. Built with
# chr() from numeric codepoints rather than typed literals: a CJK Compatibility
# Ideograph and its canonical CJK Unified twin render identically but are different
# codepoints, and copy-pasting the wrong one through an editor is exactly how a prior
# version of this file's own _CJK_CHAR constant got silently corrupted mid-review.
# --------------------------------------------------------------------------
def _script(start: int, count: int) -> str:
    return "".join(chr(start + i) for i in range(count))


def test_a_script_beyond_the_original_six_is_also_caught():
    """Lao (U+0E80 block) was never on the old six-script list."""
    lao = _script(0x0E9B, 4)
    reply = f"ยินดีค่ะ {lao} ขอบคุณค่ะ"
    assert _drop_alien_scripts(reply) == "ยินดีค่ะ ขอบคุณค่ะ"


def test_khmer_is_also_caught():
    khmer = _script(0x1798, 4)
    reply = f"ยินดีค่ะ {khmer} ขอบคุณค่ะ"
    assert _drop_alien_scripts(reply) == "ยินดีค่ะ ขอบคุณค่ะ"


def test_georgian_is_also_caught():
    georgian = _script(0x10D0, 4)
    reply = f"ยินดีค่ะ {georgian} ขอบคุณค่ะ"
    assert _drop_alien_scripts(reply) == "ยินดีค่ะ ขอบคุณค่ะ"


def test_a_script_beyond_the_six_backed_by_the_customer_is_kept():
    myanmar = _script(0x1002, 4)
    reply = f"ขอบคุณค่ะคุณ{myanmar}"
    assert _drop_alien_scripts(reply, customer_text=f"ชื่อ{myanmar}ค่ะ") == reply


def test_accented_latin_is_not_alien():
    """Latin Extended (Vietnamese, French, Turkish names) is now inside the allowlist,
    not swept up as alien the way it would be if the check still worked from a bare
    A-Za-z range."""
    reply = "ขอบคุณค่ะคุณ Nguyễn บันทึกให้แล้วนะคะ"
    assert _drop_alien_scripts(reply) == reply


def test_currency_and_punctuation_symbols_survive():
    reply = "ราคาเริ่มต้น €120 หรือ ¥15,000 ค่ะ — ทางเลือกอื่นก็มีนะคะ…"
    assert _drop_alien_scripts(reply) == reply


# --------------------------------------------------------------------------
# _drop_invisible — control/formatting characters with no legitimate visible use
# --------------------------------------------------------------------------
def test_zero_width_space_is_stripped():
    from app.ai.chat import _drop_invisible

    reply = "ยินดีค่ะ" + chr(0x200B) + "สนใจทรีตเมนต์ไหนคะ"
    assert _drop_invisible(reply) == "ยินดีค่ะสนใจทรีตเมนต์ไหนคะ"


def test_bidi_override_is_stripped():
    from app.ai.chat import _drop_invisible

    reply = "ราคา" + chr(0x202E) + "24,000 บาทค่ะ"
    assert _drop_invisible(reply) == "ราคา24,000 บาทค่ะ"


def test_replacement_character_is_stripped():
    from app.ai.chat import _drop_invisible

    reply = "ยืนยันคิวเรียบร้อยค่ะ" + chr(0xFFFD)
    assert _drop_invisible(reply) == "ยืนยันคิวเรียบร้อยค่ะ"


def test_private_use_area_is_stripped():
    from app.ai.chat import _drop_invisible

    reply = "ยินดีค่ะ" + chr(0xE001) + "ขอบคุณค่ะ"
    assert _drop_invisible(reply) == "ยินดีค่ะขอบคุณค่ะ"


def test_zwj_emoji_sequence_survives():
    """A real multi-codepoint emoji (family) is built out of ZWJ — must not be
    treated as an invisible glitch and stripped."""
    from app.ai.chat import _drop_invisible

    zwj = chr(0x200D)
    family = f"\U0001F468{zwj}\U0001F469{zwj}\U0001F467"
    reply = f"ยินดีค่ะ {family} ขอบคุณค่ะ"
    assert _drop_invisible(reply) == reply


def test_empty_and_none_are_safe_for_invisible():
    from app.ai.chat import _drop_invisible

    assert _drop_invisible("") == ""
    assert _drop_invisible(None) == ""


# --------------------------------------------------------------------------
# _drop_unbacked_cjk — CJK gibberish glued into the MIDDLE of a reply, not just the
# tail. Hybrid backing: kept if the customer said it, it's in their saved CRM name, or
# it directly follows an address word ("คุณ").
# --------------------------------------------------------------------------
def test_unbacked_mid_reply_cjk_is_removed():
    from app.ai.chat import _drop_unbacked_cjk

    reply = "ที่สาขานี้ 乐彩 มีทรีตเมนต์ให้เลือกหลายแบบค่ะ"
    assert _drop_unbacked_cjk(reply) == "ที่สาขานี้ มีทรีตเมนต์ให้เลือกหลายแบบค่ะ"


def test_mid_reply_cjk_backed_by_customer_text_is_kept():
    from app.ai.chat import _drop_unbacked_cjk

    reply = "ที่สาขานี้ 田中 สนใจ Hifu ค่ะ"
    assert _drop_unbacked_cjk(reply, customer_text="ผมชื่อ田中ครับ") == reply


def test_mid_reply_cjk_backed_by_crm_name_is_kept():
    """Covers a name STAFF entered into the CRM that the customer never typed
    themselves in this conversation."""
    from app.ai.chat import _drop_unbacked_cjk

    reply = "คุณลูกค้า 田中 คะ นัดหมายของคุณคือวันพรุ่งนี้ค่ะ"
    assert _drop_unbacked_cjk(reply, customer_text="", crm_names="田中 Tanaka") == reply


def test_mid_reply_cjk_after_an_address_word_is_kept():
    """The only shape the assistant is ever shown addressing a customer in CJK with —
    kept even with zero other backing."""
    from app.ai.chat import _drop_unbacked_cjk

    reply = "ขอบคุณค่ะ คุณ田中 บันทึกให้แล้วนะคะ"
    assert _drop_unbacked_cjk(reply) == reply


def test_unbacked_cjk_with_no_address_word_is_removed_even_if_short():
    from app.ai.chat import _drop_unbacked_cjk

    reply = "ยินดีค่ะ 田中 มีคำถามเพิ่มเติมไหมคะ"
    assert _drop_unbacked_cjk(reply) == "ยินดีค่ะ มีคำถามเพิ่มเติมไหมคะ"


def test_no_cjk_is_a_no_op():
    from app.ai.chat import _drop_unbacked_cjk

    reply = "สวัสดีค่ะ สนใจทรีตเมนต์ไหนคะ"
    assert _drop_unbacked_cjk(reply) == reply


# --------------------------------------------------------------------------
# _drop_trailing_gibberish no longer skips English-classified replies for the
# CJK/digit checks — only the trailing-Latin check stays Thai-only, since stripping a
# trailing English word only makes sense when the REST of the reply is Thai.
# --------------------------------------------------------------------------
def test_an_english_reply_still_gets_trailing_cjk_stripped():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "Our team will check your booking and get back to you 乐彩"
    assert (_drop_trailing_gibberish(reply)
            == "Our team will check your booking and get back to you")


def test_an_english_reply_still_gets_trailing_digit_stripped():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "Your appointment is confirmed1"
    assert _drop_trailing_gibberish(reply) == "Your appointment is confirmed"


def test_an_english_reply_keeps_its_own_trailing_english_word():
    """The Latin check itself stays Thai-only — an English reply ending in an English
    word is normal, not a glitch."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "Which branch would suit you best"
    assert _drop_trailing_gibberish(reply) == reply


# --------------------------------------------------------------------------
# The trailing unbacked-offer strip — guardrails.unbacked_offers finally gets to
# remove the text it flags, not just log it. This is the exact screenshot: a correct
# booking reply with a dangling, ungrounded "เครดิตฟรี" tacked on the end.
# --------------------------------------------------------------------------
def test_the_reported_free_credit_glitch_is_removed():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ที่สาขา Central Aurora ราคา HIFU Lifting อยู่ที่ 25,000 บาท และมัดจำ 5,000 บาท ใช้เวลาประมาณ 60 นาทีค่ะ สะดวกเข้ารับบริการวันที่และเวลาไหนคะ เครดิตฟรี"
    assert _drop_trailing_gibberish(reply) == (
        "ที่สาขา Central Aurora ราคา HIFU Lifting อยู่ที่ 25,000 บาท และมัดจำ 5,000 บาท "
        "ใช้เวลาประมาณ 60 นาทีค่ะ สะดวกเข้ารับบริการวันที่และเวลาไหนคะ")


def test_a_grounded_offer_word_is_kept():
    """A real promotion the tool actually returned must not be deleted."""
    from app.ai.chat import _drop_trailing_gibberish

    reply = "ตอนนี้มีโปรทรีตเมนต์ผิวหน้าฟรี 1 ครั้งค่ะ"
    assert _drop_trailing_gibberish(
        reply, grounding="โปรโมชั่นทรีตเมนต์ผิวหน้าฟรี 1 ครั้ง") == reply


def test_an_offer_word_the_customer_raised_is_kept():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "รับทราบค่ะ ทางเราไม่มีเครดิตฟรี"
    assert _drop_trailing_gibberish(
        reply, customer_text="มีเครดิตฟรีไหมคะ") == reply


def test_an_english_reply_also_gets_trailing_offer_word_stripped():
    from app.ai.chat import _drop_trailing_gibberish

    reply = "Your booking is confirmed for tomorrow at 2pm free credit"
    assert (_drop_trailing_gibberish(reply)
            == "Your booking is confirmed for tomorrow at 2pm")
