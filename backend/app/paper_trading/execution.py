"""Deterministic fill simulation on COMPLETED OHLC candles. Pure functions, no I/O.

Entry triggers (BUY):
  CANDLE_CLOSE_ABOVE (Dashboard 1 default): a completed 5m candle closes at/above the
      entry level after the previous candle closed below it. Reference fill = that close
      (the decision is only known at candle close).
  CROSS_ABOVE (buy-stop; Dashboard 2 entry): previous close below the level and the candle
      high reaches it. Reference fill = max(level, candle open) — a gap up fills at the open.
  TOUCH_BELOW (buy-limit): candle low trades STRICTLY below the level (a mere touch is not
      assumed to fill). Reference fill = min(level, candle open) — a gap down fills at the open.

Exits (long):
  Open <= stop -> STOP_LOSS_GAP at the open; open >= target -> TAKE_PROFIT_GAP at the open.
  If both stop and target lie inside the same candle's range, the intrabar sequence is
  unknown and the CONSERVATIVE assumption (stop first) is applied — no sequence is invented.
Slippage (basis points) is always applied against the trader, except a limit buy never fills
above its limit.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.market_data.candles import Candle

TRIGGERS = {
    "CANDLE_CLOSE_ABOVE": "A completed 5-minute candle closes at/above the entry after the prior candle closed below it",
    "CROSS_ABOVE": "Price crosses up through the entry (buy-stop); gap-ups fill at the open",
    "TOUCH_BELOW": "Price trades strictly below the entry (buy-limit); gap-downs fill at the open",
}
DEFAULT_D1_TRIGGER = "CANDLE_CLOSE_ABOVE"
D2_TRIGGER = "CROSS_ABOVE"


@dataclass
class Fill:
    reference_price: float
    price: float
    reason: str
    candle_ts: float
    note: str = ""


def _slip_buy(ref: float, bps: float) -> float:
    return round(ref * (1 + bps / 10_000), 2)


def _slip_sell(ref: float, bps: float) -> float:
    return round(ref * (1 - bps / 10_000), 2)


def entry_fill(trigger: str, level: float, candle: Candle, prev: Candle | None, slippage_bps: float) -> Fill | None:
    prev_close = prev.close if prev is not None else candle.open
    if trigger == "CANDLE_CLOSE_ABOVE":
        if prev_close < level <= candle.close:
            return Fill(candle.close, _slip_buy(candle.close, slippage_bps), "ENTRY", candle.ts, "Filled at trigger-candle close + slippage")
        return None
    if trigger == "CROSS_ABOVE":
        if prev_close < level <= candle.high:
            ref = max(level, candle.open)
            note = "Gap above entry: filled at candle open" if candle.open > level else "Buy-stop triggered"
            return Fill(ref, _slip_buy(ref, slippage_bps), "ENTRY", candle.ts, note)
        return None
    if trigger == "TOUCH_BELOW":
        if candle.low < level:
            ref = min(level, candle.open)
            note = "Gap below entry: filled at candle open" if candle.open < level else "Limit traded through"
            return Fill(ref, min(level, _slip_buy(ref, slippage_bps)), "ENTRY", candle.ts, note)
        return None
    raise ValueError(f"Unknown entry trigger {trigger}")


def exit_fill(stop: float, target: float, candle: Candle, slippage_bps: float) -> Fill | None:
    if candle.open <= stop:
        return Fill(candle.open, _slip_sell(candle.open, slippage_bps), "STOP_LOSS_GAP", candle.ts, "Gapped through stop: filled at open")
    if candle.open >= target:
        return Fill(candle.open, _slip_sell(candle.open, slippage_bps), "TAKE_PROFIT_GAP", candle.ts, "Gapped above target: filled at open")
    hit_stop = candle.low <= stop
    hit_target = candle.high >= target
    if hit_stop and hit_target:
        return Fill(stop, _slip_sell(stop, slippage_bps), "STOP_LOSS", candle.ts,
                    "Stop and target both inside one candle; sequence unknown -> conservative stop-first assumption")
    if hit_stop:
        return Fill(stop, _slip_sell(stop, slippage_bps), "STOP_LOSS", candle.ts)
    if hit_target:
        return Fill(target, _slip_sell(target, slippage_bps), "TAKE_PROFIT", candle.ts)
    return None
