"""Shared period-range resolution for reporting endpoints (dashboard, payments) — one
place so a "30d"/"1y" token means the same cutoff everywhere it's used, instead of two
copies of the same calendar math quietly drifting apart.
"""
from datetime import datetime, timedelta

RANGES = {"7d": 7, "30d": 30, "90d": 90, "1y": 365, "all": 4000}


def one_year_days(today) -> int:
    """Exact day-count back to the same calendar date last year — 365 or 366
    depending on whether a Feb 29 falls within the trailing window (a fixed
    365 undercounts by a day whenever the year being spanned was a leap year)."""
    try:
        last_year = today.replace(year=today.year - 1)
    except ValueError:      # today is Feb 29 -> no such date twelve months back
        last_year = today.replace(year=today.year - 1, month=2, day=28)
    return (today - last_year).days


def period_since(period: str, now_utc: datetime) -> datetime:
    """The UTC cutoff datetime a "period" token (7d/30d/90d/1y/all) resolves to,
    anchored to today in Bangkok time (matches how every other date boundary in this
    app is reasoned about) rather than the server's own UTC day."""
    today_bkk_date = (now_utc + timedelta(hours=7)).date()
    days = one_year_days(today_bkk_date) if period == "1y" else RANGES.get(period, 30)
    return now_utc - timedelta(days=days)
