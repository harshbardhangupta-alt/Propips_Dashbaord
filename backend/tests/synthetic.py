"""SYNTHETIC TEST DATA ONLY.

Deterministic, hand-built candle series used exclusively by the unit tests. These are
NOT market data and are never used by the application at runtime.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.core.market_calendar import get_calendar
from app.core.timeutils import IST
from app.market_data.candles import Candle, aggregate_4h

HOUR_STARTS = [time(9, 15), time(10, 15), time(11, 15), time(12, 15), time(13, 15), time(14, 15), time(15, 15)]


def trading_days_back(end: date, n: int) -> list[date]:
    cal = get_calendar()
    days = [end] if cal.is_trading_day(end) else []
    d = end
    while len(days) < n:
        d = cal.previous_trading_day(d)
        days.append(d)
    return sorted(days)


def daily_series(end: date, n: int, start: float, stop: float, volume: float = 1e6) -> list[Candle]:
    days = trading_days_back(end, n)
    out = []
    for i, d in enumerate(days):
        c = start + (stop - start) * i / (n - 1)
        o = c - 0.4
        out.append(Candle(datetime.combine(d, time(0, 0), IST).timestamp(), o, c + 0.8, o - 0.8, c, volume))
    return out


def bars_from_bucket(o: float, h: float, l: float, c: float, starts: list[datetime]) -> list[Candle]:
    """Split one 4H OHLC into consecutive 1H bars that aggregate back to exactly (o,h,l,c)."""
    n = len(starts)
    way = [o, l, h, c] if c >= o else [o, h, l, c]
    if n == 4:
        mid = (way[1] + way[2]) / 2
        pts = [way[0], way[1], mid, way[2], way[3]]
    elif n == 3:
        pts = way
    else:
        raise ValueError(n)
    out = []
    for k in range(n):
        a, b = pts[k], pts[k + 1]
        out.append(Candle(starts[k].timestamp(), a, max(a, b), min(a, b), b, 1e5))
    return out


def hourly_from_4h(days: list[date], buckets: list[tuple[float, float, float, float]]) -> list[Candle]:
    """buckets[i] covers day i//2, bucket i%2 (0 = 09:15-13:15 four bars, 1 = 13:15-15:30 three bars)."""
    out = []
    for i, b in enumerate(buckets):
        d = days[i // 2]
        hs = HOUR_STARTS[:4] if i % 2 == 0 else HOUR_STARTS[4:]
        out += bars_from_bucket(*b, [datetime.combine(d, t, IST) for t in hs])
    return out


def mech_scenario():
    """A Mechanical Swing BUY setup that satisfies every mandatory rule.

    Structure (4H): zig-zag advance -> swing high 150 -> decline -> base 140-142.5 ->
    displacement 142->150.5 (break of structure above 150) -> impulse high 170.
    Pullback (1H): 6 consecutive red candles to 141.8 (below the 50% level 155, inside the
    demand zone), then a bullish confirmation candle and one inside bar.
    Returns (now, daily, h4, h1).
    """
    now = datetime(2026, 10, 23, 16, 0, tzinfo=IST)  # Friday after the close
    buckets: list[tuple[float, float, float, float]] = []
    # 46 zig-zag prefix bars 118 -> ~143
    price = 118.0
    for i in range(46):
        up = i % 2 == 0
        o = price
        c = o + (1.6 if up else -0.6)
        buckets.append((o, max(o, c) + 0.3, min(o, c) - 0.3, c))
        price = c
    # rise to swing high 150
    for o, c in ((price, 146.0), (146.0, 148.5), (148.5, 149.0)):
        buckets.append((o, max(o, c) + 0.3, min(o, c) - 0.3, c))
    buckets[-1] = (148.5, 150.0, 148.2, 149.0)
    # decline 149 -> 141.5 with small bodies (lower highs)
    seq = [149.0, 147.6, 146.3, 145.0, 143.8, 142.6, 141.6]
    for a, b in zip(seq, seq[1:]):
        buckets.append((a, a + 0.2, b - 0.2, b))
    # base: small bodies, low 140.0 in the middle
    buckets += [(141.6, 142.3, 140.4, 141.9), (141.9, 142.4, 140.0, 141.7), (141.7, 142.5, 140.6, 142.0)]
    # displacement + impulse to 170
    buckets += [(142.0, 151.0, 141.8, 150.5), (150.5, 158.4, 150.2, 158.0), (158.0, 164.4, 157.6, 164.0), (164.0, 170.0, 163.5, 169.0)]
    n_days = (len(buckets) + 1) // 2 + 1
    days = trading_days_back(now.date(), n_days + (0 if len(buckets) % 2 == 0 else 1))
    if len(buckets) % 2 == 1:
        # pad one neutral bucket at the start so the impulse high lands in a day's second bucket
        buckets.insert(0, (117.8, 118.2, 117.6, 118.0))
    pre_days = days[: len(buckets) // 2]
    h1 = hourly_from_4h(pre_days, buckets)
    last_day = days[len(buckets) // 2]
    pb = [
        (169.0, 169.2, 164.8, 165.0),
        (165.0, 165.2, 158.8, 159.0),
        (159.0, 159.2, 152.8, 153.0),
        (153.0, 153.2, 146.8, 147.0),
        (147.0, 147.2, 141.8, 142.5),
        (142.4, 144.9, 142.2, 144.6),  # bullish confirmation
        (144.5, 144.7, 144.0, 144.3),  # inside bar, no trigger
    ]
    for t, (o, h, l, c) in zip(HOUR_STARTS, pb):
        h1.append(Candle(datetime.combine(last_day, t, IST).timestamp(), o, h, l, c, 1e5))
    h4 = aggregate_4h(h1)
    daily = daily_series(now.date(), 120, 90.0, 144.3)
    return now, daily, h4, h1
