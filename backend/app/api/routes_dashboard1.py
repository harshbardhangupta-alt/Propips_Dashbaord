"""Dashboard 1 — Nifty 100 MTF paper trading."""
from __future__ import annotations

import threading
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import get_instrument, trade_view
from app.core.market_calendar import get_calendar
from app.core.timeutils import MARKET_CLOSE, ist_combine, iso, now_ist
from app.database.models import MTFSnapshot, PaperTrade, Quote
from app.database.repository import get_account
from app.database.session import SessionLocal, get_db
from app.integrations.dhan_client import DhanError
from app.paper_trading import engine
from app.paper_trading.execution import DEFAULT_D1_TRIGGER, TRIGGERS
from app.paper_trading.risk_manager import PlanInput
from app.services import market_data_service as mds
from app.services import mtf_service
from app.services.settings_service import get_dhan_client
from app.services.universe_service import last_success, members
from app.strategies import dashboard1_mtf as d1

router = APIRouter(prefix="/api/d1", tags=["dashboard1"])
D1_PENDING_VALID_TRADING_DAYS = 5


@router.get("/stocks")
def stocks(db: Session = Depends(get_db)):
    insts = members(db, "NIFTY100")
    acc = get_account(db, "D1_MTF")
    active = {t.instrument_id: t for t in db.scalars(select(PaperTrade).where(PaperTrade.account_id == acc.id, PaperTrade.status.in_(engine.ACTIVE_STATES)))}
    rows = []
    for i in insts:
        q = mds.quote_view(db.get(Quote, i.id))
        s = db.get(MTFSnapshot, i.id)
        t = active.get(i.id)
        unreal = None
        if t and t.status == "OPEN" and t.entry_price and t.last_price:
            unreal = round((t.last_price - t.entry_price) * t.filled_qty, 2)
        rows.append({
            "symbol": i.symbol, "company_name": i.company_name, "industry": i.industry, "mapping_status": i.mapping_status,
            "security_id": i.security_id, "quote": q,
            "daily_trend": s.daily_trend if s else "NOT_EVALUATED", "h4_trend": s.h4_trend if s else "NOT_EVALUATED",
            "m15_status": s.m15_status if s else "NOT_EVALUATED", "m5_status": s.m5_status if s else "NOT_EVALUATED",
            "bias": s.bias if s else "NOT_EVALUATED", "confirmation": s.confirmation if s else "NOT_EVALUATED",
            "quality": s.quality if s else 0, "mtf_evaluated_at": iso(s.evaluated_at) if s else None, "mtf_error": s.error if s else None,
            "trade": {"id": t.id, "status": t.status, "auto_entry_enabled": t.auto_entry_enabled} if t else None,
            "auto_trade_status": (t.status if t else "NOT_CONFIGURED"), "position_status": ("OPEN" if t and t.status == "OPEN" else "NONE"),
            "unrealized_pnl": unreal,
        })
    return {"universe": "NIFTY100", "count": len(rows), "last_universe_refresh": last_success(db, "NIFTY100"),
            "mtf_refresh": mtf_service.progress, "stocks": rows, "account": engine.account_summary(db, acc)}


@router.post("/refresh-mtf", status_code=202)
def refresh_mtf(db: Session = Depends(get_db)):
    try:
        get_dhan_client(db)
    except DhanError as e:
        raise HTTPException(400, f"{e.status}: {e.message}")
    if mtf_service.progress.get("running"):
        return {"status": "ALREADY_RUNNING", "progress": mtf_service.progress}

    def work():
        s = SessionLocal()
        try:
            mtf_service.refresh_universe(s, get_dhan_client(s))
        finally:
            s.close()

    threading.Thread(target=work, name="d1-mtf-refresh", daemon=True).start()
    return {"status": "STARTED"}


