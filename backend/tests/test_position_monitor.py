"""Position monitor with mocked 5m data: D1 entries need MTF alignment, D2 entries need a valid signal."""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.timeutils import IST
from app.database.models import Instrument, Signal, utcnow
from app.database.repository import get_account
from app.market_data.candles import Candle
from app.paper_trading import engine, position_manager as pm
from app.paper_trading.risk_manager import PlanInput
from app.services.market_data_service import CandleSet

DAY = datetime(2026, 10, 26, tzinfo=IST)  # Monday


def m5(prices):
    out = []
    t = DAY.replace(hour=9, minute=15)
    for o, h, l, c in prices:
        out.append(Candle(t.timestamp(), o, h, l, c))
        t += timedelta(minutes=5)
    return out


class R:
    def __init__(self, ok):
        self.entry_conditions_ok = ok
        self.reasons = [] if ok else ["4H: condition not met (NEUTRAL)"]


def setup(db, monkeypatch, candles, mtf_ok=True):
    i = Instrument(symbol="AAA", company_name="A", security_id="1", mapping_status="MAPPED")
    db.add(i)
    db.flush()
    monkeypatch.setattr(pm.mds, "get_completed", lambda c, inst, tf, now=None: CandleSet("5m", candles, "SYN", utcnow()))
    monkeypatch.setattr(pm, "evaluate_instrument", lambda c, inst, now=None: (R(mtf_ok), {}))
    monkeypatch.setattr(pm, "store_snapshot", lambda *a, **k: None)
    return i


def arm(db, i, code, **kw):
    t = engine.create_trade(db, get_account(db, code), i, PlanInput(100, 95, 115, 10_000), trigger="CROSS_ABOVE", idempotency_key=f"{code}-{i.id}", **kw)
    t.created_at = datetime(2026, 10, 26, 3, 30)  # 09:00 IST in naive UTC
    db.commit()
    return t


CROSS = m5([(98, 99, 97, 99), (99, 100.4, 98.9, 100.2), (100.2, 101, 100, 100.8)])


def test_d1_fills_only_when_mtf_aligned(db, monkeypatch):
    i = setup(db, monkeypatch, CROSS, mtf_ok=False)
    t = arm(db, i, "D1_MTF")
    st = pm.monitor(db, client=None, now=DAY.replace(hour=9, minute=40))
    assert t.status == "PENDING_ENTRY" and st["actions"][0]["actions"] == ["BLOCKED"]
    monkeypatch.setattr(pm, "evaluate_instrument", lambda c, inst, now=None: (R(True), {}))
    t.last_candle_ts = None
    pm.monitor(db, client=None, now=DAY.replace(hour=9, minute=40))
    assert t.status == "OPEN" and t.filled_qty > 0


def test_d2_requires_valid_signal(db, monkeypatch):
    i = setup(db, monkeypatch, CROSS)
    sig = Signal(instrument_id=i.id, status="QUALIFIED", validity="INVALIDATED", signal_key="K", invalidated_reason="daily trend broke",
                 valid_until=utcnow() + timedelta(days=2))
    db.add(sig)
    db.flush()
    t = arm(db, i, "D2_MECH", signal_id=sig.id, signal_key="K")
    pm.monitor(db, client=None, now=DAY.replace(hour=9, minute=40))
    assert t.status == "PENDING_ENTRY" and any(e.event == "TRIGGER_BLOCKED" for e in t.events)


def test_overdue_pending_trades_expire(db, monkeypatch):
    i = setup(db, monkeypatch, [])
    t = arm(db, i, "D1_MTF", valid_until=datetime(2026, 10, 1, tzinfo=IST))
    assert pm.expire_overdue(db) == 1 and t.status == "EXPIRED" and get_account(db, "D1_MTF").reserved == 0
