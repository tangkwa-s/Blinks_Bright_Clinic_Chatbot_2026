"""The clinic's payment QR — the one way a customer pays.

The clinic drops its own PromptPay QR at ``settings.payment_qr_image``; the AI shows it
with the amount, the customer sends the slip, and staff confirm the payment by hand
(``POST /api/payments/{id}/mark-paid``).
"""
from pathlib import Path

from app.config import settings

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def qr_image_url() -> str | None:
    """The QR's public path, or None when none is configured or the file is missing.

    Checked on every call rather than cached, so dropping the file in (or removing it)
    takes effect without a restart."""
    rel = (settings.payment_qr_image or "").strip()
    if not rel.startswith("/") or ".." in rel:
        return None
    return rel if (WEB_DIR / rel.lstrip("/")).is_file() else None
