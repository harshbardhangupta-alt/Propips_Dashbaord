from app.market_data.candles import Candle
from app.strategies.indicators import atr, ema, fib_retracement, pivot_highs, pivot_lows, round_to_tick


def test_ema_seed_and_recursion():
    vals = [1, 2, 3, 4, 5, 6]
    e = ema(vals, 3)
    assert e[:2] == [None, None]
    assert e[2] == 2.0  # SMA seed
    assert abs(e[3] - (4 * 0.5 + 2.0 * 0.5)) < 1e-12  # alpha = 2/(3+1)
    assert abs(e[5] - 5.0) < 1e-12


def test_ema_insufficient_data():
    assert ema([1, 2], 3) == [None, None]


def test_ema_no_lookahead():
    vals = list(range(1, 60))
    full = ema(vals, 10)
    part = ema(vals[:30], 10)
    assert full[:30] == part


def test_atr_constant_range():
    cs = [Candle(i, 10, 11, 9, 10) for i in range(30)]
    a = atr(cs, 14)
    assert a[13] is None and abs(a[14] - 2.0) < 1e-12 and abs(a[-1] - 2.0) < 1e-12


def test_pivots_confirmed_only():
    highs = [1, 2, 5, 2, 1, 2, 3, 9]
    cs = [Candle(i, h - 0.5, h, h - 1, h - 0.2) for i, h in enumerate(highs)]
    ph = pivot_highs(cs, 2, 2)
    assert ph == [2]  # index 7 (9) is not confirmed: no right-hand bars
    lows = pivot_lows(cs, 2, 2)
    assert 4 in lows


def test_fibonacci_levels():
    L, H = 100.0, 200.0
    assert fib_retracement(L, H, 0.5) == 150.0
    assert abs(fib_retracement(L, H, 0.618) - 138.2) < 1e-9
    assert abs(fib_retracement(L, H, 0.786) - 121.4) < 1e-9


def test_round_to_tick():
    assert round_to_tick(100.03, 0.05, "up") == 100.05
    assert round_to_tick(100.03, 0.05, "down") == 100.0
    assert round_to_tick(100.025, 0.05) in (100.0, 100.05)
