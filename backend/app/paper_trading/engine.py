"""Paper-trading ledger: accounts, trade lifecycle, simulated fills and P&L.

PAPER TRADING ONLY. Nothing in this module talks to a broker. Every trade and execution
row is flagged ``simulated=True``. Cash/position updates happen inside one DB transaction
under ``ENGINE_LOCK``; ``UniqueConstraint(trade_id, side)`` on executions and
``UniqueConstraint(account_id, idempotency_key)`` on trades make duplicate fills impossible.

Cash model per account:
  cash      = cash not invested in open positions (includes reserved money)
  reserved  = allocations earmarked for PENDING_ENTRY trades
  available = cash - reserved   (what a new trade may allocate)
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import PAPER_TRADING_ONLY
from app.database.models import Execution, Instrument, PaperAccount, PaperTrade, TradeEvent, utcnow
from app.market_data.candles import Candle, candle_end
from app.paper_trading.charges import estimate_charges
from app.paper_trading.execution import Fill, entry_fill, exit_fill
from app.paper_trading.risk_manager import AccountLimits, PlanInput, PlanResult, validate_plan

assert PAPER_TRADING_ONLY, "This engine only supports paper trading"

ENGINE_LOCK = threading.RLock()

ACTIVE_STATES = ("CONFIGURED", "PENDING_ENTRY", "OPEN")
ALL_STATES = ("CONFIGURED", "PENDING_ENTRY", "OPEN", "CLOSED", "CANCELLED", "REJECTED", "EXPIRED")

ACCOUNT_DEFS = {
    "D1_MTF": {"name": "Dashboard 1 — MTF", "strategy": "DASHBOARD1_MTF", "min_reward_risk": 2.0},
    "D2_MECH": {"name": "Dashboard 2 — Mechanical Swing", "strategy": "DASHBOARD2_MECHANICAL", "min_reward_risk": 3.0},
}


class TradeRejected(Exception):
    def __init__(self, errors: list[str], trade: PaperTrade | None = None, plan: PlanResult | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.trade = trade
        self.plan = plan


def _r(x: float) -> float:
    return round(float(x), 2)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def add_event(db: Session, trade: PaperTrade, event: str, message: str, data: dict | None = None) -> None:
    db.add(TradeEvent(trade_id=trade.id, event=event, message=message, data=data or {}))


# --------------------------------------------------------------------------- accounts
def ensure_accounts(db: Session, initial_capital: float = 100_000.0) -> None:
    for code, d in ACCOUNT_DEFS.items():
        if db.scalar(select(PaperAccount).where(PaperAccount.code == code)) is None:
            db.add(PaperAccount(code=code, name=d["name"], strategy=d["strategy"], initial_capital=initial_capital,
                                cash=initial_capital, reserved=0.0, min_reward_risk=d["min_reward_risk"]))
    db.flush()


def active_trades(db: Session, account_id: int | None = None) -> list[PaperTrade]:
    q = select(PaperTrade).where(PaperTrade.status.in_(ACTIVE_STATES))
    if account_id is not None:
        q = q.where(PaperTrade.account_id == account_id)
    return list(db.scalars(q))


def open_risk(t: PaperTrade) -> float:
    if t.status == "OPEN" and t.entry_price is not None:
        return max(0.0, (t.entry_price - t.stop_loss) * t.filled_qty)
    if t.status == "PENDING_ENTRY":
        return t.planned_risk
    return 0.0


def limits_for(db: Session, acc: PaperAccount) -> AccountLimits:
    trades = [t for t in active_trades(db, acc.id) if t.status in ("PENDING_ENTRY", "OPEN")]
    return AccountLimits(
        available_cash=_r(acc.cash - acc.reserved),
        initial_capital=acc.initial_capital,
        risk_pct_per_trade=acc.risk_pct_per_trade,
        max_risk_per_trade=acc.max_risk_per_trade,
        max_allocation_per_trade=acc.max_allocation_per_trade,
        max_open_positions=acc.max_open_positions,
        max_aggregate_risk_pct=acc.max_aggregate_risk_pct,
        min_reward_risk=acc.min_reward_risk,
        open_or_pending_count=len(trades),
        aggregate_open_risk=sum(open_risk(t) for t in trades),
    )


def account_summary(db: Session, acc: PaperAccount) -> dict:
    trades = list(db.scalars(select(PaperTrade).where(PaperTrade.account_id == acc.id)))
    open_t = [t for t in trades if t.status == "OPEN"]
    closed = [t for t in trades if t.status == "CLOSED"]
    deployed = sum((t.entry_price or 0) * t.filled_qty for t in open_t)
    open_value = sum((t.last_price or t.entry_price or 0) * t.filled_qty for t in open_t)
    unrealized = sum(((t.last_price or t.entry_price or 0) - (t.entry_price or 0)) * t.filled_qty for t in open_t)
    net_realized = sum(t.net_pnl or 0 for t in closed)
    wins = sum(1 for t in closed if (t.net_pnl or 0) > 0)
    losses = sum(1 for t in closed if (t.net_pnl or 0) <= 0)
    return {
        "code": acc.code,
        "name": acc.name,
        "strategy": acc.strategy,
        "simulated": True,
        "initial_capital": _r(acc.initial_capital),
        "cash": _r(acc.cash),
        "reserved": _r(acc.reserved),
        "available_cash": _r(acc.cash - acc.reserved),
        "capital_deployed": _r(deployed),
        "open_position_value": _r(open_value),
        "unrealized_pnl": _r(unrealized),
        "realized_gross_pnl": _r(acc.realized_gross),
        "estimated_charges": _r(acc.total_charges),
        "estimated_slippage": _r(acc.total_slippage),
        "net_realized_pnl": _r(net_realized),
        "equity": _r(acc.cash + open_value),
        "open_positions": len(open_t),
        "pending_entries": sum(1 for t in trades if t.status == "PENDING_ENTRY"),
        "paused": sum(1 for t in trades if t.status == "CONFIGURED"),
        "trade_count": len(closed),
        "winning_trades": wins,
        "losing_trades": losses,
        "limits": {
            "risk_pct_per_trade": acc.risk_pct_per_trade,
            "max_risk_per_trade": acc.max_risk_per_trade,
            "max_allocation_per_trade": acc.max_allocation_per_trade,
            "max_open_positions": acc.max_open_positions,
            "max_aggregate_risk_pct": acc.max_aggregate_risk_pct,
            "min_reward_risk": acc.min_reward_risk,
            "slippage_bps": acc.slippage_bps,
            "max_entry_deviation_pct": acc.max_entry_deviation_pct,
        },
        "reset_at": acc.reset_at.isoformat() if acc.reset_at else None,
        "label": "SIMULATED PAPER-TRADING PERFORMANCE",
    }


def reset_account(db: Session, acc: PaperAccount, initial_capital: float | None = None) -> None:
    with ENGINE_LOCK:
        if any(t.status == "OPEN" for t in active_trades(db, acc.id)):
            raise TradeRejected(["Close all open paper positions in this account before resetting it"])
        for t in active_trades(db, acc.id):
            t.status = "CANCELLED"
            t.reserved_amount = 0
            add_event(db, t, "CANCELLED", "Cancelled by paper-account reset")
        cap = initial_capital if initial_capital and initial_capital > 0 else acc.initial_capital
        acc.initial_capital = cap
        acc.cash = cap
        acc.reserved = 0
        acc.realized_gross = 0
        acc.total_charges = 0
        acc.total_slippage = 0
        acc.reset_at = utcnow()
        db.flush()


# --------------------------------------------------------------------------- lifecycle
def preview(db: Session, acc: PaperAccount, inp: PlanInput) -> PlanResult:
    return validate_plan(inp, limits_for(db, acc))


def create_trade(
    db: Session,
    acc: PaperAccount,
    instrument: Instrument,
    inp: PlanInput,
    *,
    trigger: str,
    idempotency_key: str,
    snapshot: dict | None = None,
    signal_id: int | None = None,
    signal_key: str | None = None,
    valid_until: datetime | None = None,
    is_overridden: bool = False,
    original_values: dict | None = None,
) -> PaperTrade:
    """Validate, reserve cash and arm a PENDING_ENTRY paper trade. Never opens a position."""
    with ENGINE_LOCK:
        existing = db.scalar(select(PaperTrade).where(PaperTrade.account_id == acc.id, PaperTrade.idempotency_key == idempotency_key))
        if existing is not None:
            return existing
        errors: list[str] = []
        dup = db.scalar(
            select(PaperTrade).where(
                PaperTrade.account_id == acc.id, PaperTrade.instrument_id == instrument.id, PaperTrade.status.in_(ACTIVE_STATES)
            )
        )
        if dup is not None:
            errors.append(f"{instrument.symbol} already has an active paper trade #{dup.id} ({dup.status}) in this account")
        if signal_key:
            used = db.scalar(select(PaperTrade).where(PaperTrade.account_id == acc.id, PaperTrade.signal_key == signal_key,
                                                      PaperTrade.status.notin_(("REJECTED", "CANCELLED"))))
            if used is not None:
                errors.append(f"Signal already used by paper trade #{used.id}; duplicate entries for one signal are not allowed")
        plan = validate_plan(inp, limits_for(db, acc))
        errors += plan.errors
        trade = PaperTrade(
            account_id=acc.id,
            strategy=acc.strategy,
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            signal_id=signal_id,
            signal_key=signal_key,
            idempotency_key=idempotency_key,
            status="REJECTED" if errors else "PENDING_ENTRY",
            entry_trigger=trigger,
            planned_entry=_r(inp.entry),
            stop_loss=_r(inp.stop),
            target=_r(inp.target),
            allocation=_r(inp.allocation),
            max_risk_amount=inp.max_risk_amount,
            planned_qty=plan.quantity,
            planned_risk=_r(plan.planned_risk),
            planned_reward=_r(plan.potential_reward),
            reward_risk=plan.reward_risk,
            reserved_amount=0 if errors else _r(inp.allocation),
            auto_entry_enabled=not errors,
            is_overridden=is_overridden,
            original_values=original_values,
            valid_until=_naive_utc(valid_until) if valid_until else None,
            rejection_reason="; ".join(errors) or None,
            snapshot=snapshot or {},
            simulated=True,
        )
        db.add(trade)
        db.flush()
        if errors:
            add_event(db, trade, "REJECTED", "Paper trade rejected at configuration", {"errors": errors})
            db.flush()
            raise TradeRejected(errors, trade, plan)
        acc.reserved = _r(acc.reserved + trade.reserved_amount)
        add_event(db, trade, "CONFIGURED", "Paper auto-trade configured (simulated)", {"plan": plan.to_dict(), "trigger": trigger})
        add_event(db, trade, "PENDING_ENTRY", f"Reserved Rs {trade.reserved_amount:,.2f} of paper cash; waiting for entry trigger")
        db.flush()
        return trade


def _release(db: Session, trade: PaperTrade) -> None:
    if trade.reserved_amount:
        acc = trade.account
        acc.reserved = _r(max(0.0, acc.reserved - trade.reserved_amount))
        trade.reserved_amount = 0


def cancel_trade(db: Session, trade: PaperTrade, reason: str = "Cancelled by user") -> PaperTrade:
    with ENGINE_LOCK:
        if trade.status not in ("CONFIGURED", "PENDING_ENTRY"):
            raise TradeRejected([f"Only pending/paused trades can be cancelled (status {trade.status}); use Manual Paper Exit for open positions"])
        _release(db, trade)
        trade.status = "CANCELLED"
        trade.auto_entry_enabled = False
        add_event(db, trade, "CANCELLED", reason)
        db.flush()
        return trade


def disable_auto_entry(db: Session, trade: PaperTrade) -> PaperTrade:
    """Stop future auto entries. A pending trade is paused (CONFIGURED, cash released);
    an OPEN position is untouched and keeps being monitored for stop/target."""
    with ENGINE_LOCK:
        if trade.status == "PENDING_ENTRY":
            _release(db, trade)
            trade.status = "CONFIGURED"
            trade.auto_entry_enabled = False
            add_event(db, trade, "PAUSED", "Auto entry disabled; reserved cash released. Configuration kept.")
        elif trade.status == "OPEN":
            trade.auto_entry_enabled = False
            add_event(db, trade, "AUTO_ENTRY_DISABLED", "Future auto entries disabled; open position continues to be monitored")
        else:
            raise TradeRejected([f"Trade is {trade.status}; nothing to disable"])
        db.flush()
        return trade


def enable_auto_entry(db: Session, trade: PaperTrade) -> PaperTrade:
    with ENGINE_LOCK:
        if trade.status != "CONFIGURED":
            raise TradeRejected([f"Only paused (CONFIGURED) trades can be resumed; status is {trade.status}"])
        acc = trade.account
        plan = validate_plan(
            PlanInput(trade.planned_entry, trade.stop_loss, trade.target, trade.allocation, trade.max_risk_amount),
            limits_for(db, acc),
        )
        if not plan.ok:
            raise TradeRejected(plan.errors, trade, plan)
        trade.planned_qty = plan.quantity
        trade.planned_risk = _r(plan.planned_risk)
        trade.planned_reward = _r(plan.potential_reward)
        trade.reserved_amount = trade.allocation
        acc.reserved = _r(acc.reserved + trade.allocation)
        trade.status = "PENDING_ENTRY"
        trade.auto_entry_enabled = True
        add_event(db, trade, "RESUMED", "Auto entry re-enabled; cash re-reserved", {"plan": plan.to_dict()})
        db.flush()
        return trade


def expire_trade(db: Session, trade: PaperTrade, reason: str) -> None:
    with ENGINE_LOCK:
        if trade.status not in ("CONFIGURED", "PENDING_ENTRY"):
            return
        _release(db, trade)
        trade.status = "EXPIRED"
        trade.auto_entry_enabled = False
        trade.rejection_reason = reason
        add_event(db, trade, "EXPIRED", reason)
        db.flush()


def reject_pending(db: Session, trade: PaperTrade, reason: str) -> None:
    with ENGINE_LOCK:
        if trade.status not in ("CONFIGURED", "PENDING_ENTRY"):
            return
        _release(db, trade)
        trade.status = "REJECTED"
        trade.auto_entry_enabled = False
        trade.rejection_reason = reason
        add_event(db, trade, "REJECTED", reason)
        db.flush()


def fill_entry(db: Session, trade: PaperTrade, fill: Fill, data_source: str, executed_at: datetime | None = None) -> bool:
    """Simulate the BUY fill. Returns False (and logs) if the fill is not allowed."""
    with ENGINE_LOCK:
        if trade.status != "PENDING_ENTRY":
            return False
        if db.scalar(select(func.count()).select_from(Execution).where(Execution.trade_id == trade.id, Execution.side == "BUY")):
            return False
        acc = trade.account
        price = fill.price
        if not (trade.stop_loss < price < trade.target):
            add_event(db, trade, "FILL_SKIPPED", f"Simulated fill {price:.2f} is outside stop {trade.stop_loss:.2f} / target {trade.target:.2f}")
            return False
        qty = trade.planned_qty
        while qty > 0 and qty * price + estimate_charges("BUY", qty * price) > trade.allocation + 1e-9:
            qty -= 1
        if qty < 1:
            reject_pending(db, trade, f"Allocation insufficient for 1 share at simulated fill {price:.2f}")
            return False
        cost = _r(qty * price)
        charges = estimate_charges("BUY", cost)
        slip = _r(qty * (price - fill.reference_price))
        db.add(Execution(trade_id=trade.id, side="BUY", qty=qty, price=price, reference_price=fill.reference_price, slippage=slip,
                         charges=charges, reason="ENTRY", candle_ts=fill.candle_ts, data_source=data_source, note=fill.note,
                         simulated=True, executed_at=_naive_utc(executed_at) if executed_at else utcnow()))
        _release(db, trade)
        acc.cash = _r(acc.cash - cost - charges)
        acc.total_charges = _r(acc.total_charges + charges)
        acc.total_slippage = _r(acc.total_slippage + max(0.0, slip))
        trade.status = "OPEN"
        trade.filled_qty = qty
        trade.entry_price = price
        trade.entry_reference_price = fill.reference_price
        trade.entry_at = _naive_utc(executed_at) if executed_at else utcnow()
        trade.charges = charges
        trade.slippage_cost = max(0.0, slip)
        trade.last_price = price
        trade.last_price_at = trade.entry_at
        add_event(db, trade, "ENTRY_FILLED", f"SIMULATED paper BUY {qty} @ {price:.2f} (ref {fill.reference_price:.2f}). {fill.note}".strip(),
                  {"qty": qty, "price": price, "reference_price": fill.reference_price, "charges": charges, "candle_ts": fill.candle_ts, "source": data_source})
        db.flush()
        return True


def close_position(db: Session, trade: PaperTrade, fill: Fill, data_source: str, executed_at: datetime | None = None) -> bool:
    with ENGINE_LOCK:
        if trade.status != "OPEN":
            return False
        if db.scalar(select(func.count()).select_from(Execution).where(Execution.trade_id == trade.id, Execution.side == "SELL")):
            return False
        acc = trade.account
        qty = trade.filled_qty
        proceeds = _r(qty * fill.price)
        charges = estimate_charges("SELL", proceeds)
        slip = _r(qty * (fill.reference_price - fill.price))
        db.add(Execution(trade_id=trade.id, side="SELL", qty=qty, price=fill.price, reference_price=fill.reference_price, slippage=slip,
                         charges=charges, reason=fill.reason, candle_ts=fill.candle_ts, data_source=data_source, note=fill.note,
                         simulated=True, executed_at=_naive_utc(executed_at) if executed_at else utcnow()))
        gross = _r((fill.price - trade.entry_price) * qty)
        acc.cash = _r(acc.cash + proceeds - charges)
        acc.realized_gross = _r(acc.realized_gross + gross)
        acc.total_charges = _r(acc.total_charges + charges)
        acc.total_slippage = _r(acc.total_slippage + max(0.0, slip))
        trade.status = "CLOSED"
        trade.exit_price = fill.price
        trade.exit_reference_price = fill.reference_price
        trade.exit_at = _naive_utc(executed_at) if executed_at else utcnow()
        trade.exit_reason = fill.reason
        trade.gross_pnl = gross
        trade.charges = _r(trade.charges + charges)
        trade.slippage_cost = _r(trade.slippage_cost + max(0.0, slip))
        trade.net_pnl = _r(gross - trade.charges)
        trade.last_price = fill.price
        trade.auto_entry_enabled = False
        add_event(db, trade, fill.reason, f"SIMULATED paper SELL {qty} @ {fill.price:.2f} ({fill.reason}). {fill.note}".strip(),
                  {"price": fill.price, "reference_price": fill.reference_price, "gross_pnl": gross, "net_pnl": trade.net_pnl, "source": data_source})
        db.flush()
        return True


def manual_exit(db: Session, trade: PaperTrade, price: float, price_source: str, slippage_bps: float | None = None) -> bool:
    """Close a paper position at the latest verified price. Affects ONLY the paper ledger."""
    if price is None or price <= 0:
        raise TradeRejected(["No verified market price available for a manual paper exit"])
    bps = trade.account.slippage_bps if slippage_bps is None else slippage_bps
    fill = Fill(price, round(price * (1 - bps / 10_000), 2), "MANUAL_EXIT", 0, f"Manual paper exit at latest verified price ({price_source})")
    return close_position(db, trade, fill, price_source)


def mark_to_market(trade: PaperTrade, price: float, at: datetime) -> None:
    trade.last_price = price
    trade.last_price_at = _naive_utc(at)


# --------------------------------------------------------------------------- candle processing
EntryGate = Callable[[PaperTrade, Candle], tuple[bool, str]]


def process_candles(
    db: Session,
    trade: PaperTrade,
    candles: list[Candle],
    gate: EntryGate,
    data_source: str,
    *,
    gap_policy: str = "SKIP",  # SKIP: stay pending (Dashboard 1) | REJECT: drop the signal (Dashboard 2)
    invalidate_below_stop: bool = False,
) -> list[str]:
    """Advance one trade through newly COMPLETED 5-minute candles (oldest first).

    Only candles that START after the trade was armed are considered, and each candle is
    processed at most once (``last_candle_ts``), so restarts never double-fill.
    """
    actions: list[str] = []
    armed_epoch = trade.created_at.replace(tzinfo=timezone.utc).timestamp()
    for i, c in enumerate(candles):
        if c.ts < armed_epoch or (trade.last_candle_ts is not None and c.ts <= trade.last_candle_ts):
            continue
        prev = candles[i - 1] if i > 0 else None
        end = candle_end(c, "5m")
        if trade.status == "PENDING_ENTRY":
            if trade.valid_until and end.astimezone(timezone.utc).replace(tzinfo=None) > trade.valid_until:
                expire_trade(db, trade, "Signal validity window ended before the entry triggered")
                actions.append("EXPIRED")
                break
            if invalidate_below_stop and c.low <= trade.stop_loss:
                expire_trade(db, trade, f"Price traded at/below the stop {trade.stop_loss:.2f} before entry (setup invalidated)")
                actions.append("INVALIDATED")
                break
            f = entry_fill(trade.entry_trigger, trade.planned_entry, c, prev, trade.account.slippage_bps)
            if f is not None:
                ok, why = gate(trade, c)
                if not ok:
                    add_event(db, trade, "TRIGGER_BLOCKED", f"Entry level reached on candle {c.dt.isoformat()} but strategy conditions failed: {why}")
                    actions.append("BLOCKED")
                else:
                    dev = (f.price - trade.planned_entry) / trade.planned_entry * 100
                    if dev > trade.account.max_entry_deviation_pct:
                        msg = f"Simulated fill {f.price:.2f} is {dev:.2f}% above entry {trade.planned_entry:.2f} (limit {trade.account.max_entry_deviation_pct}%); not chased"
                        if gap_policy == "REJECT":
                            reject_pending(db, trade, msg)
                            actions.append("REJECTED_GAP")
                            break
                        add_event(db, trade, "FILL_SKIPPED", msg)
                        actions.append("SKIPPED_GAP")
                    elif fill_entry(db, trade, f, data_source, executed_at=end):
                        actions.append("FILLED")
                        # Intrabar fills (stop/limit) cannot rule out the stop also trading in the same candle.
                        if trade.entry_trigger != "CANDLE_CLOSE_ABOVE" and c.low <= trade.stop_loss:
                            close_position(db, trade, Fill(trade.stop_loss, round(trade.stop_loss * (1 - trade.account.slippage_bps / 10_000), 2),
                                                           "STOP_LOSS", c.ts, "Entry and stop inside the same candle; conservative stop-first assumption"),
                                           data_source, executed_at=end)
                            actions.append("STOP_LOSS")
        elif trade.status == "OPEN":
            x = exit_fill(trade.stop_loss, trade.target, c, trade.account.slippage_bps)
            if x is not None:
                close_position(db, trade, x, data_source, executed_at=end)
                actions.append(x.reason)
        trade.last_candle_ts = c.ts
        if trade.status == "OPEN":
            mark_to_market(trade, c.close, end)
        if trade.status not in ("PENDING_ENTRY", "OPEN"):
            break
    db.flush()
    return actions
