"""System status, audit log, charts data and AI explanations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import get_instrument
from app.core.config import PAPER_BANNER, PAPER_TRADING_ONLY, get_settings
from app.core.market_calendar import get_calendar
from app.core.scheduler import get_scheduler, jobs_view
from app.core.timeutils import iso, now_ist
from app.database.models import AuditEvent, MTFSnapshot, Quote, Signal
from app.database.session import get_db
from app.integrations import tradingview
from app.integrations.dhan_client import ALLOWED_ENDPOINTS, DhanError
from app.services import explanation_service
from app.services import market_data_service as mds
from app.services.scan_service import latest_runs, scan_manager
from app.services.settings_service import dhan_view, get_dhan_client, openai_view

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def status(db: Session = Depends(get_db)):
    cal = get_calendar()
    now = now_ist()
    newest_quote = db.scalar(select(func.max(Quote.fetched_at)))
    dv = dhan_view(db)
    ov = openai_view(db)
    return {
        "paper_trading_only": PAPER_TRADING_ONLY,
        "banner": PAPER_BANNER,
        "live_trading_available": False,
        "now_ist": now.isoformat(),
        "market_open": cal.is_market_open(now),
        "trading_day": cal.is_trading_day(now.date()),
        "holiday": cal.holiday_name(now.date()),
        "calendar": cal.year_status(now.year),
        "dhan": {"status": dv["status"], "client_id_set": dv["client_id_set"], "token_set": dv["access_token_set"],
                 "token_reminder_due": dv["token_reminder_due"], "detail": dv["status_detail"]},
        "openai": {"status": ov["status"], "enabled": ov["enabled"], "model": ov["model"]},
        "market_data": {"newest_quote_at": iso(newest_quote), "quote_mode": "REST snapshot polling (/marketfeed/ohlc). WebSocket streaming is not implemented.",
                        "state": mds.quote_view(db.scalar(select(Quote).order_by(Quote.fetched_at.desc()).limit(1)))["data_state"]},
        "scheduler": {"running": bool(get_scheduler() and get_scheduler().running), "enabled": get_settings().enable_scheduler, "jobs": jobs_view()},
        "scanner": {"running": scan_manager.running, "progress": scan_manager.progress, **latest_runs(db)},
        "counts": {"mtf_snapshots": db.scalar(select(func.count()).select_from(MTFSnapshot)), "signals": db.scalar(select(func.count()).select_from(Signal))},
        "allowed_dhan_endpoints": sorted(f"{m} {p}" for m, p in ALLOWED_ENDPOINTS),
        "database": get_settings().database_url.split("///")[-1],
    }


@router.get("/audit")
def audit_log(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(max(limit, 1), 1000)))
    return [{"id": r.id, "level": r.level, "source": r.source, "message": r.message, "data": r.data, "at": iso(r.created_at)} for r in rows]


@router.get("/chart/{symbol}")
def chart(symbol: str, tf: str = "1D", db: Session = Depends(get_db)):
    """Validated Dhan OHLC for the in-app TradingView Lightweight Chart (same data the engines use)."""
    if tf not in ("1D", "4H", "1H", "15m", "5m"):
        raise HTTPException(400, "Unsupported timeframe")
    inst = get_instrument(db, symbol)
    try:
        cs = mds.get_completed(get_dhan_client(db), inst, tf)
    except DhanError as e:
        return {"symbol": inst.symbol, "available": False, "error": e.to_dict(), "candles": [], "tradingview_symbol": tradingview.symbol_for(inst.symbol)}
    return {"symbol": inst.symbol, "available": bool(cs.candles), "timeframe": tf, "source": cs.source, "fetched_at": iso(cs.fetched_at),
            "note": "Completed candles only. Data source: Dhan (same as the strategy engine).",
            "candles": [{"time": int(c.ts), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in cs.candles[-600:]],
            "tradingview_symbol": tradingview.symbol_for(inst.symbol), "warnings": cs.warnings}


class ExplainIn(BaseModel):
    kind: str  # D2_SIGNAL | D1_MTF
    signal_id: int | None = None
    symbol: str | None = None


@router.post("/explain")
def explain(body: ExplainIn, db: Session = Depends(get_db)):
    if body.kind == "D2_SIGNAL":
        s = db.get(Signal, body.signal_id or 0)
        if s is None:
            raise HTTPException(404, "Signal not found")
        ctx = {"strategy": "Mechanical Swing Trading System (Dashboard 2)", "symbol": s.instrument.symbol, "status": s.status, "score": s.score,
               "grade": s.grade, "entry": s.entry, "stop_loss": s.stop_loss, "target": s.target, "reward_risk": s.reward_risk,
               "validity": s.validity, "rejection_reasons": s.rejection_reasons, "components": s.components, "details": s.details}
    elif body.kind == "D1_MTF":
        inst = get_instrument(db, body.symbol or "")
        snap = db.get(MTFSnapshot, inst.id)
        if snap is None:
            raise HTTPException(404, "No MTF evaluation stored for this symbol yet")
        ctx = {"strategy": "Dashboard 1 multi-timeframe baseline", "symbol": inst.symbol, "evaluation": snap.details, "evaluated_at": iso(snap.evaluated_at)}
    else:
        raise HTTPException(400, "kind must be D2_SIGNAL or D1_MTF")
    return explanation_service.explain(db, body.kind, ctx)
