"""Is this photo a payment slip, and for how much? One question to the vision model.

Only asked while the customer owes a payment (app/services/slips.py). The answer only
decides which path the photo takes — a slip goes to a person, any other photo gets the
assistant's normal reply — and whether the amount on it matches what is owed. It never
decides that money arrived: staff do that, looking at the slip itself.
"""
import json
import re

from app.ai import usage
from app.ai.client import chat_completion, is_configured
from app.config import settings

_QUESTION = (
    "Is this image a bank transfer or payment slip / receipt — for example a Thai banking "
    "app transfer confirmation, a PromptPay receipt, or an e-slip showing an amount sent? "
    "If it is, also read the amount that was transferred (จำนวนเงิน / Amount), in baht, as "
    "a plain number without commas or currency signs; null if you cannot read it clearly. "
    'Answer with JSON only, exactly: {"slip": true|false, "amount": number|null}'
)


def _amount(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
    return float(m.group(0).replace(",", "")) if m else None


def read_slip(image_url: str, clinic_id: int | None = None) -> dict | None:
    """``{"is_slip": bool, "amount": float | None}``, or None when the model could not be
    asked (no API key, no readable file, an error, an unreadable answer). Callers treat
    None as a possible slip: a paying customer losing their slot to a timeout is worse
    than a person glancing at a skin photo."""
    from app.ai.chat import _image_part

    part = _image_part(image_url)
    if not part or not is_configured():
        return None
    try:
        res = chat_completion(
            [{"role": "user", "content": [{"type": "text", "text": _QUESTION}, part]}],
            max_tokens=60, temperature=0)
    except Exception as exc:  # pragma: no cover - network
        print("[slip] classify error:", exc)
        return None
    u = getattr(res, "usage", None)
    if u:
        usage.record(clinic_id, "slip_check", settings.chat_model,
                     getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
    answer = ((res.choices[0].message.content or "") if res.choices else "").strip()
    return parse_answer(answer)


def parse_answer(answer: str) -> dict | None:
    m = re.search(r"\{.*\}", answer or "", re.S)
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("slip"), bool):
            return {"is_slip": data["slip"],
                    "amount": _amount(data.get("amount")) if data["slip"] else None}
    low = (answer or "").strip().lower()
    if low.startswith("yes"):
        return {"is_slip": True, "amount": None}
    if low.startswith("no"):
        return {"is_slip": False, "amount": None}
    return None


def is_payment_slip(image_url: str, clinic_id: int | None = None) -> bool | None:
    """The yes/no half of ``read_slip`` (None = could not ask)."""
    r = read_slip(image_url, clinic_id)
    return None if r is None else r["is_slip"]
