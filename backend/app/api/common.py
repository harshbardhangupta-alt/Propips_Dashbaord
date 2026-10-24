from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import iso
from app.database.models import Instrument, PaperTrade

SYMBOL_RE = re.compile(r"^[A-Z0-9&\-_.]{1,32}$")


def get_instrument(db: Session, symbol: str) -> Instrument:
    symbol = symbol.upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Invalid symbol")
    inst = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if inst is None:
        raise HTTPException(404, f"Unknown symbol {symbol}")
    return inst


def trade_view(t: PaperTrade, detail: bool = False) -> dict:
    unreal = None
    if t.status == "OPEN" and t.entry_price is not None and t.last_price is not None:
        unreal = round((t.last_price - t.entry_price) * t.filled_qty, 2)
    d = {
        "id": t.id, "account": t.account.code if t.account else None, "strategy": t.strategy, "symbol": t.symbol, "status": t.status,
        "side": t.side, "simulated": True, "entry_trigger": t.entry_trigger, "planned_entry": t.planned_entry, "stop_loss": t.stop_loss,
        "target": t.target, "allocation": t.allocation, "planned_qty": t.planned_qty, "filled_qty": t.filled_qty,
        "planned_risk": t.planned_risk, "planned_reward": t.planned_reward, "reward_risk": t.reward_risk, "reserved_amount": t.reserved_amount,
        "auto_entry_enabled": t.auto_entry_enabled, "is_overridden": t.is_overridden, "original_values": t.original_values,
        "entry_price": t.entry_price, "entry_at": iso(t.entry_at), "exit_price": t.exit_price, "exit_at": iso(t.exit_at),
        "exit_reason": t.exit_reason, "gross_pnl": t.gross_pnl, "charges": t.charges, "slippage_cost": t.slippage_cost,
        "net_pnl": t.net_pnl, "unrealized_pnl": unreal, "last_price": t.last_price, "last_price_at": iso(t.last_price_at),
        "valid_until": iso(t.valid_until), "rejection_reason": t.rejection_reason, "signal_id": t.signal_id,
        "created_at": iso(t.created_at), "updated_at": iso(t.updated_at),
    }
    if detail:
        d["snapshot"] = t.snapshot
        d["events"] = [{"id": e.id, "event": e.event, "message": e.message, "data": e.data, "at": iso(e.created_at)} for e in t.events]
        d["executions"] = [{"id": x.id, "side": x.side, "qty": x.qty, "price": x.price, "reference_price": x.reference_price, "slippage": x.slippage,
                            "charges": x.charges, "reason": x.reason, "data_source": x.data_source, "note": x.note, "simulated": True,
                            "executed_at": iso(x.executed_at)} for x in t.executions]
    return d
