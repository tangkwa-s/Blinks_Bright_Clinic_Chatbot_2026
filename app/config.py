"""Application configuration, loaded from the project-root .env file."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Settings sourced from environment variables / .env (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- API keys (.env) ---
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # Resend — booking-confirmation email; blank key disables email entirely.
    # email_from falls back to onboarding@resend.dev (Resend's shared test sender).
    resend_api_key: str = ""
    email_from: str = ""

    # --- AI models ---
    chat_model: str = "gpt-5.6-luna"
    # The eval judge stays PINNED to one model regardless of chat_model, so an
    # A/B between chat models never lets a candidate grade its own answers.
    judge_model: str = "gpt-5.4-mini-2026-03-17"
    embedding_model: str = "text-embedding-3-small"

    # --- LLM cost (for the dashboard AI-cost summary) ---
    # NOTE: these are still gpt-5.4-mini list prices, but chat_model is now
    # gpt-5.6-luna — so the dashboard's AI-cost summary is priced against the wrong
    # model until these are updated. text-embedding-3-small; $/1M tokens, then THB.
    # Override any of these in .env if your rate differs.
    ai_price_input_usd: float = 0.75
    ai_price_output_usd: float = 4.50
    ai_price_embed_usd: float = 0.02
    usd_to_thb: float = 36.0

    # --- application ---
    app_name: str = "Blinks Bright"
    session_secret: str = "blinksbright-dev-secret-change-me"
    db_path: str = str(BASE_DIR / "clinic.db")
    host: str = "127.0.0.1"
    port: int = 8051
    base_url: str = "http://localhost:8051"
    timezone: str = "Asia/Bangkok"
    currency: str = "thb"
    # How long an unpaid AI booking holds its slot before it is released (minutes).
    # Business policy, so it is .env-tunable (HOLD_MINUTES=15). booking.py clamps it
    # to >= 1: zero would silently switch holds OFF and bring back the bug they exist
    # to fix (an abandoned checkout blocking a slot until the no-show sweep).
    hold_minutes: int = 10
    # The clinic's PromptPay / bank-transfer QR image (path under web/) — the only way to
    # pay. The AI shows it with the amount, the customer sends the slip in chat, and a
    # staff member confirms it (POST /api/payments/{id}/mark-paid). File missing = the
    # assistant hands payment to a person instead.
    payment_qr_image: str = "/assets/images/payment-qr.png"
    # How often the external-calendar (ICS) sync job pulls each doctor's busy blocks
    # from their pasted calendar URL (minutes), .env CALENDAR_SYNC_MINUTES. Purely a
    # freshness-vs-fetch-volume tradeoff — it never touches claim_slot's lock path (see
    # booking.py's day_availability), so lowering this only affects background fetch
    # volume and how quickly a slot frees up again after a doctor clears their own
    # calendar, never booking latency.
    calendar_sync_minutes: int = 15
    # How long a human "takeover" (manual or auto-escalated) can sit with the
    # customer's latest message unanswered before the conversation automatically hands
    # back to the AI (minutes), .env TAKEOVER_TIMEOUT_MINUTES. Measured from the
    # customer's message going unanswered, not from the takeover moment itself — a
    # staff member actively replying is never interrupted just because the takeover
    # itself is "old".
    takeover_timeout_minutes: int = 15


settings = Settings()
