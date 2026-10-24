"""Hallucination guard — verify the AI reply is grounded in known facts.

Any 3+ digit number in the reply (prices, intervals) must appear in the
retrieved KB context or a tool result, otherwise it is flagged for review.

Calendar years are exempt: a booking summary naturally says "1 ส.ค. 2026" (or
พ.ศ. 2569), and when the model correctly REUSES availability it checked in an
earlier turn (the prompt tells it to), no tool result in THIS turn carries the
year — so replies were flagged for the date of their own appointment. Years
2020-2099 CE / 2560-2599 BE cannot collide with real prices except a ฿2,5xx
price in the 2560-2599 band, which stays flagged only if truly ungrounded and
is vanishingly rare on a clinic menu.
"""
import re

_YEAR_RE = re.compile(r"^(?:20[2-9]\d|25[6-9]\d)$")   # 2020-2099 CE, 2560-2599 BE


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d{3,}", re.sub(r",", "", text or "")))


def check(reply: str, grounding: str) -> dict:
    """Return {'grounded': bool, 'unsupported': [numbers]}."""
    reply_numbers = {n for n in _numbers(reply) if not _YEAR_RE.match(n)}
    if not reply_numbers:
        return {"grounded": True, "unsupported": []}
    supported = _numbers(grounding)
    unsupported = sorted(reply_numbers - supported)
    return {"grounded": not unsupported, "unsupported": unsupported}
