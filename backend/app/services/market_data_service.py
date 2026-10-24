"""Candle and quote retrieval from Dhan with caching, validation and freshness metadata."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.market_calendar import get_calendar
from app.core.timeutils import IST, MARKET_CLOSE, iso, now_ist
from app.database.models import Instrument, Quote, utcnow
from app.integrations.dhan_client import DhanClient, DhanError, DhanStatus
from app.market_data.cache import candle_cache
from app.market_data.candles import Candle, aggregate_4h, completed_only, parse_dhan_candles, validate_candles

DATA_SOURCE_INTRADAY = "DHAN_REST_CHARTS_INTRADAY"
DATA_SOURCE_DAILY = "DHAN_REST_CHARTS_HISTORICAL"
DATA_SOURCE_QUOTE = "DHAN_REST_MARKETFEED_OHLC"

# (lookback calendar days, cache seconds)
FETCH_PLAN = {"1D": (400, 1800), "1H": (59, 300), "15m": (7, 180), "5m": (4, 60)}
INTERVAL = {"1H": 60, "15m": 15, "5m": 5}


@dataclass
class CandleSet:
    timeframe: str
    candles: list[Candle]
    source: str
    fetched_at: datetime
    warnings: list[str] = field(default_factory=list)


def _fmt_dt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def fetch_raw(client: DhanClient, inst: Instrument, timeframe: str, now: datetime) -> CandleSet:
    if not inst.security_id:
        raise DhanError(DhanStatus.INVALID_REQUEST, f"{inst.symbol} has no Dhan security id mapping")
    key = (inst.security_id, timeframe)
    hit = candle_cache.get(key)
    if hit is not None:
        return hit
    days, ttl = FETCH_PLAN["1H" if timeframe == "4H" else timeframe]
    now = now.astimezone(IST)
    if timeframe == "1D":
        body = client.historical_daily(inst.security_id, (now - timedelta(days=days)).date().isoformat(), (now + timedelta(days=1)).date().isoformat(), inst.exchange_segment)
        src = DATA_SOURCE_DAILY
    else:
        tf = "1H" if timeframe == "4H" else timeframe
        start = (now - timedelta(days=days)).replace(hour=9, minute=15, second=0, microsecond=0)
        end = now.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute, second=0, microsecond=0)
        body = client.intraday(inst.security_id, INTERVAL[tf], _fmt_dt(start), _fmt_dt(end), inst.exchange_segment)
        src = DATA_SOURCE_INTRADAY
    candles, warnings = validate_candles(parse_dhan_candles(body))
    cs = CandleSet(timeframe, candles, src, utcnow(), warnings)
    candle_cache.set(key, cs, ttl)
    return cs


def get_completed(client: DhanClient, inst: Instrument, timeframe: str, now: datetime | None = None) -> CandleSet:
    """Completed, validated candles for 1D/4H/1H/15m/5m. 4H is aggregated from 60m."""
    now = now or now_ist()
    if timeframe == "4H":
        hourly = fetch_raw(client, inst, "1H", now)
        h4 = [c for c in aggregate_4h(completed_only(hourly.candles, "1H", now)) if completed_only([c], "4H", now)]
        return CandleSet("4H", h4, hourly.source + " (aggregated 60m->4H)", hourly.fetched_at, hourly.warnings)
    raw = fetch_raw(client, inst, timeframe, now)
    return CandleSet(timeframe, completed_only(raw.candles, timeframe, now), raw.source, raw.fetched_at, raw.warnings)


# ------------------------------------------------------------------ quotes
def refresh_quotes(db: Session, client: DhanClient, instruments: list[Instrument]) -> dict:
    ids = {i.security_id: i for i in instruments if i.security_id}
    if not ids:
        return {"updated": 0, "requested": 0}
    data = client.ohlc(list(ids.keys()))
    now = utcnow()
    n = 0
    for sid, row in data.items():
        inst = ids.get(str(sid))
        if inst is None or not isinstance(row, dict):
            continue
        ltp = row.get("last_price")
        if ltp is None or float(ltp) <= 0:
            continue
        o = row.get("ohlc") or {}
        q = db.get(Quote, inst.id) or Quote(instrument_id=inst.id)
        q.ltp = float(ltp)
        q.open = float(o["open"]) if o.get("open") else None
        q.high = float(o["high"]) if o.get("high") else None
        q.low = float(o["low"]) if o.get("low") else None
        # Dhan's OHLC snapshot "close" is the previous session close.
        q.prev_close = float(o["close"]) if o.get("close") else None
        q.source = DATA_SOURCE_QUOTE
        q.fetched_at = now
        db.merge(q)
        n += 1
    return {"updated": n, "requested": len(ids)}


def quote_view(q: Quote | None) -> dict:
    """Classify a stored quote honestly. REST snapshots are never labelled 'live'."""
    if q is None or q.ltp is None:
        return {"ltp": None, "change": None, "pct_change": None, "fetched_at": None, "data_state": "NO_DATA", "source": None}
    cal = get_calendar()
    now = now_ist()
    fetched = q.fetched_at.replace(tzinfo=None)
    age = (utcnow() - fetched).total_seconds()
    if cal.is_market_open(now):
        state = "RECENT_SNAPSHOT" if age <= 120 else ("DELAYED_SNAPSHOT" if age <= 600 else "STALE")
    else:
        state = "LAST_AVAILABLE" if age <= 24 * 3600 * 4 else "STALE"
    change = pct = None
    if q.prev_close:
        change = round(q.ltp - q.prev_close, 2)
        pct = round(change / q.prev_close * 100, 2)
    return {"ltp": q.ltp, "change": change, "pct_change": pct, "prev_close": q.prev_close, "fetched_at": iso(q.fetched_at),
            "data_state": state, "source": q.source, "age_seconds": int(age)}
