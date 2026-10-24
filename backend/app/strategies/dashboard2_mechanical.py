"""Dashboard 2 — Mechanical Swing Trading System (BUY side only).

Implements rules A–H of the Mechanical Swing Trading System as specified in the
project brief. The original PDF / text files were NOT present in the repository when
this was built, so every threshold below is an explicit, documented interpretation
(README §"Strategy interpretation notes"). All decisions use COMPLETED candles only.

Timeframes (Rule G)
  Daily  -> primary trend (Rule A: 50 EMA)
  4H     -> impulse, swing structure, break of structure, Fibonacci, demand zones (B, D, E)
  1H     -> pullback (Rule C: >=3 consecutive red candles) and confirmation (Rule F)

Mandatory rules (any failure => REJECTED regardless of score)
  A  latest daily close > Daily EMA50
  B  confirmed bullish impulse L->H on 4H with a close above the prior swing high (BOS),
     size >= MIN_IMPULSE_ATR x ATR14(4H); no newer high after H; impulse low not broken
  C  >= 3 consecutive completed bearish (close < open) 1H candles in the pullback after H
  D  pullback low strictly below the 50% retracement H - 0.5(H-L) (and above L)
  E  a valid historical demand zone (look-left) that the pullback reached and did not break
  F  a completed bullish (close > open) 1H candle after the red run, at/after the discount touch
  G  all three timeframes present and FRESH
  H  entry = confirmation high + 1 tick (buy-stop); stop = min(pullback low, zone low) - buffer;
     target = entry + 3 x (entry - stop); RR >= 3; target <= 1.618 extension of the impulse;
     risk per share <= MAX_RISK_PCT of entry; position sizing feasible
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.market_calendar import MarketCalendar
from app.core.timeutils import IST, MARKET_CLOSE, ist_combine
from app.market_data.candles import Candle, candle_end
from app.market_data.validation import freshness
from app.strategies.indicators import atr, ema, fib_retracement, pivot_highs, pivot_lows, round_to_tick

STRATEGY_ID = "DASHBOARD2_MECHANICAL"
PULLBACK_TF = "1H"
STRUCTURE_TF = "4H"


@dataclass
class MechParams:
    ema_period: int = 50
    ema_slope_lookback: int = 5
    pivot_left: int = 2
    pivot_right: int = 2
    min_impulse_atr: float = 2.0
    min_red_candles: int = 3
    fib_threshold: float = 0.50
    confirmation_max_age_bars: int = 6  # 1H bars after confirmation before the setup is stale
    stop_buffer_atr: float = 0.10  # x ATR14(4H) below the structural low
    min_rr: float = 3.0
    max_target_extension: float = 1.618  # target must be <= L + 1.618 (H - L)
    max_risk_pct: float = 8.0
    zone_lookback_bars: int = 150  # 4H bars to look left for demand zones
    displacement_body_atr: float = 1.2
    base_body_atr: float = 0.6
    zone_max_base: int = 3
    zone_bos_window: int = 10
    zone_touch_tolerance_atr: float = 0.25
    min_daily_bars: int = 60
    min_4h_bars: int = 60
    min_1h_bars: int = 30
    tick: float = 0.05


@dataclass
class RuleCheck:
    rule: str
    name: str
    passed: bool
    mandatory: bool
    detail: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class DemandZone:
    low: float
    high: float
    base_start_ts: float
    base_end_ts: float
    displacement_ts: float
    bos_ts: float | None
    prior_reactions: int
    gap: bool

    def to_dict(self) -> dict:
        return {
            "low": round(self.low, 2),
            "high": round(self.high, 2),
            "base_start": datetime.fromtimestamp(self.base_start_ts, IST).isoformat(),
            "base_end": datetime.fromtimestamp(self.base_end_ts, IST).isoformat(),
            "displacement": datetime.fromtimestamp(self.displacement_ts, IST).isoformat(),
            "bos": datetime.fromtimestamp(self.bos_ts, IST).isoformat() if self.bos_ts else None,
            "prior_reactions": self.prior_reactions,
            "gap": self.gap,
        }


@dataclass
class MechResult:
    symbol: str
    status: str  # QUALIFIED | REJECTED | UNAVAILABLE
    score: float
    grade: str
    checks: list[RuleCheck]
    components: dict
    details: dict
    entry: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    reward_risk: float | None = None
    signal_key: str | None = None
    valid_until: datetime | None = None
    reasons: list[str] = field(default_factory=list)

    def mandatory_failures(self) -> list[RuleCheck]:
        return [c for c in self.checks if c.mandatory and not c.passed]


def _ts(c: Candle) -> str:
    return c.dt.isoformat()


def grade_for(score: float) -> str:
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    return "C"


def signal_key(symbol: str, impulse_high_ts: float, confirmation_ts: float) -> str:
    raw = f"{STRATEGY_ID}|{symbol}|{int(impulse_high_ts)}|{int(confirmation_ts)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def signal_valid_until(confirmation: Candle, cal: MarketCalendar) -> datetime:
    """A signal stays valid until the close of the next trading session after its confirmation candle."""
    return ist_combine(cal.next_trading_day(confirmation.dt.date()), MARKET_CLOSE)


# --------------------------------------------------------------------------- structure
@dataclass
class Impulse:
    low: float
    high: float
    low_idx: int
    high_idx: int
    bos_level: float
    bos_idx: int
    prior_high_idx: int
    atr_multiple: float


def find_impulse(h4: list[Candle], p: MechParams) -> tuple[Impulse | None, str]:
    if len(h4) < p.min_4h_bars:
        return None, f"Only {len(h4)} completed 4H candles (need {p.min_4h_bars})"
    highs = pivot_highs(h4, p.pivot_left, p.pivot_right)
    lows = pivot_lows(h4, p.pivot_left, p.pivot_right)
    if not highs or not lows:
        return None, "No confirmed 4H swing points"
    ih = highs[-1]
    H = h4[ih].high
    later_high = max((c.high for c in h4[ih + 1 :]), default=0)
    if later_high > H:
        return None, "Price made a higher high after the last confirmed swing high (impulse still extending, no pullback yet)"
    prior_lows = [i for i in lows if i < ih]
    if not prior_lows:
        return None, "No confirmed swing low before the swing high"
    il = prior_lows[-1]
    L = min(c.low for c in h4[il : ih + 1])
    prior_highs = [i for i in highs if i < il]
    if not prior_highs:
        return None, "No prior swing high before the impulse low to define a break of structure"
    ip = prior_highs[-1]
    level = h4[ip].high
    bos_idx = next((i for i in range(il + 1, ih + 1) if h4[i].close > level), None)
    if bos_idx is None:
        return None, f"No close above prior swing high {level:.2f} during the impulse (no break of structure)"
    a = atr(h4, 14)[ih]
    if not a:
        return None, "Insufficient 4H history for ATR"
    mult = (H - L) / a
    if mult < p.min_impulse_atr:
        return None, f"Impulse {H - L:.2f} is only {mult:.2f}x ATR14(4H); need >= {p.min_impulse_atr}x"
    broken = next((c for c in h4[ih + 1 :] if c.close < L), None)
    if broken:
        return None, f"4H close {broken.close:.2f} below impulse low {L:.2f} at {_ts(broken)} (impulse invalidated)"
    return Impulse(L, H, il, ih, level, bos_idx, ip, mult), ""


def find_demand_zones(h4: list[Candle], upto_idx: int, p: MechParams) -> list[DemandZone]:
    """Look-left demand-zone detection on 4H candles up to (and including) ``upto_idx``.

    A zone is a base of 1..zone_max_base small-bodied candles immediately followed by a
    bullish displacement candle (body >= displacement_body_atr x ATR14) and then a
    structural break (a close above the highest high of the 10 bars preceding the base)
    within zone_bos_window bars. Zone = [lowest low of base, highest body-top of base].
    Zones later violated by a 4H close below their low (before the impulse high) are
    discarded. These are technical zones only; they do not prove institutional orders.
    """
    atrs = atr(h4, 14)
    start = max(15, upto_idx - p.zone_lookback_bars)
    zones: list[DemandZone] = []
    for d in range(start, upto_idx + 1):
        c = h4[d]
        a = atrs[d]
        if not a or not c.bullish or c.body < p.displacement_body_atr * a:
            continue
        base = []
        j = d - 1
        while j >= 0 and len(base) < p.zone_max_base and h4[j].body <= p.base_body_atr * (atrs[j] or a):
            base.insert(0, j)
            j -= 1
        if not base:
            continue  # no small-bodied base directly before the displacement
        b0, b1 = base[0], base[-1]
        zlow = min(h4[i].low for i in base)
        ztop = max(max(h4[i].open, h4[i].close) for i in base)
        if ztop <= zlow:
            ztop = max(h4[i].high for i in base)
        ref_hi = max((x.high for x in h4[max(0, b0 - 10) : b0]), default=None)
        if ref_hi is None:
            continue
        bos = next((i for i in range(d, min(len(h4), d + p.zone_bos_window + 1)) if i <= upto_idx and h4[i].close > ref_hi), None)
        if bos is None:
            continue
        violated = any(x.close < zlow for x in h4[d + 1 : upto_idx + 1])
        if violated:
            continue
        reactions = 0
        k = max(0, b0 - p.zone_lookback_bars)
        while k < b0 - 3:
            x = h4[k]
            if x.low <= ztop and x.low >= zlow - 0.5 * a and all(y.close > ztop for y in h4[k + 1 : k + 4]):
                reactions += 1
                k += 4
            else:
                k += 1
        gap = c.low > h4[b1].high
        zones.append(DemandZone(zlow, ztop, h4[b0].ts, h4[b1].ts, c.ts, h4[bos].ts, reactions, gap))
    return zones


# --------------------------------------------------------------------------- evaluation
def evaluate(
    symbol: str,
    daily: list[Candle],
    h4: list[Candle],
    h1: list[Candle],
    now: datetime,
    cal: MarketCalendar,
    p: MechParams | None = None,
    sizing: dict | None = None,
) -> MechResult:
    """Evaluate the Mechanical Swing rules for one symbol. Inputs must be COMPLETED candles.

    ``sizing`` (optional): {"allocation": float, "risk_budget": float} used for the
    execution-feasibility score and suggested quantity.
    """
    p = p or MechParams()
    checks: list[RuleCheck] = []
    comp: dict[str, dict] = {}
    details: dict = {"timeframes": {}}
    tick = p.tick

    def add(rule, name, passed, mandatory, detail):
        checks.append(RuleCheck(rule, name, bool(passed), mandatory, detail))

    # ---- Rule G: data availability & freshness
    frs = {"1D": freshness(daily, "1D", now, cal), "4H": freshness(h4, "4H", now, cal), "1H": freshness(h1, "1H", now, cal)}
    details["timeframes"] = frs
    missing = [tf for tf, f in frs.items() if f["status"] == "MISSING"]
    stale = [tf for tf, f in frs.items() if f["status"] == "STALE"]
    enough = len(daily) >= p.min_daily_bars and len(h4) >= p.min_4h_bars and len(h1) >= p.min_1h_bars
    if missing or not enough:
        add("G", "MTF data availability", False, True,
            f"Missing/insufficient data: missing={missing}, daily={len(daily)}, 4H={len(h4)}, 1H={len(h1)} completed candles")
        return MechResult(symbol, "UNAVAILABLE", 0, "-", checks, {}, details, reasons=[checks[-1].detail])
    add("G", "MTF data freshness", not stale, True, "All timeframes fresh" if not stale else f"Stale timeframe data: {stale}")

    # ---- Rule A: Daily 50 EMA
    de = ema([c.close for c in daily], p.ema_period)
    dclose, dema = daily[-1].close, de[-1]
    rising = de[-1] > de[-1 - p.ema_slope_lookback]
    above = dclose > dema
    details["daily"] = {"close": round(dclose, 2), "ema50": round(dema, 2), "ema50_rising": rising, "candle": _ts(daily[-1]),
                        "bias": "BULLISH" if above and rising else ("BEARISH" if not above and not rising else "NEUTRAL")}
    add("A", "Daily close above 50 EMA", above, True, f"Close {dclose:.2f} vs EMA50 {dema:.2f}")

    # ---- Rule B: impulse & BOS (4H)
    imp, why = find_impulse(h4, p)
    a4_series = atr(h4, 14)
    a4 = a4_series[-1] or 0.0
    hh = pivot_highs(h4, p.pivot_left, p.pivot_right)
    hl = pivot_lows(h4, p.pivot_left, p.pivot_right)
    struct_bull = len(hh) >= 2 and len(hl) >= 2 and h4[hh[-1]].high > h4[hh[-2]].high and h4[hl[-1]].low > h4[hl[-2]].low
    details["h4"] = {"structure": "HIGHER_HIGHS_HIGHER_LOWS" if struct_bull else "MIXED", "atr14": round(a4, 2), "candle": _ts(h4[-1])}
    add("B", "Confirmed bullish impulse + break of structure", imp is not None, True,
        why if imp is None else f"Impulse {imp.low:.2f} -> {imp.high:.2f} ({imp.atr_multiple:.1f}x ATR), BOS above {imp.bos_level:.2f} at {_ts(h4[imp.bos_idx])}")

    trend_pts = (10 if above else 0) + (5 if rising else 0) + (5 if struct_bull else 0)
    comp["trend_structure"] = {"points": trend_pts, "max": 20, "detail": f"close>EMA50={above}, EMA rising={rising}, 4H HH/HL={struct_bull}"}

    if imp is None:
        for rule, name in (("C", "Three consecutive red candles"), ("D", "Fibonacci discount below 50%"), ("E", "Historical demand zone"), ("F", "Bullish confirmation candle"), ("H", "Minimum 1:3 reward-to-risk")):
            add(rule, name, False, True, "Not evaluated: no valid impulse")
        comp.update({k: {"points": 0, "max": m, "detail": "No impulse"} for k, m in (("impulse_bos", 15), ("pullback", 15), ("fibonacci", 15), ("demand_zone", 15), ("confirmation", 10))})
        comp["liquidity"] = _liquidity(daily, None, sizing, frs)
        return _finish(symbol, checks, comp, details, None, None, None, None, None, None)

    L, H = imp.low, imp.high
    fib50, fib618, fib786 = fib_retracement(L, H, 0.5), fib_retracement(L, H, 0.618), fib_retracement(L, H, 0.786)
    details["impulse"] = {
        "low": round(L, 2), "high": round(H, 2),
        "low_time": _ts(h4[imp.low_idx]), "high_time": _ts(h4[imp.high_idx]),
        "bos_level": round(imp.bos_level, 2), "bos_time": _ts(h4[imp.bos_idx]),
        "prior_swing_high_time": _ts(h4[imp.prior_high_idx]), "atr_multiple": round(imp.atr_multiple, 2),
    }
    details["fibonacci"] = {"fib_50": round(fib50, 2), "fib_618": round(fib618, 2), "fib_786": round(fib786, 2)}
    imp_pts = 10 + (5 if imp.atr_multiple >= 3 else 3 if imp.atr_multiple >= 2.5 else 1)
    comp["impulse_bos"] = {"points": imp_pts, "max": 15, "detail": f"BOS confirmed; impulse {imp.atr_multiple:.1f}x ATR"}

    # ---- Pullback on 1H, after the 1H bar that printed H
    h4_hi = h4[imp.high_idx]
    window_end = candle_end(h4_hi, "4H").timestamp()
    in_bar = [i for i, c in enumerate(h1) if h4_hi.ts <= c.ts < window_end]
    if not in_bar:
        add("C", "Three consecutive red candles", False, True, "1H candles for the impulse-high bar are missing")
        for rule, name in (("D", "Fibonacci discount below 50%"), ("E", "Historical demand zone"), ("F", "Bullish confirmation candle"), ("H", "Minimum 1:3 reward-to-risk")):
            add(rule, name, False, True, "Not evaluated: 1H data gap")
        comp.update({k: {"points": 0, "max": m, "detail": "1H data gap"} for k, m in (("pullback", 15), ("fibonacci", 15), ("demand_zone", 15), ("confirmation", 10))})
        comp["liquidity"] = _liquidity(daily, None, sizing, frs)
        return _finish(symbol, checks, comp, details, None, None, None, None, None, None)
    j0 = max(in_bar, key=lambda i: h1[i].high)
    pb = h1[j0 + 1 :]
    pb_idx0 = j0 + 1

    # Rule C: last run of >= min_red consecutive red candles
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(pb):
        if pb[i].bearish:
            s = i
            while i < len(pb) and pb[i].bearish:
                i += 1
            runs.append((s, i - 1))
        else:
            i += 1
    good_runs = [r for r in runs if r[1] - r[0] + 1 >= p.min_red_candles]
    max_run = max((r[1] - r[0] + 1 for r in runs), default=0)
    run = good_runs[-1] if good_runs else None
    add("C", f"At least {p.min_red_candles} consecutive red {PULLBACK_TF} candles", run is not None, True,
        f"Longest red run in pullback: {max_run}" + (f"; qualifying run {_ts(pb[run[0]])} -> {_ts(pb[run[1]])}" if run else ""))

    # Rule F: first bullish candle after that run
    conf_i = None
    if run is not None:
        conf_i = next((k for k in range(run[1] + 1, len(pb)) if pb[k].bullish), None)
    upto = conf_i if conf_i is not None else len(pb) - 1
    pb_slice = pb[: upto + 1] if pb else []
    pb_low = min((c.low for c in pb_slice), default=None)
    touch_i = next((k for k, c in enumerate(pb) if c.low < fib50), None)

    # Rule D: discount
    disc_ok = pb_low is not None and pb_low < fib50 and pb_low > L and touch_i is not None and (conf_i is None or touch_i <= conf_i)
    retr = (H - pb_low) / (H - L) if pb_low is not None and H > L else None
    details["pullback"] = {
        "low": round(pb_low, 2) if pb_low else None,
        "retracement_pct": round(retr * 100, 1) if retr is not None else None,
        "red_run_max": max_run,
        "discount_touch_time": _ts(pb[touch_i]) if touch_i is not None else None,
        "bars_since_high": len(pb),
    }
    if pb_low is not None and pb_low <= L:
        dmsg = f"Pullback low {pb_low:.2f} broke the impulse low {L:.2f} (setup invalid)"
    elif pb_low is None:
        dmsg = "No pullback candles yet"
    else:
        dmsg = f"Pullback low {pb_low:.2f} vs 50% level {fib50:.2f} (retracement {retr * 100:.1f}%)"
    add("D", "Price reached the discount zone (below 50% retracement)", disc_ok, True, dmsg)

    # Pullback quality score
    pb_pts = 10 if run else 0
    if run and pb:
        bars = upto + 1
        a1 = atr(h1, 14)[-1] or 0.0
        # An orderly pullback has no single 1H candle wider than 2.5x ATR14(1H).
        wild = bool(a1) and any(c.range > 2.5 * a1 for c in pb_slice)
        pb_pts += 5 if (3 <= bars <= 30 and not wild) else 2
    comp["pullback"] = {"points": pb_pts, "max": 15, "detail": f"red run {max_run}, bars since high {len(pb)}"}

    fib_pts = 0
    if disc_ok:
        fib_pts = 8
        if fib786 <= pb_low <= fib618:
            fib_pts += 7
        elif fib618 < pb_low < fib50:
            fib_pts += 4
        else:
            fib_pts += 2
    comp["fibonacci"] = {"points": fib_pts, "max": 15, "detail": dmsg}

    # ---- Rule E: demand zone (look-left)
    zones = find_demand_zones(h4, imp.high_idx, p)
    tol = p.zone_touch_tolerance_atr * a4
    zone = None
    zone_msg = "No unviolated demand zone in the discount area"
    if pb_low is not None:
        candidates = [z for z in zones if z.high >= L - tol and z.low <= fib50]
        touched = [z for z in candidates if pb_low <= z.high + tol and pb_low >= z.low - tol]
        broken = [z for z in touched if any(c.close < z.low for c in pb_slice)]
        valid = [z for z in touched if z not in broken]
        if valid:
            # Prefer a zone that contains the pullback low, then the most recent displacement.
            zone = min(valid, key=lambda z: (not (z.low <= pb_low <= z.high), -z.displacement_ts))
            zone_msg = f"Pullback low {pb_low:.2f} reached demand zone {zone.low:.2f}-{zone.high:.2f} ({zone.prior_reactions} prior reaction(s))"
        elif broken:
            zone_msg = f"Demand zone {broken[0].low:.2f}-{broken[0].high:.2f} was broken by a {PULLBACK_TF} close below it"
        elif candidates:
            near = min(candidates, key=lambda z: abs(pb_low - z.high))
            zone_msg = f"Nearest zone {near.low:.2f}-{near.high:.2f} not reached (pullback low {pb_low:.2f})"
    details["demand_zone"] = zone.to_dict() if zone else None
    details["demand_zones_found"] = len(zones)
    add("E", "Historical demand zone (look-left) reached", zone is not None, True, zone_msg)
    dz_pts = 0
    if zone:
        dz_pts = 8 + (4 if zone.low <= pb_low <= zone.high else 2) + min(3, zone.prior_reactions + (1 if zone.gap else 0))
    comp["demand_zone"] = {"points": min(15, dz_pts), "max": 15, "detail": zone_msg}

    # ---- Rule F: confirmation
    conf = pb[conf_i] if conf_i is not None else None
    conf_ok = conf is not None and disc_ok
    age = (len(pb) - 1 - conf_i) if conf_i is not None else None
    fmsg = "No completed bullish candle after the red pullback run yet"
    if conf is not None:
        fmsg = f"Bullish {PULLBACK_TF} candle {_ts(conf)} O {conf.open:.2f} C {conf.close:.2f}"
        if age is not None and age > p.confirmation_max_age_bars:
            conf_ok = False
            fmsg += f" is stale ({age} bars old > {p.confirmation_max_age_bars})"
    add("F", "Completed bullish confirmation candle", conf_ok, True, fmsg)
    conf_pts = 0
    if conf is not None:
        prev = pb[conf_i - 1] if conf_i > 0 else h1[j0]
        engulf = conf.close > prev.open and conf.open <= prev.close
        above_prev = conf.close > prev.high
        strong = conf.range > 0 and conf.body / conf.range >= 0.5
        conf_pts = 5 + (3 if (engulf or above_prev) else 0) + (2 if strong else 0)
        details["confirmation"] = {"time": _ts(conf), "open": conf.open, "high": conf.high, "low": conf.low, "close": conf.close,
                                   "engulfing": engulf, "close_above_prev_high": above_prev, "strong_body": strong, "bars_since": age}
    comp["confirmation"] = {"points": conf_pts if conf_ok else 0, "max": 10, "detail": fmsg}

    # ---- Rule H: trade plan
    entry = stop = target = rr = None
    vu = None
    key = None
    hmsg = "Not calculated: earlier mandatory rule failed"
    h_ok = False
    if conf is not None and pb_low is not None:
        entry = round_to_tick(conf.high + tick, tick, "up")
        struct_low = min(pb_low, zone.low) if zone else pb_low
        stop = round_to_tick(struct_low - max(p.stop_buffer_atr * a4, tick), tick, "down")
        risk = entry - stop
        if risk <= 0:
            hmsg = "Invalid stop (>= entry)"
        else:
            target = round_to_tick(entry + p.min_rr * risk, tick, "up")
            rr = round((target - entry) / risk, 2)
            ext = L + p.max_target_extension * (H - L)
            risk_pct = risk / entry * 100
            triggered = next((c for c in pb[conf_i + 1 :] if c.high >= entry), None)
            if rr < p.min_rr:
                hmsg = f"Reward:risk {rr} below {p.min_rr}"
            elif target > ext:
                hmsg = f"3R target {target:.2f} beyond {p.max_target_extension} impulse extension {ext:.2f} (structurally unrealistic)"
            elif risk_pct > p.max_risk_pct:
                hmsg = f"Risk per share {risk_pct:.1f}% of entry exceeds {p.max_risk_pct}%"
            elif triggered is not None:
                hmsg = f"Entry {entry:.2f} already triggered at {_ts(triggered)} before detection; not chased"
            else:
                h_ok = True
                hmsg = f"Entry {entry:.2f} / Stop {stop:.2f} / Target {target:.2f} = 1:{rr}"
            details["plan"] = {"structural_low": round(struct_low, 2), "risk_per_share": round(risk, 2), "risk_pct": round(risk_pct, 2),
                               "target_extension_cap": round(ext, 2), "entry_rule": "Buy-stop 1 tick above confirmation candle high"}
        key = signal_key(symbol, h4_hi.ts, conf.ts)
        vu = signal_valid_until(conf, cal)
    add("H", f"Minimum 1:{p.min_rr:g} reward-to-risk with realistic target", h_ok, True, hmsg)
    comp["liquidity"] = _liquidity(daily, (entry, stop) if h_ok else None, sizing, frs)
    return _finish(symbol, checks, comp, details, entry, stop, target, rr, key, vu)


def _liquidity(daily: list[Candle], plan: tuple[float, float] | None, sizing: dict | None, frs: dict) -> dict:
    recent = daily[-20:]
    turnover = sum(c.close * c.volume for c in recent) / max(1, len(recent))
    cr = turnover / 1e7
    pts = 5 if cr >= 50 else 3 if cr >= 10 else 0
    feasible = None
    if plan and sizing:
        entry, stop = plan
        q = min(int(sizing["allocation"] // entry), int(sizing["risk_budget"] // (entry - stop)))
        feasible = q >= 1
        pts += 3 if feasible else 0
    elif plan:
        pts += 3
    fresh = all(f["status"] == "FRESH" for f in frs.values())
    pts += 2 if fresh else 0
    return {"points": pts, "max": 10, "detail": f"20-day avg turnover Rs {cr:.1f} cr; sizing feasible={feasible}; data fresh={fresh}"}


def _finish(symbol, checks, comp, details, entry, stop, target, rr, key, vu) -> MechResult:
    score = float(sum(c["points"] for c in comp.values()))
    grade = grade_for(score)
    fails = [c for c in checks if c.mandatory and not c.passed]
    reasons = [f"Rule {c.rule} ({c.name}): {c.detail}" for c in fails]
    if not fails and score < 75:
        reasons.append(f"Score {score:.0f} below 75 (grade {grade}) — not a qualified recommendation")
    status = "QUALIFIED" if not fails and score >= 75 else "REJECTED"
    return MechResult(symbol, status, score, grade, checks, comp, details, entry, stop, target, rr, key, vu, reasons)
