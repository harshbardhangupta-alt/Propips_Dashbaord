"""Paper trade book, accounts and manual paper actions. Nothing here touches a broker."""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import trade_view
from app.core.timeutils import IST
from app.database.models import PaperAccount, PaperTrade, Quote
from app.database.repository import audit, get_account
from app.database.session import get_db
from app.paper_trading import engine
from app.services import market_data_service as mds

router = APIRouter(prefix="/api/paper", tags=["paper"])
STRATEGY_MIN_RR_FLOOR = {"D1_MTF": 1.0, "D2_MECH": 3.0}


@router.get("/accounts")
def accounts(db: Session = Depends(get_db)):
    return {"accounts": [engine.account_summary(db, a) for a in db.scalars(select(PaperAccount).order_by(PaperAccount.id))],
            "label": "Simulated balances — not real money or broker balances"}


class Limits(BaseModel):
    risk_pct_per_trade: float | None = Field(default=None, gt=0, le=10)
    max_risk_per_trade: float | None = Field(default=None, gt=0)
    max_allocation_per_trade: float | None = Field(default=None, gt=0)
    max_open_positions: int | None = Field(default=None, ge=1, le=50)
    max_aggregate_risk_pct: float | None = Field(default=None, gt=0, le=50)
    min_reward_risk: float | None = Field(default=None, gt=0, le=20)
    slippage_bps: float | None = Field(default=None, ge=0, le=200)
    max_entry_deviation_pct: float | None = Field(default=None, ge=0, le=10)


@router.put("/accounts/{code}/limits")
def update_limits(code: str, body: Limits, db: Session = Depends(get_db)):
    acc = _acc(db, code)
    data = body.model_dump(exclude_none=True)
    floor = STRATEGY_MIN_RR_FLOOR[acc.code]
    if "min_reward_risk" in data and data["min_reward_risk"] < floor:
        raise HTTPException(400, f"Minimum reward:risk for {acc.name} cannot be below 1:{floor:g}")
    for k, v in data.items():
        setattr(acc, k, v)
    audit(db, "INFO", "paper", f"Limits updated for {acc.code}", data)
    db.commit()
    return engine.account_summary(db, acc)


class Reset(BaseModel):
    confirm: str
    initial_capital: float | None = Field(default=None, gt=0, le=1e9)


@router.post("/accounts/{code}/reset")
def reset(code: str, body: Reset, db: Session = Depends(get_db)):
    acc = _acc(db, code)
    if body.confirm != "RESET":
        raise HTTPException(400, "Type RESET to confirm resetting this paper account")
    try:
        engine.reset_account(db, acc, body.initial_capital)
    except engine.TradeRejected as e:
        raise HTTPException(409, {"errors": e.errors})
    audit(db, "WARN", "paper", f"Paper account {acc.code} reset to {acc.initial_capital}")
    db.commit()
    return engine.account_summary(db, acc)


def _acc(db: Session, code: str) -> PaperAccount:
    if code not in engine.ACCOUNT_DEFS:
        raise HTTPException(404, "Unknown account")
    return get_account(db, code)


@router.get("/trades")
def trades(status: str | None = None, strategy: str | None = None, symbol: str | None = None,
           date_from: date | None = None, date_to: date | None = None, limit: int = 500, db: Session = Depends(get_db)):
    q = select(PaperTrade)
    if status:
        sts = [s.strip().upper() for s in status.split(",")]
        if any(s not in engine.ALL_STATES for s in sts):
            raise HTTPException(400, "Invalid status filter")
        q = q.where(PaperTrade.status.in_(sts))
    if strategy:
        q = q.where(PaperTrade.strategy == strategy)
    if symbol:
        q = q.where(PaperTrade.symbol.like(f"%{symbol.upper()[:32]}%"))
    if date_from:
        q = q.where(PaperTrade.created_at >= datetime.combine(date_from, time.min, IST).astimezone(timezone.utc).replace(tzinfo=None))
    if date_to:
        q = q.where(PaperTrade.created_at <= datetime.combine(date_to, time.max, IST).astimezone(timezone.utc).replace(tzinfo=None))
    rows = list(db.scalars(q.order_by(PaperTrade.id.desc()).limit(min(max(limit, 1), 2000))))
    closed = [t for t in rows if t.status == "CLOSED"]
    summary = {
        "count": len(rows),
        "closed": len(closed),
        "gross_pnl": round(sum(t.gross_pnl or 0 for t in closed), 2),
        "charges": round(sum(t.charges or 0 for t in closed), 2),
        "net_pnl": round(sum(t.net_pnl or 0 for t in closed), 2),
        "unrealized_pnl": round(sum(((t.last_price or 0) - (t.entry_price or 0)) * t.filled_qty for t in rows if t.status == "OPEN"), 2),
        "wins": sum(1 for t in closed if (t.net_pnl or 0) > 0),
        "losses": sum(1 for t in closed if (t.net_pnl or 0) <= 0),
        "label": "SIMULATED PAPER-TRADING RESULTS",
    }
    return {"trades": [trade_view(t) for t in rows], "summary": summary}


def _trade(db: Session, trade_id: int) -> PaperTrade:
    t = db.get(PaperTrade, trade_id)
    if t is None:
        raise HTTPException(404, "Trade not found")
    return t


@router.get("/trades/{trade_id}")
def trade_detail(trade_id: int, db: Session = Depends(get_db)):
    return trade_view(_trade(db, trade_id), detail=True)


def _act(db: Session, trade_id: int, fn):
    t = _trade(db, trade_id)
    try:
        fn(db, t)
    except engine.TradeRejected as e:
        raise HTTPException(409, {"errors": e.errors})
    db.commit()
    return trade_view(t, detail=True)


@router.post("/trades/{trade_id}/cancel")
def cancel(trade_id: int, db: Session = Depends(get_db)):
    return _act(db, trade_id, engine.cancel_trade)


@router.post("/trades/{trade_id}/disable-auto")
def disable(trade_id: int, db: Session = Depends(get_db)):
    return _act(db, trade_id, engine.disable_auto_entry)


@router.post("/trades/{trade_id}/enable-auto")
def enable(trade_id: int, db: Session = Depends(get_db)):
    return _act(db, trade_id, engine.enable_auto_entry)


class ManualExit(BaseModel):
    confirm: bool = False


@router.post("/trades/{trade_id}/manual-exit")
def manual_exit(trade_id: int, body: ManualExit, db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(400, "Confirmation required for a manual paper exit")
    t = _trade(db, trade_id)
    if t.status != "OPEN":
        raise HTTPException(409, f"Trade is {t.status}, not OPEN")
    q = mds.quote_view(db.get(Quote, t.instrument_id))
    if q["ltp"] is None or q["data_state"] == "STALE":
        raise HTTPException(409, f"No fresh verified price for {t.symbol} (state {q['data_state']}); refresh quotes first")
    try:
        engine.manual_exit(db, t, q["ltp"], f"{q['source']} @ {q['fetched_at']}")
    except engine.TradeRejected as e:
        raise HTTPException(409, {"errors": e.errors})
    db.commit()
    return trade_view(t, detail=True)
