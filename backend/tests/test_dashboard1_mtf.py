"""Dashboard 1 MTF strategy tests (SYNTHETIC data)."""
from datetime import datetime, time, timedelta

from app.core.market_calendar import get_calendar
from app.core.timeutils import IST
from app.market_data.candles import Candle
from app.strategies import dashboard1_mtf as d1
from tests.synthetic import daily_series, trading_days_back

NOW = datetime(2026, 10, 23, 16, 0, tzinfo=IST)


def intraday(minutes: int, n: int, start: float, step: float, end: datetime = NOW) -> list[Candle]:
    """n completed bars ending at the last session close, stepping `step` per bar (synthetic)."""
    bars = []
    day = end.date()
    cal = get_calendar()
    t = datetime.combine(day, time(15, 30), IST) - timedelta(minutes=minutes)
    while len(bars) < n:
        if t.time() < time(9, 15):
            day = cal.previous_trading_day(day)
            t = datetime.combine(day, time(15, 30), IST) - timedelta(minutes=minutes)
            continue
        bars.append(t)
        t -= timedelta(minutes=minutes)
    bars.reverse()
    out = []
    p = start
    for b in bars:
        o, c = p, p + step
        out.append(Candle(b.timestamp(), o, max(o, c) + 0.1, min(o, c) - 0.1, c, 1000))
        p = c
    return out


def h4_series(n, start, step):
    days = trading_days_back(NOW.date(), (n + 1) // 2)
    out = []
    p = start
    for i in range(n):
        d = days[i // 2]
        t = time(9, 15) if i % 2 == 0 else time(13, 15)
        o, c = p, p + step
        out.append(Candle(datetime.combine(d, t, IST).timestamp(), o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        p = c
    return out


def bull():
    return (daily_series(NOW.date(), 120, 100, 160), h4_series(70, 120, 0.5), intraday(15, 40, 150, 0.2), intraday(5, 40, 155, 0.05))


def test_all_bullish_confirms():
    r = d1.evaluate(*bull(), NOW, get_calendar())
    assert r.daily.status == "BULLISH" and r.daily.checks["ema50_rising"]
    assert r.h4.status == "BULLISH" and not r.h4.checks["bearish_reversal"]
    assert r.m15.status == "CONFIRMED"
    assert r.m5.status == "MOMENTUM_UP"
    assert r.bias == "BULLISH" and r.confirmation == "CONFIRMED" and r.quality == 4
    assert r.entry_conditions_ok


def test_daily_below_ema_blocks_entry():
    daily, h4, m15, m5 = bull()
    daily = daily_series(NOW.date(), 120, 160, 100)
    r = d1.evaluate(daily, h4, m15, m5, NOW, get_calendar())
    assert r.daily.status == "BEARISH" and not r.entry_conditions_ok


def test_close_above_falling_ema_is_not_bullish():
    daily = daily_series(NOW.date(), 120, 155, 150)
    daily[-1] = Candle(daily[-1].ts, 150, 153.5, 149, 153.0)
    r = d1.evaluate_daily(daily, {"status": "FRESH"})
    assert r.checks["close_above_ema50"] and not r.checks["ema50_rising"] and not r.passed


def test_h4_bearish_reversal_detected():
    h4 = h4_series(70, 120, 0.5)
    # Last bar closes below the most recent confirmed swing low -> bearish reversal.
    lows = [c.low for c in h4]
    h4[-1] = Candle(h4[-1].ts, h4[-2].close, h4[-2].close, min(lows) - 5, min(lows) - 4)
    r = d1.evaluate_h4(h4, {"status": "FRESH"})
    assert r.status in ("BEARISH", "NEUTRAL") and not r.passed


def test_m15_not_confirmed_when_falling():
    r = d1.evaluate_m15(intraday(15, 40, 160, -0.3), {"status": "FRESH"})
    assert r.status == "NOT_CONFIRMED" and not r.passed


def test_m5_waiting_when_below_ema():
    r = d1.evaluate_m5(intraday(5, 40, 160, -0.1), {"status": "FRESH"})
    assert r.status == "WAITING"


def test_missing_timeframe_rejected():
    daily, h4, m15, m5 = bull()
    r = d1.evaluate(daily, h4, [], m5, NOW, get_calendar())
    assert r.m15.status == "UNAVAILABLE" and r.confirmation == "UNAVAILABLE" and not r.entry_conditions_ok
    assert any("15m" in x for x in r.reasons)


def test_stale_data_blocks_entry():
    daily, h4, m15, m5 = bull()
    later = NOW + timedelta(days=7)  # data now a week old
    r = d1.evaluate(daily, h4, m15, m5, later, get_calendar())
    assert not r.entry_conditions_ok
    assert any("STALE" in x for x in r.reasons)


def test_dashboard1_min_rr_is_two_not_three():
    assert d1.DEFAULT_MIN_RR == 2.0
