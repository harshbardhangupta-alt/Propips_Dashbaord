"""Candle model, Dhan response parsing, completeness and 4-hour aggregation."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta

from app.core.timeutils import IST, MARKET_CLOSE, MARKET_OPEN, epoch_to_ist, ist_combine

TF_MINUTES = {"5m": 5, "15m": 15, "1H": 60, "4H": 240, "1D": 1440}


@dataclass(frozen=True)
class Candle:
    ts: float  # epoch seconds of candle START
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def dt(self) -> datetime:
        return epoch_to_ist(self.ts)

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time"] = self.dt.isoformat()
        return d


def parse_dhan_candles(body: dict) -> list[Candle]:
    """Parse Dhan's columnar response {open:[],high:[],low:[],close:[],volume:[],timestamp:[]}."""
    if not isinstance(body, dict):
        return []
    data = body.get("data", body) if isinstance(body.get("data"), dict) else body
    keys = ("open", "high", "low", "close", "timestamp")
    if not all(k in data for k in keys):
        return []
    n = min(len(data[k]) for k in keys)
    vols = data.get("volume") or [0] * n
    out = []
    for i in range(n):
        out.append(
            Candle(
                ts=float(data["timestamp"][i]),
                open=float(data["open"][i]),
                high=float(data["high"][i]),
                low=float(data["low"][i]),
                close=float(data["close"][i]),
                volume=float(vols[i]) if i < len(vols) and vols[i] is not None else 0.0,
            )
        )
    return out


def candle_end(c: Candle, timeframe: str) -> datetime:
    start = c.dt
    if timeframe == "1D":
        return ist_combine(start.date(), MARKET_CLOSE)
    end = start + timedelta(minutes=TF_MINUTES[timeframe])
    close_dt = ist_combine(start.date(), MARKET_CLOSE)
    return min(end, close_dt)


def is_complete(c: Candle, timeframe: str, now: datetime) -> bool:
    return candle_end(c, timeframe) <= now.astimezone(IST)


def completed_only(candles: list[Candle], timeframe: str, now: datetime) -> list[Candle]:
    """Drop the trailing in-progress candle(s). Mandatory decisions use completed candles only."""
    return [c for c in candles if is_complete(c, timeframe, now)]


def aggregate_4h(hourly: list[Candle]) -> list[Candle]:
    """Build session-anchored 4H candles from 60-minute candles.

    NSE session 09:15-15:30 gives two buckets per day: 09:15-13:15 and 13:15-15:30.
    Dhan does not offer a native 4H interval, so 4H is always derived from 60m data.
    """
    buckets: dict[tuple, list[Candle]] = {}
    session_start_min = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute
    for c in sorted(hourly, key=lambda x: x.ts):
        dt = c.dt
        minutes = dt.hour * 60 + dt.minute - session_start_min
        if minutes < 0:
            continue
        idx = minutes // 240
        buckets.setdefault((dt.date(), idx), []).append(c)
    out = []
    for (d, idx), cs in sorted(buckets.items()):
        start = ist_combine(d, time(MARKET_OPEN.hour, MARKET_OPEN.minute)) + timedelta(minutes=240 * idx)
        out.append(
            Candle(
                ts=start.timestamp(),
                open=cs[0].open,
                high=max(x.high for x in cs),
                low=min(x.low for x in cs),
                close=cs[-1].close,
                volume=sum(x.volume for x in cs),
            )
        )
    return out


def is_4h_complete(c: Candle, now: datetime) -> bool:
    return candle_end(c, "4H") <= now.astimezone(IST)


def validate_candles(candles: list[Candle]) -> tuple[list[Candle], list[str]]:
    """Sort, de-duplicate and drop malformed candles. Returns (clean, warnings)."""
    warnings: list[str] = []
    seen: dict[float, Candle] = {}
    bad = 0
    for c in candles:
        vals = (c.open, c.high, c.low, c.close)
        if any(v is None or math.isnan(v) or v <= 0 for v in vals) or c.high < max(c.open, c.close) - 1e-9 or c.low > min(c.open, c.close) + 1e-9:
            bad += 1
            continue
        seen[c.ts] = c
    if bad:
        warnings.append(f"Dropped {bad} malformed candle(s)")
    dupes = len(candles) - bad - len(seen)
    if dupes:
        warnings.append(f"Removed {dupes} duplicate candle(s)")
    return sorted(seen.values(), key=lambda x: x.ts), warnings


def count_intraday_gaps(candles: list[Candle], minutes: int) -> int:
    """Count missing bars inside the same session (data-quality metric)."""
    gaps = 0
    for a, b in zip(candles, candles[1:]):
        if a.dt.date() == b.dt.date():
            delta = (b.ts - a.ts) / 60
            if delta > minutes * 1.5:
                gaps += int(round(delta / minutes)) - 1
    return gaps
