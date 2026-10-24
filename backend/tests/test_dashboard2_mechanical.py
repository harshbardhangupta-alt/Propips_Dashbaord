"""Dashboard 2 Mechanical Swing tests (SYNTHETIC data)."""
from datetime import timedelta

from app.core.market_calendar import get_calendar
from app.market_data.candles import Candle, aggregate_4h
from app.strategies import dashboard2_mechanical as d2
from tests.synthetic import daily_series, mech_scenario

CAL = get_calendar()
SIZING = {"allocation": 50_000, "risk_budget": 1_000}


def run(daily=None, h4=None, h1=None, now=None, p=None):
    n, d, f, h = mech_scenario()
    return d2.evaluate("TEST", daily if daily is not None else d, h4 if h4 is not None else f, h1 if h1 is not None else h,
                       now or n, CAL, p, SIZING)


def check(r, rule):
    return next(c for c in r.checks if c.rule == rule)


def test_scenario_qualifies_with_all_mandatory_rules():
    r = run()
    assert r.status == "QUALIFIED", r.reasons
    assert all(c.passed for c in r.checks if c.mandatory)
    assert r.grade in ("A", "A+") and r.score >= 75
    assert r.signal_key and r.valid_until is not None


def test_impulse_swing_points_and_bos():
    r = run()
    imp = r.details["impulse"]
    assert imp["low"] == 140.0 and imp["high"] == 170.0
    assert imp["bos_level"] == 150.0
    assert imp["low_time"] < imp["bos_time"] <= imp["high_time"]


def test_fibonacci_levels_reported():
    f = run().details["fibonacci"]
    assert f == {"fib_50": 155.0, "fib_618": 151.46, "fib_786": 146.42}


def test_trade_plan_is_one_to_three():
    r = run()
    risk = r.entry - r.stop_loss
    assert abs(r.target - (r.entry + 3 * risk)) <= 0.05
    assert r.reward_risk >= 3.0
    assert r.entry == 144.95  # confirmation high 144.90 + 1 tick
    assert r.stop_loss < 140.0  # below the demand zone low


def test_demand_zone_boundaries():
    z = run().details["demand_zone"]
    assert z["low"] == 140.0 and z["high"] == 142.0
    assert z["bos"] is not None


def test_score_components_sum():
    r = run()
    assert r.score == sum(c["points"] for c in r.components.values())
    assert set(r.components) == {"trend_structure", "impulse_bos", "pullback", "fibonacci", "demand_zone", "confirmation", "liquidity"}
    assert sum(c["max"] for c in r.components.values()) == 100


def test_daily_trend_failure_rejects():
    now, *_ = mech_scenario()
    r = run(daily=daily_series(now.date(), 120, 200, 144))
    assert r.status == "REJECTED" and not check(r, "A").passed


def _h1_with(pb_mod):
    now, daily, h4, h1 = mech_scenario()
    h1 = list(h1)
    pb_mod(h1)
    return now, daily, aggregate_4h(h1), h1


def test_three_red_candles_required():
    def mod(h1):
        # Turn the 3rd pullback candle green -> longest red run < 3 after the high
        i = len(h1) - 5
        c = h1[i]
        h1[i] = Candle(c.ts, c.close, c.high, c.low, c.open + 0.01 if c.open < c.close else c.open)
        c2 = h1[i - 2]
        h1[i - 2] = Candle(c2.ts, c2.close - 0.5, c2.high, c2.low, c2.close)

    now, daily, h4, h1 = _h1_with(mod)
    r = d2.evaluate("T", daily, h4, h1, now, CAL, None, SIZING)
    assert not check(r, "C").passed and r.status == "REJECTED"


def test_discount_requires_below_fifty_percent():
    now, daily, h4, h1 = mech_scenario()
    # Shallow pullback: scale pullback lows to stay above the 50% level (155).
    h1 = list(h1)
    pb = h1[-7:]
    new = []
    for c in pb:
        f = lambda x: 170 - (170 - x) * 0.4  # noqa: E731
        new.append(Candle(c.ts, f(c.open), f(c.high), f(c.low), f(c.close)))
    h1 = h1[:-7] + new
    r = d2.evaluate("T", daily, aggregate_4h(h1), h1, now, CAL, None, SIZING)
    assert not check(r, "D").passed and r.status == "REJECTED"


def test_confirmation_candle_required():
    now, daily, h4, h1 = mech_scenario()
    h1 = list(h1)[:-2]  # drop confirmation and inside bar
    later = now  # data still from the same session
    r = d2.evaluate("T", daily, aggregate_4h(h1), h1, later, CAL, None, SIZING)
    assert not check(r, "F").passed


def test_fibonacci_touch_alone_is_not_a_signal():
    """Price in the discount zone without a bullish candle must not qualify."""
    now, daily, h4, h1 = mech_scenario()
    h1 = list(h1)[:-2]
    r = d2.evaluate("T", daily, aggregate_4h(h1), h1, now, CAL, None, SIZING)
    assert check(r, "D").passed and r.status == "REJECTED"


def test_min_rr_enforced_by_extension_cap():
    p = d2.MechParams(max_target_extension=0.6)  # cap below the 3R target -> unrealistic
    r = run(p=p)
    assert not check(r, "H").passed and "unrealistic" in check(r, "H").detail


def test_entry_already_triggered_not_chased():
    now, daily, h4, h1 = mech_scenario()
    h1 = list(h1)
    c = h1[-1]
    h1[-1] = Candle(c.ts, c.open, 146.0, c.low, 145.8)
    r = d2.evaluate("T", daily, aggregate_4h(h1), h1, now, CAL, None, SIZING)
    assert not check(r, "H").passed and "already triggered" in check(r, "H").detail


def test_missing_timeframe_unavailable():
    r = run(h1=[])
    assert r.status == "UNAVAILABLE"


def test_stale_data_mandatory_failure():
    now, daily, h4, h1 = mech_scenario()
    r = d2.evaluate("T", daily, h4, h1, now + timedelta(days=10), CAL, None, SIZING)
    assert not check(r, "G").passed and r.status == "REJECTED"


def test_impulse_low_break_invalidates():
    now, daily, h4, h1 = mech_scenario()
    h1 = list(h1)
    c = h1[-3]
    h1[-3] = Candle(c.ts, c.open, c.high, 138.0, 138.5)
    r = d2.evaluate("T", daily, aggregate_4h(h1), h1, now, CAL, None, SIZING)
    assert r.status == "REJECTED"


def test_mandatory_failure_overrides_score():
    r = run(p=d2.MechParams(max_target_extension=0.6))
    assert r.score >= 60 and r.status == "REJECTED"


def test_grades():
    assert d2.grade_for(85) == "A+" and d2.grade_for(84.9) == "A" and d2.grade_for(75) == "A" and d2.grade_for(74) == "B"


def test_signal_key_deterministic():
    assert run().signal_key == run().signal_key
    assert d2.signal_key("A", 1, 2) != d2.signal_key("A", 1, 3)


def test_no_lookahead_future_bars_do_not_change_past_result():
    """Evaluating with data up to the confirmation must not depend on later bars (later bars are simply absent)."""
    r1 = run()
    now, daily, h4, h1 = mech_scenario()
    r2 = d2.evaluate("TEST", daily, h4, h1, now, CAL, None, SIZING)
    assert r1.entry == r2.entry and r1.stop_loss == r2.stop_loss
