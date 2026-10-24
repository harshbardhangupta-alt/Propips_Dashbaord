"""Dashboard 2 Nifty 250 scanner: one scan at a time, cancellable, honest status."""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.market_calendar import get_calendar
from app.core.timeutils import iso, now_ist
from app.database.models import Quote, ScanRun, utcnow
from app.database.repository import audit, get_account
from app.database.session import SessionLocal
from app.integrations.dhan_client import DhanError, DhanStatus
from app.paper_trading.engine import limits_for
from app.services import market_data_service as mds
from app.services.settings_service import get_dhan_client
from app.services.signal_service import upsert_signal
from app.services.universe_service import members
from app.strategies import dashboard2_mechanical as d2

log = logging.getLogger(__name__)

AFTER_MARKET_LABEL = "AFTER-MARKET SCAN — NOT LIVE MARKET ACTIVITY"


class ScanManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.progress: dict = {"running": False, "run_id": None, "kind": None, "done": 0, "total": 0, "current": None}

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def cancel(self) -> bool:
        if self.running:
            self.cancel_event.set()
            return True
        return False

    def run(self, kind: str, session_factory=SessionLocal, now: datetime | None = None) -> dict:
        """Run a full scan synchronously. Returns immediately if another scan is running."""
        if not self._lock.acquire(blocking=False):
            return {"status": "SKIPPED", "message": "A scan is already running"}
        self.cancel_event.clear()
        db: Session = session_factory()
        run = ScanRun(kind=kind, status="RUNNING", label=AFTER_MARKET_LABEL if kind == "AFTER_MARKET" else None)
        try:
            db.add(run)
            db.commit()
            self.progress.update(running=True, run_id=run.id, kind=kind, done=0, total=0, current=None)
            try:
                client = get_dhan_client(db)
            except DhanError as e:
                return self._finish(db, run, "FAILED", f"{e.status}: {e.message}")
            insts = members(db, "NIFTY250")
            run.universe_size = len(insts)
            self.progress["total"] = len(insts)
            if not insts:
                return self._finish(db, run, "FAILED", "Nifty 250 universe is empty — sync it from Settings first")
            acc = get_account(db, "D2_MECH")
            lim = limits_for(db, acc)
            sizing = {"allocation": min(acc.max_allocation_per_trade, lim.available_cash),
                      "risk_budget": min(lim.available_cash * acc.risk_pct_per_trade / 100, acc.max_risk_per_trade)}
            params = d2.MechParams(min_rr=max(3.0, acc.min_reward_risk))
            cal = get_calendar()
            consecutive_auth = 0
            last_err = None
            for inst in insts:
                if self.cancel_event.is_set():
                    return self._finish(db, run, "CANCELLED", f"Stopped by user after {run.scanned}/{run.universe_size} stocks")
                self.progress["current"] = inst.symbol
                if not inst.security_id:
                    run.unavailable += 1
                    run.scanned += 1
                    self.progress["done"] += 1
                    continue
                t = now or now_ist()
                try:
                    daily = mds.get_completed(client, inst, "1D", t).candles
                    h1 = mds.get_completed(client, inst, "1H", t).candles
                    h4 = mds.get_completed(client, inst, "4H", t).candles
                    res = d2.evaluate(inst.symbol, daily, h4, h1, t, cal, params, sizing)
                    res.details["instrument"] = {"tick": inst.tick_size, "security_id": inst.security_id}
                    q = mds.quote_view(db.get(Quote, inst.id))
                    upsert_signal(db, inst, res, run, q, sizing)
                    consecutive_auth = 0
                    if res.status == "QUALIFIED":
                        run.qualified += 1
                    elif res.status == "REJECTED":
                        run.rejected += 1
                    else:
                        run.unavailable += 1
                except DhanError as e:
                    run.errors += 1
                    last_err = f"{inst.symbol}: {e.status} {e.message}"
                    if e.status in (DhanStatus.AUTH_FAILED, DhanStatus.PERMISSION_DENIED, DhanStatus.NOT_CONFIGURED):
                        consecutive_auth += 1
                        if consecutive_auth >= 3:
                            return self._finish(db, run, "FAILED", f"Aborted: {last_err}")
                except Exception as e:  # noqa: BLE001 - one bad symbol must not kill the scan
                    log.exception("scan error for %s", inst.symbol)
                    run.errors += 1
                    last_err = f"{inst.symbol}: {type(e).__name__}: {e}"
                run.scanned += 1
                self.progress["done"] += 1
                db.commit()
            if run.errors == 0 and run.unavailable == 0:
                status = "SUCCESS"
            elif run.errors >= run.universe_size:
                status = "FAILED"
            else:
                status = "PARTIAL"
            msg = f"Scanned {run.scanned}/{run.universe_size}: {run.qualified} qualified, {run.rejected} rejected, {run.unavailable} unavailable, {run.errors} errors"
            if last_err:
                msg += f". Last error: {last_err}"
            return self._finish(db, run, status, msg)
        except Exception as e:  # noqa: BLE001
            log.exception("scan crashed")
            db.rollback()
            return self._finish(db, run, "FAILED", f"{type(e).__name__}: {e}")
        finally:
            self.progress.update(running=False, current=None)
            db.close()
            self._lock.release()

    def _finish(self, db: Session, run: ScanRun, status: str, message: str) -> dict:
        run.status = status
        run.message = message
        run.finished_at = utcnow()
        audit(db, "INFO" if status == "SUCCESS" else "WARN", "dashboard2", f"Scan #{run.id} ({run.kind}) {status}: {message}")
        db.commit()
        return {"status": status, "run_id": run.id, "message": message}


scan_manager = ScanManager()


def run_view(r: ScanRun | None) -> dict | None:
    if r is None:
        return None
    return {"id": r.id, "kind": r.kind, "status": r.status, "label": r.label, "started_at": iso(r.started_at), "finished_at": iso(r.finished_at),
            "universe_size": r.universe_size, "scanned": r.scanned, "qualified": r.qualified, "rejected": r.rejected,
            "unavailable": r.unavailable, "errors": r.errors, "message": r.message}


def latest_runs(db: Session) -> dict:
    last = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
    last_ok = db.scalar(select(ScanRun).where(ScanRun.status.in_(("SUCCESS", "PARTIAL")), ScanRun.kind != "AFTER_MARKET").order_by(ScanRun.id.desc()))
    last_am = db.scalar(select(ScanRun).where(ScanRun.kind == "AFTER_MARKET").order_by(ScanRun.id.desc()))
    return {"latest": run_view(last), "last_successful": run_view(last_ok), "last_after_market": run_view(last_am)}
