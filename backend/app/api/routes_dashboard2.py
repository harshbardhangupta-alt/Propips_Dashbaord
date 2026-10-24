"""Dashboard 2 — Mechanical Swing scanner (Nifty LargeMidcap 250)."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import trade_view
from app.core.scheduler import after_market_trigger, is_after_market_slot, is_regular_scan_slot, next_valid_fire, regular_scan_trigger
from app.core.timeutils import iso
from app.database.models import PaperTrade, Quote, Signal
from app.database.repository import audit, get_account, set_setting
from app.database.session import get_db
from app.paper_trading import engine
from app.paper_trading.execution import D2_TRIGGER, TRIGGERS
from app.paper_trading.risk_manager import PlanInput
from app.services import market_data_service as mds
from app.services.scan_service import AFTER_MARKET_LABEL, latest_runs, scan_manager
from app.services.settings_service import K_SCAN_AFTER, K_SCAN_AUTO, bool_setting
from app.services.universe_service import last_success, members

router = APIRouter(prefix="/api/d2", tags=["dashboard2"])


def signal_view(s: Signal, trade: PaperTrade | None = None) -> dict:
    d = s.details or {}
    return {
        "id": s.id, "symbol": s.instrument.symbol, "company_name": s.instrument.company_name, "industry": s.instrument.industry,
        "status": s.status, "score": s.score, "grade": s.grade, "ltp": s.ltp, "pct_change": s.pct_change,
        "daily": d.get("daily"), "h4": d.get("h4"), "impulse": d.get("impulse"), "fibonacci": d.get("fibonacci"),
        "pullback": d.get("pullback"), "demand_zone": d.get("demand_zone"), "confirmation": d.get("confirmation"),
        "plan": d.get("plan"), "timeframes": d.get("timeframes"), "checks": d.get("checks", []),
        "entry": s.entry, "stop_loss": s.stop_loss, "target": s.target, "reward_risk": s.reward_risk,
        "suggested_qty": s.suggested_qty, "capital_required": s.capital_required, "planned_risk": s.planned_risk,
        "components": s.components, "rejection_reasons": s.rejection_reasons, "signal_key": s.signal_key,
        "validity": s.validity, "invalidated_reason": s.invalidated_reason, "valid_until": iso(s.valid_until),
        "is_new": s.is_new, "after_market": s.after_market, "after_market_label": AFTER_MARKET_LABEL if s.after_market else None,
        "first_seen_at": iso(s.first_seen_at), "evaluated_at": iso(s.created_at), "scan_run_id": s.scan_run_id,
        "trade": {"id": trade.id, "status": trade.status} if trade else None,
    }


@router.get("/signals")
def signals(view: str = "qualified", db: Session = Depends(get_db)):
    if view not in ("qualified", "rejected", "all"):
        raise HTTPException(400, "view must be qualified|rejected|all")
    q = select(Signal).where(Signal.is_latest.is_(True))
    if view == "qualified":
        q = q.where(Signal.status == "QUALIFIED")
    elif view == "rejected":
        q = q.where(Signal.status.in_(("REJECTED", "UNAVAILABLE")))
    rows = list(db.scalars(q.order_by(Signal.score.desc())))
    acc = get_account(db, "D2_MECH")
    trades = {t.instrument_id: t for t in db.scalars(select(PaperTrade).where(PaperTrade.account_id == acc.id).order_by(PaperTrade.id))}
    out = []
    for s in rows:
        v = signal_view(s, trades.get(s.instrument_id))
        v["quote"] = mds.quote_view(db.get(Quote, s.instrument_id))
        out.append(v)
    return {"view": view, "count": len(out), "signals": out, "account": engine.account_summary(db, acc)}


@router.get("/signals/{signal_id}")
def signal_detail(signal_id: int, db: Session = Depends(get_db)):
    s = db.get(Signal, signal_id)
    if s is None:
        raise HTTPException(404, "Signal not found")
    v = signal_view(s)
    v["quote"] = mds.quote_view(db.get(Quote, s.instrument_id))
    return v


@router.get("/scanner/status")
def scanner_status(db: Session = Depends(get_db)):
    auto = bool_setting(db, K_SCAN_AUTO, False)
    after = bool_setting(db, K_SCAN_AFTER, True)
    return {
        "auto_scan_enabled": auto,
        "after_market_enabled": after,
        "running": scan_manager.running,
        "progress": scan_manager.progress,
        "next_regular_scan": next_valid_fire(regular_scan_trigger(), is_regular_scan_slot) if auto else None,
        "next_after_market_scan": next_valid_fire(after_market_trigger(), is_after_market_slot) if after else None,
        "schedule": "Every 5 minutes 09:15–15:00 IST on NSE trading days, plus one after-market scan at 19:00 IST",
        "after_market_note": "The 19:00 after-market scan has its own toggle; Stop Auto Scan stops only the 5-minute scans.",
        "universe_size": len(members(db, "NIFTY250")),
        "universe_mapped": len(members(db, "NIFTY250", mapped_only=True)),
        "last_universe_refresh": last_success(db, "NIFTY250"),
        **latest_runs(db),
    }


@router.post("/scanner/start")
def start(db: Session = Depends(get_db)):
    set_setting(db, K_SCAN_AUTO, "true")
    audit(db, "INFO", "dashboard2", "Auto scan started")
    db.commit()
    return scanner_status(db)


@router.post("/scanner/stop")
def stop(db: Session = Depends(get_db)):
    set_setting(db, K_SCAN_AUTO, "false")
    cancelled = scan_manager.cancel()
    audit(db, "INFO", "dashboard2", f"Auto scan stopped (active scan cancelled: {cancelled})")
    db.commit()
    return {**scanner_status(db), "cancelled_active_scan": cancelled}


class AfterMarketToggle(BaseModel):
    enabled: bool


@router.post("/scanner/after-market")
def toggle_after(body: AfterMarketToggle, db: Session = Depends(get_db)):
    set_setting(db, K_SCAN_AFTER, "true" if body.enabled else "false")
    db.commit()
    return scanner_status(db)


@router.post("/scanner/run-now", status_code=202)
def run_now():
    if scan_manager.running:
        return {"status": "ALREADY_RUNNING", "progress": scan_manager.progress}
    threading.Thread(target=scan_manager.run, args=("MANUAL",), name="d2-manual-scan", daemon=True).start()
    return {"status": "STARTED"}


class Override(BaseModel):
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    target: float = Field(gt=0)


class D2Plan(BaseModel):
    signal_id: int
    allocation: float = Field(gt=0)
    override: Override | None = None


class D2Create(D2Plan):
    confirm: bool = False


def _plan(db: Session, p: D2Plan):
    s = db.get(Signal, p.signal_id)
    if s is None:
        raise HTTPException(404, "Signal not found")
    if s.status != "QUALIFIED" or s.entry is None:
        raise HTTPException(400, f"Signal is {s.status}; only QUALIFIED Mechanical Swing setups can be paper traded")
    if s.validity != "VALID":
        raise HTTPException(400, f"Signal validity is {s.validity}; it can no longer be traded")
    entry, stop, target = s.entry, s.stop_loss, s.target
    if p.override:
        entry, stop, target = p.override.entry, p.override.stop_loss, p.override.target
    return s, PlanInput(entry, stop, target, p.allocation, None, s.instrument.lot_size)


@router.post("/preview")
def preview(p: D2Plan, db: Session = Depends(get_db)):
    s, inp = _plan(db, p)
    acc = get_account(db, "D2_MECH")
    plan = engine.preview(db, acc, inp)
    return {"plan": plan.to_dict(), "account": engine.account_summary(db, acc), "signal": signal_view(s),
            "overridden": p.override is not None, "trigger": {"id": D2_TRIGGER, "description": TRIGGERS[D2_TRIGGER]}, "paper_only": True}


@router.post("/trades")
def create(p: D2Create, db: Session = Depends(get_db)):
    if not p.confirm:
        raise HTTPException(400, "Explicit confirmation (confirm=true) is required")
    s, inp = _plan(db, p)
    acc = get_account(db, "D2_MECH")
    original = {"entry": s.entry, "stop_loss": s.stop_loss, "target": s.target, "reward_risk": s.reward_risk} if p.override else None
    try:
        t = engine.create_trade(
            db, acc, s.instrument, inp, trigger=D2_TRIGGER,
            idempotency_key=f"D2:{s.signal_key}:{'OVR' if p.override else 'STD'}",
            signal_id=s.id, signal_key=s.signal_key, valid_until=s.valid_until.replace(tzinfo=None) if s.valid_until else None,
            is_overridden=p.override is not None, original_values=original,
            snapshot={"signal": signal_view(s), "overridden": p.override is not None},
        )
        db.commit()
    except engine.TradeRejected as e:
        db.commit()
        raise HTTPException(422, {"errors": e.errors, "trade_id": e.trade.id if e.trade else None})
    return {"trade": trade_view(t), "message": "Paper auto trade armed: waiting for the buy-stop above the confirmation candle.", "paper_only": True}
