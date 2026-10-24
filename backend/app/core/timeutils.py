"""Timezone helpers. All exchange logic runs in Asia/Kolkata."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now_ist() -> datetime:
    return datetime.now(tz=IST)


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Naive datetimes stored in the DB are UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def epoch_to_ist(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=IST)


def ist_combine(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=IST)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat()
