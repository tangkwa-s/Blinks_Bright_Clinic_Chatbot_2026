"""Regression tests for how the reply language is decided (``app/ai/chat.py``).

Almost everything the AI is given about the clinic is written in Thai, so the model
drifts Thai unless the language is stated as a computed fact. It is resolved from the
customer's own messages rather than the model's judgement — and the awkward part is
that a lone "Hi"/"Hello" is NOT a language choice: Thai customers open that way
constantly, so treating it as English would answer a Thai speaker in English.
"""
from app.ai.chat import _language_directive, customer_language, script_of


class _Msg:
    def __init__(self, text, sender="customer"):
        self.text, self.sender = text, sender


# --------------------------------------------------------------------------
# script_of — which script a single message is written in
# --------------------------------------------------------------------------
def test_script_is_decided_by_the_bulk_of_the_message():
    # a Thai sentence naming an English treatment is still Thai
    assert script_of("Signature Facial ราคาเริ่มต้น 2,800 บาทค่ะ ใช้เวลา 60 นาที") == "th"
    # an English sentence naming a Thai-named branch is still English
    assert script_of("The treatment at สาขา Thonglor starts from 2,800 baht.") == "en"
    assert script_of("How much is the Signature Facial?") == "en"


def test_a_message_with_no_letters_decides_nothing():
    assert script_of("11:00") == ""
    assert script_of("081-234-5678") == ""
    assert script_of("👍") == ""


def test_a_payment_link_is_not_read_as_english():
    assert script_of("กรุณาชำระผ่านลิงก์นี้ค่ะ https://checkout.stripe.com/c/pay/cs_test_x") == "th"


# --------------------------------------------------------------------------
# customer_language — the resolver the orchestrator actually uses
# --------------------------------------------------------------------------
def test_a_lone_english_greeting_does_not_switch_the_language():
    """The reported case: Thai customers type "Hi"/"Hello" too."""
    for greeting in ("Hello", "hello!", "Hey", "Good morning", "Thanks", "ok"):
        assert customer_language([greeting]) == "th", greeting


def test_a_real_english_sentence_does_switch():
    assert customer_language(["Hello", "How much is the Signature Facial?"]) == "en"
    assert customer_language(["Hi, how much is HIFU?"]) == "en"


def test_thai_wins_whenever_the_customer_writes_thai():
    assert customer_language(["สวัสดีค่ะ"]) == "th"
    assert customer_language(["How much is HIFU?", "สนใจสาขาทองหล่อค่ะ"]) == "th"


def test_filler_after_an_english_conversation_keeps_english():
    """"ok" decides nothing, so the English question before it still rules."""
    assert customer_language(["How much is the Signature Facial?", "ok"]) == "en"
    assert customer_language(["How much is the Signature Facial?", "11:00"]) == "en"


def test_greeting_after_a_thai_conversation_keeps_thai():
    assert customer_language(["ราคาเท่าไหร่คะ", "Hello"]) == "th"


def test_defaults_to_thai_when_nothing_settles_it():
    """A Thai clinic: silence, emoji or a bare number is not a request for English."""
    assert customer_language([]) == "th"
    assert customer_language(["👍", "11:00"]) == "th"


# --------------------------------------------------------------------------
# _language_directive — what actually reaches the prompt
# --------------------------------------------------------------------------
def test_directive_names_the_language_and_ignores_the_ai_side():
    en = _language_directive([_Msg("How much is the Signature Facial?"),
                              _Msg("ราคาเริ่มต้น 2,800 บาทค่ะ", sender="ai")])
    assert "REPLY LANGUAGE" in en and "English" in en and "Thai" not in en

    th = _language_directive([_Msg("Hello"), _Msg("สนใจ HIFU ค่ะ")])
    assert "Thai" in th and "English" not in th


# --------------------------------------------------------------------------
# The clinic's own names are Latin — answering with one is not "writing English"
# --------------------------------------------------------------------------
_AURORA = frozenset({"south", "north", "central", "aurora", "hifu", "lifting",
                     "skin", "booster"})


def test_naming_a_latin_branch_does_not_switch_the_language():
    """The reported case: a Thai customer answers the branch question with the branch's
    own English name. Without the clinic's names the whole chat flipped to English."""
    assert customer_language(["สนใจสกินบู๊ทค่ะ", "South Aurora"], _AURORA) == "th"
    assert customer_language(["สนใจค่ะ", "HIFU Lifting"], _AURORA) == "th"


def test_a_latin_name_still_decides_nothing_on_its_own():
    """No earlier message either way -> fall through to the Thai default."""
    assert customer_language(["South Aurora"], _AURORA) == "th"


def test_a_real_english_sentence_around_the_name_still_switches():
    assert customer_language(["สนใจค่ะ", "Is South Aurora open today?"], _AURORA) == "en"


def test_names_do_not_mask_an_english_conversation():
    """English question first, branch name second -> still English."""
    assert customer_language(["How much is HIFU?", "South Aurora"], _AURORA) == "en"


def test_without_the_clinic_names_the_old_behaviour_is_unchanged():
    """The names are opt-in, so every existing caller keeps its result."""
    assert customer_language(["สนใจสกินบู๊ทค่ะ", "South Aurora"]) == "en"


def test_language_directive_takes_the_names_too():
    th = _language_directive([_Msg("สนใจสกินบู๊ทค่ะ"), _Msg("South Aurora")], _AURORA)
    assert "Thai" in th and "English" not in th


def test_clinic_name_words_reads_branches_services_and_staff(db, clinic):
    from app.ai.chat import clinic_name_words
    words = clinic_name_words(db, clinic.id)
    assert "hifu" in words and "lifting" in words     # a seeded treatment
    assert "branch" in words                          # the seeded "Main Branch"


def test_a_thai_question_about_a_long_latin_name_is_thai_even_after_english():
    """"Botox Jaw Slimming ราคาเท่าไหร่คะ" carries more Latin letters in the treatment
    name than Thai letters in the question around it. Counted whole it read as English
    and was then discarded as "only names" — so the resolver fell through to whatever
    came before, and one earlier English line flipped the reply. The names come out
    BEFORE the count now, and the message is what it is: a Thai question."""
    names = frozenset({"botox", "jaw", "slimming"})
    assert customer_language(["How much is it?", "Botox Jaw Slimming ราคาเท่าไหร่คะ"], names) == "th"


def test_the_baht_sign_is_not_a_thai_letter():
    """U+0E3F sits inside the Thai block; "฿2,800" is a price in any language."""
    assert script_of("฿2,800") == ""
    assert script_of("Botox is ฿2,800 per session") == "en"
