"""Dashboard 2 signal persistence, de-duplication, validity and invalidation."""
from __future__ import annotations

from datetime import timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.timeutils import now_ist
from app.database.models import Instrument, ScanRun, Signal, utcnow
from app.strategies.dashboard2_mechanical import MechResult


def _naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt is not None and dt.tzinfo else dt


def _triggered_only(res: MechResult) -> bool:
    fails = res.mandatory_failures()
    return len(fails) == 1 and fails[0].rule == "H" and "already triggered" in fails[0].detail


def upsert_signal(db: Session, inst: Instrument, res: MechResult, run: ScanRun | None, quote: dict | None, sizing: dict | None) -> Signal:
    """One row per (instrument, signal_key). Re-detections update the same row (no duplicates)."""
    existing = None
    if res.signal_key:
        existing = db.scalar(select(Signal).where(Signal.instrument_id == inst.id, Signal.signal_key == res.signal_key))
    if existing is None:
        # Reuse the instrument's latest key-less row instead of piling up rejection rows.
        existing = db.scalar(select(Signal).where(Signal.instrument_id == inst.id, Signal.signal_key.is_(None), Signal.is_latest.is_(True)))
        if existing is not None and res.signal_key:
            existing = None
    db.execute(update(Signal).where(Signal.instrument_id == inst.id).values(is_latest=False))
    sig = existing or Signal(instrument_id=inst.id, first_seen_at=utcnow(), is_new=True)
    # "New" = first time this setup is seen as QUALIFIED.
    sig.is_new = existing is None or existing.status != "QUALIFIED"
    prev_status = existing.status if existing is not None else None
    sig.scan_run_id = run.id if run else None
    sig.is_latest = True
    sig.after_market = bool(run and run.kind == "AFTER_MARKET")
    sig.ltp = (quote or {}).get("ltp")
    sig.pct_change = (quote or {}).get("pct_change")
    sig.created_at = utcnow()
    sig.signal_key = res.signal_key
    sig.score, sig.grade = res.score, res.grade
    sig.components = res.components
    sig.details = {**res.details, "checks": [c.to_dict() for c in res.checks]}
    sig.valid_until = _naive(res.valid_until)
    if prev_status == "QUALIFIED" and res.status != "QUALIFIED":
        if _triggered_only(res):
            sig.validity = "TRIGGERED"
            sig.rejection_reasons = res.reasons
            return sig  # keep the qualified plan intact
        sig.status = "REJECTED"
        sig.validity = "INVALIDATED"
        sig.invalidated_reason = "; ".join(res.reasons)[:2000]
    else:
        sig.status = res.status
        sig.validity = "VALID" if res.status == "QUALIFIED" else "N/A"
        sig.invalidated_reason = None
    sig.rejection_reasons = res.reasons
    sig.entry, sig.stop_loss, sig.target, sig.reward_risk = res.entry, res.stop_loss, res.target, res.reward_risk
    if res.status == "QUALIFIED" and res.entry and res.stop_loss and sizing:
        risk = res.entry - res.stop_loss
        q = min(int(sizing["allocation"] // res.entry), int(sizing["risk_budget"] // risk)) if risk > 0 else 0
        sig.suggested_qty = max(0, q)
        sig.capital_required = round(q * res.entry, 2)
        sig.planned_risk = round(q * risk, 2)
    else:
        sig.suggested_qty = sig.capital_required = sig.planned_risk = None
    if sig.status == "QUALIFIED" and sig.valid_until and sig.valid_until < utcnow():
        sig.validity = "EXPIRED"
    if existing is None:
        db.add(sig)
    db.flush()
    return sig


def expire_signals(db: Session) -> int:
    rows = db.scalars(select(Signal).where(Signal.validity.in_(("VALID", "TRIGGERED")), Signal.valid_until.isnot(None), Signal.valid_until < utcnow()))
    n = 0
    for s in rows:
        s.validity = "EXPIRED"
        n += 1
    return n


def signal_entry_gate(db: Session, signal_id: int | None) -> tuple[bool, str]:
    if signal_id is None:
        return False, "No linked signal"
    s = db.get(Signal, signal_id)
    if s is None:
        return False, "Signal not found"
    if s.validity not in ("VALID", "TRIGGERED"):
        return False, f"Signal is {s.validity}: {s.invalidated_reason or ''}".strip()
    if s.valid_until and s.valid_until < utcnow():
        return False, "Signal validity window has ended"
    return True, "Signal valid"


def now_iso() -> str:
    return now_ist().isoformat()
