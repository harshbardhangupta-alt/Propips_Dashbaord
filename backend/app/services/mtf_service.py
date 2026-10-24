"""Dashboard 1: MTF evaluation of the Nifty 100 universe and per-trade entry gating."""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.market_calendar import get_calendar
from app.core.timeutils import now_ist
from app.database.models import Instrument, MTFSnapshot, utcnow
from app.database.repository import audit
from app.integrations.dhan_client import DhanClient, DhanError, DhanStatus
from app.services import market_data_service as mds
from app.services.universe_service import members
from app.strategies import dashboard1_mtf as d1

log = logging.getLogger(__name__)
_refresh_lock = threading.Lock()
progress: dict = {"running": False, "done": 0, "total": 0, "started_at": None, "finished_at": None, "errors": 0, "last_error": None}


def evaluate_instrument(client: DhanClient, inst: Instrument, now: datetime | None = None) -> tuple[d1.MTFResult, dict]:
    now = now or now_ist()
    sets = {tf: mds.get_completed(client, inst, tf, now) for tf in ("1D", "4H", "15m", "5m")}
    res = d1.evaluate(sets["1D"].candles, sets["4H"].candles, sets["15m"].candles, sets["5m"].candles, now, get_calendar())
    meta = {tf: {"source": s.source, "fetched_at": s.fetched_at.isoformat(), "bars": len(s.candles), "warnings": s.warnings} for tf, s in sets.items()}
    return res, meta


def store_snapshot(db: Session, inst: Instrument, res: d1.MTFResult | None, meta: dict | None, error: str | None = None) -> MTFSnapshot:
    snap = db.get(MTFSnapshot, inst.id) or MTFSnapshot(instrument_id=inst.id)
    if res is None:
        snap.daily_trend = snap.h4_trend = snap.m15_status = snap.m5_status = snap.bias = snap.confirmation = "UNAVAILABLE"
        snap.quality = 0
        snap.details = {}
    else:
        snap.daily_trend, snap.h4_trend = res.daily.status, res.h4.status
        snap.m15_status, snap.m5_status = res.m15.status, res.m5.status
        snap.bias, snap.confirmation, snap.quality = res.bias, res.confirmation, res.quality
        snap.details = {**res.to_dict(), "data": meta}
    snap.error = error
    snap.evaluated_at = utcnow()
    db.merge(snap)
    return snap


def refresh_universe(db: Session, client: DhanClient, cancel: threading.Event | None = None) -> dict:
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "ALREADY_RUNNING", **progress}
    try:
        insts = members(db, "NIFTY100", mapped_only=True)
        progress.update(running=True, done=0, total=len(insts), started_at=utcnow().isoformat(), finished_at=None, errors=0, last_error=None)
        auth_failures = 0
        for inst in insts:
            if cancel is not None and cancel.is_set():
                break
            try:
                res, meta = evaluate_instrument(client, inst)
                store_snapshot(db, inst, res, meta)
                auth_failures = 0
            except DhanError as e:
                progress["errors"] += 1
                progress["last_error"] = f"{inst.symbol}: {e.status} {e.message}"
                store_snapshot(db, inst, None, None, f"{e.status}: {e.message}")
                if e.status in (DhanStatus.AUTH_FAILED, DhanStatus.PERMISSION_DENIED):
                    auth_failures += 1
                    if auth_failures >= 3:
                        audit(db, "ERROR", "dashboard1", f"MTF refresh aborted: {e.status} {e.message}")
                        break
            progress["done"] += 1
            db.commit()
        status = "SUCCESS" if progress["errors"] == 0 and progress["done"] == len(insts) else ("FAILED" if progress["done"] == progress["errors"] else "PARTIAL")
        return {"status": status, **progress}
    finally:
        progress.update(running=False, finished_at=utcnow().isoformat())
        _refresh_lock.release()
