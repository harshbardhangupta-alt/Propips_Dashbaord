"""Data-freshness rules applied before any strategy decision."""
from __future__ import annotations

from datetime import date, datetime, time

from app.core.market_calendar import MarketCalendar
from app.core.timeutils import IST, MARKET_CLOSE, MARKET_OPEN
from app.market_data.candles import Candle, TF_MINUTES, candle_end

# During market hours, a completed candle is FRESH if it ended no more than
# N bar-lengths (+5 min publication tolerance) ago.
FRESHNESS_BARS = {"5m": 3, "15m": 2, "1H": 2, "4H": 1, "1D": 1}
DAILY_PUBLISH_GRACE = time(18, 0)


def latest_completed_session(now: datetime, cal: MarketCalendar) -> date:
    """Most recent trading date whose full session has closed."""
    now = now.astimezone(IST)
    if cal.is_trading_day(now.date()) and now.time() >= MARKET_CLOSE:
        return now.date()
    return cal.previous_trading_day(now.date())


def latest_started_session(now: datetime, cal: MarketCalendar) -> date:
    now = now.astimezone(IST)
    if cal.is_trading_day(now.date()) and now.time() >= MARKET_OPEN:
        return now.date()
    return cal.previous_trading_day(now.date())


def freshness(candles: list[Candle], timeframe: str, now: datetime, cal: MarketCalendar) -> dict:
    """Return {status: FRESH|STALE|MISSING, last_candle, age_minutes} for completed candles."""
    if not candles:
        return {"status": "MISSING", "last_candle": None, "age_minutes": None}
    now = now.astimezone(IST)
    last = candles[-1]
    end = candle_end(last, timeframe)
    age_min = round((now - end).total_seconds() / 60, 1)
    if timeframe == "1D":
        expected = latest_completed_session(now, cal)
        ok = last.dt.date() >= expected
        if not ok and expected == now.date() and now.time() < DAILY_PUBLISH_GRACE:
            # Dhan may publish today's daily bar after the close; accept the prior session meanwhile.
            ok = last.dt.date() >= cal.previous_trading_day(expected)
    elif cal.is_market_open(now):
        ok = age_min <= FRESHNESS_BARS[timeframe] * TF_MINUTES[timeframe] + 5
    else:
        ok = last.dt.date() >= latest_started_session(now, cal)
    return {"status": "FRESH" if ok else "STALE", "last_candle": last.dt.isoformat(), "age_minutes": age_min}
