"""Dashboard 1 — Multi-Timeframe (MTF) BUY strategy (baseline, independent of Dashboard 2).

All decisions use COMPLETED candles only. Definitions (see README §Dashboard 1 strategy):

Daily (primary trend)
  D1: close[-1] > EMA50[-1]
  D2: EMA50 rising: EMA50[-1] > EMA50[-1 - DAILY_SLOPE_LOOKBACK]
  daily_trend = BULLISH if D1 and D2; BEARISH if close < EMA50 and EMA50 falling; else NEUTRAL
4-hour (intermediate trend & structure; 4H is aggregated from Dhan 60m candles)
  H1: close[-1] > EMA20[-1] > EMA50[-1]                     -> trend BULLISH
  H2: no confirmed bearish reversal: close[-1] >= low of the most recent confirmed
      pivot low (pivot = 2 bars left / 2 bars right)
  h4 BEARISH if close < EMA20 < EMA50
15-minute (setup confirmation)
  M1: close[-1] > EMA20[-1]  and  EMA20[-1] > EMA20[-1 - M15_SLOPE_LOOKBACK]
5-minute (entry monitoring)
  Table status: close[-1] > EMA20[-1] -> MOMENTUM_UP, else WAITING.
  For an armed trade the 5m candle must additionally satisfy the configured entry trigger
  (see app.paper_trading.execution).

Entry allowed only when D1, D2, H1, H2, M1 pass, every timeframe is FRESH, and the user's
plan passes risk validation. Dashboard 1 does NOT use Fibonacci, 3-red-candle, demand-zone
or 1:3 rules (those belong to Dashboard 2). Minimum reward:risk for Dashboard 1 is 1:2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.market_calendar import MarketCalendar
from app.market_data.candles import Candle
from app.market_data.validation import freshness
from app.strategies.indicators import ema, pivot_lows

DAILY_EMA = 50
DAILY_SLOPE_LOOKBACK = 5
H4_FAST, H4_SLOW = 20, 50
M15_EMA, M15_SLOPE_LOOKBACK = 20, 3
M5_EMA = 20
MIN_BARS = {"1D": DAILY_EMA + DAILY_SLOPE_LOOKBACK + 5, "4H": H4_SLOW + 5, "15m": M15_EMA + M15_SLOPE_LOOKBACK + 2, "5m": M5_EMA + 2}
DEFAULT_MIN_RR = 2.0
STRATEGY_ID = "DASHBOARD1_MTF"


@dataclass
class TFStatus:
    timeframe: str
    status: str  # BULLISH | BEARISH | NEUTRAL | CONFIRMED | NOT_CONFIRMED | MOMENTUM_UP | WAITING | UNAVAILABLE
    passed: bool
    checks: dict = field(default_factory=dict)
    last_candle: str | None = None
    freshness: str = "MISSING"
    note: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class MTFResult:
    daily: TFStatus
    h4: TFStatus
    m15: TFStatus
    m5: TFStatus
    bias: str
    confirmation: str  # CONFIRMED | PARTIAL | NOT_CONFIRMED | UNAVAILABLE
    quality: int  # 0..4 timeframes passing
    entry_conditions_ok: bool  # daily+4h+15m pass and fresh (5m trigger evaluated per trade)
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "daily": self.daily.to_dict(),
            "h4": self.h4.to_dict(),
            "m15": self.m15.to_dict(),
            "m5": self.m5.to_dict(),
            "bias": self.bias,
            "confirmation": self.confirmation,
            "quality": self.quality,
            "entry_conditions_ok": self.entry_conditions_ok,
            "reasons": self.reasons,
        }


def _unavailable(tf: str, note: str, fr: dict | None = None) -> TFStatus:
    return TFStatus(tf, "UNAVAILABLE", False, {}, (fr or {}).get("last_candle"), (fr or {}).get("status", "MISSING"), note)


def evaluate_daily(c: list[Candle], fr: dict) -> TFStatus:
    if len(c) < MIN_BARS["1D"]:
        return _unavailable("1D", f"Need {MIN_BARS['1D']} completed daily candles, have {len(c)}", fr)
    e = ema([x.close for x in c], DAILY_EMA)
    close, e_now, e_prev = c[-1].close, e[-1], e[-1 - DAILY_SLOPE_LOOKBACK]
    above = close > e_now
    rising = e_now > e_prev
    status = "BULLISH" if above and rising else ("BEARISH" if (close < e_now and e_now < e_prev) else "NEUTRAL")
    return TFStatus(
        "1D", status, above and rising,
        {"close": round(close, 2), "ema50": round(e_now, 2), "ema50_prev": round(e_prev, 2), "close_above_ema50": above, "ema50_rising": rising},
        fr.get("last_candle"), fr.get("status"),
    )


def evaluate_h4(c: list[Candle], fr: dict) -> TFStatus:
    if len(c) < MIN_BARS["4H"]:
        return _unavailable("4H", f"Need {MIN_BARS['4H']} completed 4H candles, have {len(c)}", fr)
    closes = [x.close for x in c]
    fast, slow = ema(closes, H4_FAST)[-1], ema(closes, H4_SLOW)[-1]
    close = closes[-1]
    bullish = close > fast > slow
    bearish = close < fast < slow
    lows = pivot_lows(c, 2, 2)
    last_pl = c[lows[-1]].low if lows else None
    reversal = last_pl is not None and close < last_pl
    status = "BULLISH" if bullish and not reversal else ("BEARISH" if bearish or reversal else "NEUTRAL")
    return TFStatus(
        "4H", status, bullish and not reversal,
        {"close": round(close, 2), "ema20": round(fast, 2), "ema50": round(slow, 2), "trend_bullish": bullish,
         "last_confirmed_swing_low": round(last_pl, 2) if last_pl else None, "bearish_reversal": reversal},
        fr.get("last_candle"), fr.get("status"),
    )


def evaluate_m15(c: list[Candle], fr: dict) -> TFStatus:
    if len(c) < MIN_BARS["15m"]:
        return _unavailable("15m", f"Need {MIN_BARS['15m']} completed 15m candles, have {len(c)}", fr)
    e = ema([x.close for x in c], M15_EMA)
    close = c[-1].close
    above = close > e[-1]
    rising = e[-1] > e[-1 - M15_SLOPE_LOOKBACK]
    ok = above and rising
    return TFStatus(
        "15m", "CONFIRMED" if ok else "NOT_CONFIRMED", ok,
        {"close": round(close, 2), "ema20": round(e[-1], 2), "close_above_ema20": above, "ema20_rising": rising},
        fr.get("last_candle"), fr.get("status"),
    )


def evaluate_m5(c: list[Candle], fr: dict) -> TFStatus:
    if len(c) < MIN_BARS["5m"]:
        return _unavailable("5m", f"Need {MIN_BARS['5m']} completed 5m candles, have {len(c)}", fr)
    e = ema([x.close for x in c], M5_EMA)
    up = c[-1].close > e[-1]
    return TFStatus(
        "5m", "MOMENTUM_UP" if up else "WAITING", up,
        {"close": round(c[-1].close, 2), "ema20": round(e[-1], 2), "close_above_ema20": up},
        fr.get("last_candle"), fr.get("status"),
    )


def evaluate(daily: list[Candle], h4: list[Candle], m15: list[Candle], m5: list[Candle], now: datetime, cal: MarketCalendar) -> MTFResult:
    """Evaluate the MTF state. All inputs must already be COMPLETED candles."""
    frs = {tf: freshness(cs, tf, now, cal) for tf, cs in (("1D", daily), ("4H", h4), ("15m", m15), ("5m", m5))}
    d, h, m, f = evaluate_daily(daily, frs["1D"]), evaluate_h4(h4, frs["4H"]), evaluate_m15(m15, frs["15m"]), evaluate_m5(m5, frs["5m"])
    tfs = [d, h, m, f]
    reasons = []
    for t in tfs:
        if t.status == "UNAVAILABLE":
            reasons.append(f"{t.timeframe}: data unavailable ({t.note})")
        elif t.freshness != "FRESH":
            reasons.append(f"{t.timeframe}: data is {t.freshness} (last completed candle {t.last_candle})")
        elif not t.passed:
            reasons.append(f"{t.timeframe}: condition not met ({t.status})")
    if d.status == "BULLISH" and h.status == "BULLISH":
        bias = "BULLISH"
    elif d.status == "BEARISH" and h.status == "BEARISH":
        bias = "BEARISH"
    elif d.status == "UNAVAILABLE" or h.status == "UNAVAILABLE":
        bias = "UNAVAILABLE"
    else:
        bias = "NEUTRAL"
    quality = sum(1 for t in tfs if t.passed and t.freshness == "FRESH")
    if any(t.status == "UNAVAILABLE" for t in tfs):
        conf = "UNAVAILABLE"
    elif quality == 4:
        conf = "CONFIRMED"
    elif quality >= 2:
        conf = "PARTIAL"
    else:
        conf = "NOT_CONFIRMED"
    entry_ok = all(t.passed and t.freshness == "FRESH" for t in (d, h, m))
    return MTFResult(d, h, m, f, bias, conf, quality, entry_ok, reasons)