@router.get("/stocks/{symbol}/mtf")
def stock_mtf(symbol: str, db: Session = Depends(get_db)):
    inst = get_instrument(db, symbol)
    try:
        client = get_dhan_client(db)
        res, meta = mtf_service.evaluate_instrument(client, inst)
    except DhanError as e:
        snap = db.get(MTFSnapshot, inst.id)
        return {"symbol": inst.symbol, "available": False, "error": e.to_dict(), "cached": snap.details if snap else None,
                "cached_at": iso(snap.evaluated_at) if snap else None}
    mtf_service.store_snapshot(db, inst, res, meta)
    db.commit()
    return {"symbol": inst.symbol, "available": True, **res.to_dict(), "data": meta, "evaluated_at": iso(now_ist())}


class D1Plan(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    allocation: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    max_risk_amount: float | None = Field(default=None, gt=0)
    entry_trigger: str = DEFAULT_D1_TRIGGER
    entry_source: str = Field(default="MANUAL", pattern="^(MANUAL|LATEST_VERIFIED_PRICE)$")


class D1Create(D1Plan):
    confirm: bool = False
    client_request_id: str | None = Field(default=None, max_length=64)


@router.get("/triggers")
def triggers():
    return {"default": DEFAULT_D1_TRIGGER, "triggers": TRIGGERS, "min_reward_risk": d1.DEFAULT_MIN_RR,
            "pending_validity_trading_days": D1_PENDING_VALID_TRADING_DAYS}


@router.post("/preview")
def preview(p: D1Plan, db: Session = Depends(get_db)):
    inst = get_instrument(db, p.symbol)
    if p.entry_trigger not in TRIGGERS:
        raise HTTPException(400, "Unknown entry trigger")
    acc = get_account(db, "D1_MTF")
    plan = engine.preview(db, acc, PlanInput(p.entry, p.stop_loss, p.take_profit, p.allocation, p.max_risk_amount, inst.lot_size))
    snap = db.get(MTFSnapshot, inst.id)
    return {"plan": plan.to_dict(), "account": engine.account_summary(db, acc), "quote": mds.quote_view(db.get(Quote, inst.id)),
            "mtf": snap.details if snap else None, "mtf_evaluated_at": iso(snap.evaluated_at) if snap else None,
            "trigger": {"id": p.entry_trigger, "description": TRIGGERS[p.entry_trigger]}, "paper_only": True}


@router.post("/trades")
def create(p: D1Create, db: Session = Depends(get_db)):
    if not p.confirm:
        raise HTTPException(400, "Explicit confirmation (confirm=true) is required to enable a paper auto trade")
    inst = get_instrument(db, p.symbol)
    if not inst.security_id:
        raise HTTPException(400, f"{inst.symbol} is not mapped to a Dhan security id; monitoring is impossible")
    if p.entry_trigger not in TRIGGERS:
        raise HTTPException(400, "Unknown entry trigger")
    acc = get_account(db, "D1_MTF")
    snap = db.get(MTFSnapshot, inst.id)
    cal = get_calendar()
    # Pending entry stays armed for N trading sessions (today counts if it is a trading day).
    d = now_ist().date()
    if not cal.is_trading_day(d):
        d = cal.next_trading_day(d)
    for _ in range(D1_PENDING_VALID_TRADING_DAYS - 1):
        d = cal.next_trading_day(d)
    valid_until = ist_combine(d, MARKET_CLOSE)
    key = f"D1:{inst.symbol}:{p.client_request_id or uuid.uuid4().hex}"
    try:
        t = engine.create_trade(
            db, acc, inst, PlanInput(p.entry, p.stop_loss, p.take_profit, p.allocation, p.max_risk_amount, inst.lot_size),
            trigger=p.entry_trigger, idempotency_key=key, valid_until=valid_until,
            snapshot={"entry_source": p.entry_source, "mtf_at_configuration": snap.details if snap else None,
                      "quote_at_configuration": mds.quote_view(db.get(Quote, inst.id))},
        )
        db.commit()
    except engine.TradeRejected as e:
        db.commit()  # persist the REJECTED record for the audit trail
        raise HTTPException(422, {"errors": e.errors, "trade_id": e.trade.id if e.trade else None})
    return {"trade": trade_view(t), "message": "Paper auto trade armed. No position is opened until the entry trigger and MTF conditions pass.",
            "paper_only": True}
