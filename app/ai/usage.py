"""LLM token-usage tracking + cost — powers the dashboard's AI-cost summary.

Each AI call (chat completion, post-reply analysis) records a ``TokenUsage`` row.
Cost uses the configurable per-1M-token rates in ``app.config`` (gpt-5.4-mini list
price by default) converted to THB. Writes use their own session so they never
interfere with the caller's transaction, and a failure is swallowed (telemetry
must never break a customer reply).
"""
from app import models
from app.config import settings
from app.database import SessionLocal


def record(clinic_id, kind: str, model: str,
           prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """Persist one LLM call's token usage (no-op when there's nothing to record)."""
    p, c = int(prompt_tokens or 0), int(completion_tokens or 0)
    if not (p or c) or clinic_id is None:
        return
    db = SessionLocal()
    try:
        db.add(models.TokenUsage(clinic_id=clinic_id, kind=kind, model=(model or "")[:60],
                                 prompt_tokens=p, completion_tokens=c, total_tokens=p + c))
        db.commit()
    except Exception as exc:  # pragma: no cover
        db.rollback()
        print("[usage] record skipped:", exc)
    finally:
        db.close()


def cost_thb(prompt_tokens: int = 0, completion_tokens: int = 0, embed_tokens: int = 0) -> float:
    """THB cost for the given token counts at the configured rates."""
    usd = (prompt_tokens / 1e6 * settings.ai_price_input_usd
           + completion_tokens / 1e6 * settings.ai_price_output_usd
           + embed_tokens / 1e6 * settings.ai_price_embed_usd)
    return round(usd * settings.usd_to_thb, 2)
