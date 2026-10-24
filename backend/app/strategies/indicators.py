"""Deterministic technical indicators (no look-ahead: value[i] uses data[0..i] only)."""
from __future__ import annotations

from app.market_data.candles import Candle


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average, alpha = 2/(period+1), seeded with the SMA of the first `period` values."""
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    """Wilder's Average True Range."""
    n = len(candles)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    trs = [candles[0].high - candles[0].low]
    for i in range(1, n):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    val = sum(trs[1 : period + 1]) / period
    out[period] = val
    for i in range(period + 1, n):
        val = (val * (period - 1) + trs[i]) / period
        out[i] = val
    return out


def pivot_highs(candles: list[Candle], left: int = 2, right: int = 2) -> list[int]:
    """Indices i where high[i] is strictly greater than `left` bars before and >= `right` bars after.

    A pivot at i is only *confirmed* once bar i+right has completed, so the last
    `right` bars can never be pivots (prevents look-ahead bias).
    """
    out = []
    for i in range(left, len(candles) - right):
        h = candles[i].high
        if all(h > candles[j].high for j in range(i - left, i)) and all(h >= candles[j].high for j in range(i + 1, i + right + 1)):
            out.append(i)
    return out


def pivot_lows(candles: list[Candle], left: int = 2, right: int = 2) -> list[int]:
    out = []
    for i in range(left, len(candles) - right):
        lo = candles[i].low
        if all(lo < candles[j].low for j in range(i - left, i)) and all(lo <= candles[j].low for j in range(i + 1, i + right + 1)):
            out.append(i)
    return out


def fib_retracement(low: float, high: float, ratio: float) -> float:
    """Retracement level measured down from the impulse high: H - ratio*(H-L)."""
    return high - ratio * (high - low)


def round_to_tick(price: float, tick: float = 0.05, mode: str = "nearest") -> float:
    import math

    if tick <= 0:
        return round(price, 2)
    q = price / tick
    if mode == "up":
        q = math.ceil(q - 1e-9)
    elif mode == "down":
        q = math.floor(q + 1e-9)
    else:
        q = round(q)
    return round(q * tick, 2)
