"""Background monitoring of pending entries and open paper positions on completed 5m candles."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import now_ist
from app.database.models import Instrument, PaperTrade, Quote, utcnow
from app.database.repository import audit
from app.integrations.dhan_client import DhanClient, DhanError
from app.paper_trading import engine
from app.services import market_data_service as mds
from app.services.mtf_service import evaluate_instrument, store_snapshot
from app.services.signal_service import signal_entry_gate

log = logging.getLogger(__name__)


def expire_overdue(db: Session) -> int:
    n = 0
    for t in db.scalars(select(PaperTrade).where(PaperTrade.status.in_(("PENDING_ENTRY", "CONFIGURED")), PaperTrade.valid_until.isnot(None),
                                                 PaperTrade.valid_until < utcnow())):
        engine.expire_trade(db, t, "Entry validity window ended without a trigger")
        n += 1
    return n


def monitor(db: Session, client: DhanClient, now: datetime | None = None) -> dict:
    now = now or now_ist()
    stats = {"instruments": 0, "trades": 0, "actions": [], "errors": []}
    stats["expired"] = expire_overdue(db)
    trades = list(db.scalars(select(PaperTrade).where(PaperTrade.status.in_(("PENDING_ENTRY", "OPEN")))))
    by_inst: dict[int, list[PaperTrade]] = defaultdict(list)
    for t in trades:
        by_inst[t.instrument_id].append(t)
    for inst_id, ts in by_inst.items():
        inst = db.get(Instrument, inst_id)
        stats["instruments"] += 1
        try:
            m5 = mds.get_completed(client, inst, "5m", now)
        except DhanError as e:
            stats["errors"].append(f"{inst.symbol}: {e.status} {e.message}")
            continue
        mtf_cache: dict = {}

        def d1_gate(trade: PaperTrade, _candle) -> tuple[bool, str]:
            if "res" not in mtf_cache:
                try:
                    res, meta = evaluate_instrument(client, inst, now)
                    store_snapshot(db, inst, res, meta)
                    mtf_cache["res"] = res
                except DhanError as e:
                    mtf_cache["res"] = None
                    mtf_cache["err"] = f"{e.status}: {e.message}"
            res = mtf_cache["res"]
            if res is None:
                return False, f"MTF data unavailable ({mtf_cache.get('err')})"
            return (True, "MTF aligned") if res.entry_conditions_ok else (False, "; ".join(res.reasons) or "MTF not aligned")

        def d2_gate(trade: PaperTrade, _candle) -> tuple[bool, str]:
            return signal_entry_gate(db, trade.signal_id)

        for t in ts:
            stats["trades"] += 1
            is_d2 = t.strategy == "DASHBOARD2_MECHANICAL"
            acts = engine.process_candles(db, t, m5.candles, d2_gate if is_d2 else d1_gate, m5.source,
                                          gap_policy="REJECT" if is_d2 else "SKIP", invalidate_below_stop=is_d2)
            if acts:
                stats["actions"].append({"trade_id": t.id, "symbol": t.symbol, "actions": acts})
        db.commit()
    # Mark-to-market open positions with newer quote snapshots when available.
    for t in db.scalars(select(PaperTrade).where(PaperTrade.status == "OPEN")):
        q = db.get(Quote, t.instrument_id)
        if q and q.ltp and (t.last_price_at is None or q.fetched_at > t.last_price_at):
            engine.mark_to_market(t, q.ltp, q.fetched_at)
    if stats["errors"]:
        audit(db, "WARN", "position_monitor", f"{len(stats['errors'])} instrument(s) could not be monitored", {"errors": stats["errors"][:20]})
    db.commit()
    return stats
