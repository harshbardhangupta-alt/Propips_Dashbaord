"""Paper-trading engine: sizing, validation, cash reservation, fills, exits, P&L, idempotency."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.database.models import Execution, Instrument, PaperTrade
from app.database.repository import get_account
from app.market_data.candles import Candle
from app.paper_trading import engine
from app.paper_trading.charges import estimate_charges
from app.paper_trading.execution import entry_fill, exit_fill
from app.paper_trading.risk_manager import AccountLimits, PlanInput, validate_plan


def lim(**kw):
    base = dict(available_cash=100_000, initial_capital=100_000, risk_pct_per_trade=1.0, max_risk_per_trade=2000, max_allocation_per_trade=50_000,
                max_open_positions=5, max_aggregate_risk_pct=5.0, min_reward_risk=2.0)
    base.update(kw)
    return AccountLimits(**base)


# ------------------------------------------------------------------ risk manager
def test_position_sizing_formula():
    r = validate_plan(PlanInput(entry=100, stop=95, target=115, allocation=20_000), lim())
    # risk budget = min(100000*1% = 1000, 2000) = 1000 -> floor(1000/5) = 200; allocation -> 200
    assert r.ok and r.quantity == 200 and r.planned_risk == 1000 and r.reward_risk == 3.0


def test_allocation_limits_quantity():
    r = validate_plan(PlanInput(100, 95, 115, 5_000), lim())
    assert r.quantity == 50 and r.limiting_factor == "allocation"


def test_user_max_risk_caps_quantity():
    r = validate_plan(PlanInput(100, 95, 115, 20_000, max_risk_amount=250), lim())
    assert r.quantity == 50


@pytest.mark.parametrize("entry,stop,target,alloc,msg", [
    (100, 100, 120, 10_000, "Entry Price > Stop Loss"),
    (100, 105, 120, 10_000, "Entry Price > Stop Loss"),
    (100, 95, 99, 10_000, "Take Profit"),
    (100, 95, 120, 0, "positive"),
    (100, 95, 120, -5, "positive"),
    (100, 95, 120, float("nan"), "positive"),
    (100, 95, 120, 150_000, "exceeds available"),
    (100, 95, 120, 60_000, "maximum per-trade allocation"),
    (100, 95, 105, 10_000, "below the mandatory minimum"),
])
def test_invalid_plans_rejected(entry, stop, target, alloc, msg):
    r = validate_plan(PlanInput(entry, stop, target, alloc), lim())
    assert not r.ok and any(msg in e for e in r.errors), r.errors


def test_d1_rr_warning_close_to_minimum():
    r = validate_plan(PlanInput(100, 95, 110.5, 10_000), lim())
    assert r.ok and r.warnings


def test_max_positions_and_aggregate_risk():
    assert not validate_plan(PlanInput(100, 95, 115, 10_000), lim(open_or_pending_count=5)).ok
    r = validate_plan(PlanInput(100, 95, 115, 10_000), lim(aggregate_open_risk=4_600))
    assert not r.ok and any("Aggregate" in e for e in r.errors)


def test_zero_quantity_rejected():
    r = validate_plan(PlanInput(5000, 3900, 9000, 10_000), lim())
    assert not r.ok and any("quantity is 0" in e for e in r.errors)


# ------------------------------------------------------------------ fill simulation
def C(o, h, l, c, ts=1000.0):
    return Candle(ts, o, h, l, c)


def test_close_above_trigger():
    assert entry_fill("CANDLE_CLOSE_ABOVE", 100, C(99, 101, 98.5, 100.5), C(98, 99.5, 97, 99), 0).reference_price == 100.5
    assert entry_fill("CANDLE_CLOSE_ABOVE", 100, C(99, 101, 98.5, 99.8), C(98, 99.5, 97, 99), 0) is None  # touch, no close


def test_cross_above_gap_fills_at_open():
    f = entry_fill("CROSS_ABOVE", 100, C(102, 103, 101.5, 102.5), C(98, 99.5, 97, 99), 0)
    assert f.reference_price == 102 and "Gap" in f.note
    assert entry_fill("CROSS_ABOVE", 100, C(99, 100, 98, 99.5), C(98, 99.5, 97, 99), 0).reference_price == 100


def test_touch_below_requires_trade_through():
    assert entry_fill("TOUCH_BELOW", 100, C(101, 102, 100, 101), None, 0) is None  # exact touch is not a fill
    f = entry_fill("TOUCH_BELOW", 100, C(101, 102, 99.9, 101), None, 10)
    assert f.price <= 100  # limit never fills above its price


def test_exit_rules_and_conservative_same_candle():
    assert exit_fill(95, 110, C(100, 111, 94, 105), 0).reason == "STOP_LOSS"  # both inside -> stop first
    assert exit_fill(95, 110, C(93, 96, 92, 95), 0).reason == "STOP_LOSS_GAP"
    assert exit_fill(95, 110, C(93, 96, 92, 95), 0).reference_price == 93
    assert exit_fill(95, 110, C(112, 113, 111, 112), 0).reason == "TAKE_PROFIT_GAP"
    assert exit_fill(95, 110, C(100, 110.5, 99, 110), 0).reason == "TAKE_PROFIT"
    assert exit_fill(95, 110, C(100, 105, 96, 101), 0) is None


def test_slippage_is_adverse():
    f = entry_fill("CROSS_ABOVE", 100, C(99, 101, 98, 100.5), C(98, 99, 97, 99), 10)
    assert f.price == 100.1
    x = exit_fill(95, 110, C(100, 111, 99, 110), 10)
    assert x.price == round(110 * 0.999, 2)


def test_charges_estimate_positive():
    assert estimate_charges("BUY", 100_000) > estimate_charges("BUY", 1_000) > 0
    assert estimate_charges("SELL", 100_000) > 0


# ------------------------------------------------------------------ ledger
def inst(db, sym="TEST"):
    i = Instrument(symbol=sym, company_name="Test Ltd", security_id="1", mapping_status="MAPPED")
    db.add(i)
    db.flush()
    return i


def arm(db, code="D1_MTF", sym="TEST", entry=100.0, stop=95.0, target=115.0, alloc=20_000.0, key="k1", trigger="CROSS_ABOVE", **kw):
    acc = get_account(db, code)
    i = db.scalar(select(Instrument).where(Instrument.symbol == sym)) or inst(db, sym)
    t = engine.create_trade(db, acc, i, PlanInput(entry, stop, target, alloc), trigger=trigger, idempotency_key=key, **kw)
    t.created_at = datetime(2026, 10, 23, 3, 0)  # 08:30 IST, before the candles used below
    db.flush()
    return acc, t


def ts(h, m):  # epoch for 2026-10-23 hh:mm IST
    return datetime(2026, 10, 23, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30))).timestamp()


def ok_gate(t, c):
    return True, "ok"


def test_accounts_initialised_independently(db):
    a1, a2 = get_account(db, "D1_MTF"), get_account(db, "D2_MECH")
    assert a1.cash == a2.cash == 100_000 and a1.id != a2.id
    assert a1.min_reward_risk == 2.0 and a2.min_reward_risk == 3.0


def test_cash_reservation_and_release(db):
    acc, t = arm(db)
    assert t.status == "PENDING_ENTRY" and acc.reserved == 20_000
    assert engine.account_summary(db, acc)["available_cash"] == 80_000
    other = get_account(db, "D2_MECH")
    assert other.reserved == 0 and other.cash == 100_000  # independent ledgers
    engine.cancel_trade(db, t)
    assert acc.reserved == 0 and t.status == "CANCELLED"


def test_enabling_does_not_open_position(db):
    acc, t = arm(db)
    assert t.status == "PENDING_ENTRY" and t.filled_qty == 0
    assert db.scalar(select(func.count()).select_from(Execution)) == 0


def test_fill_then_take_profit_pnl(db):
    acc, t = arm(db)
    candles = [C(98, 99, 97, 99, ts(9, 15)), C(99, 100.5, 98.8, 100.2, ts(9, 20)), C(100.2, 116, 100, 115.5, ts(9, 25))]
    acts = engine.process_candles(db, t, candles, ok_gate, "TEST")
    assert acts == ["FILLED", "TAKE_PROFIT"]
    assert t.status == "CLOSED" and t.exit_reason == "TAKE_PROFIT"
    fill = t.entry_price
    assert fill == round(100 * 1.0005, 2)
    assert t.gross_pnl == round((t.exit_price - fill) * t.filled_qty, 2)
    assert t.net_pnl == round(t.gross_pnl - t.charges, 2)
    assert acc.reserved == 0
    assert abs(acc.cash - (100_000 + t.net_pnl)) < 0.05
    assert all(x.simulated for x in t.executions)


def test_stop_loss_exit(db):
    acc, t = arm(db)
    candles = [C(98, 99, 97, 99, ts(9, 15)), C(99, 100.5, 98.8, 100.2, ts(9, 20)), C(100, 100.5, 94, 95, ts(9, 25))]
    engine.process_candles(db, t, candles, ok_gate, "TEST")
    assert t.status == "CLOSED" and t.exit_reason == "STOP_LOSS" and t.net_pnl < 0


def test_entry_and_stop_same_candle_conservative(db):
    acc, t = arm(db)
    candles = [C(98, 99, 97, 99, ts(9, 15)), C(99, 101, 94, 100, ts(9, 20))]
    acts = engine.process_candles(db, t, candles, ok_gate, "TEST")
    assert acts == ["FILLED", "STOP_LOSS"]


def test_gate_blocks_entry(db):
    acc, t = arm(db)
    candles = [C(98, 99, 97, 99, ts(9, 15)), C(99, 101, 98.8, 100.5, ts(9, 20))]
    acts = engine.process_candles(db, t, candles, lambda t, c: (False, "MTF not aligned"), "TEST")
    assert acts == ["BLOCKED"] and t.status == "PENDING_ENTRY"
    assert any(e.event == "TRIGGER_BLOCKED" for e in t.events)


def test_gap_beyond_deviation_skipped_d1_rejected_d2(db):
    acc, t = arm(db)
    gap = [C(98, 99, 97, 99, ts(9, 15)), C(103, 104, 102.5, 103.5, ts(9, 20))]
    assert engine.process_candles(db, t, gap, ok_gate, "TEST", gap_policy="SKIP") == ["SKIPPED_GAP"]
    assert t.status == "PENDING_ENTRY"
    acc2, t2 = arm(db, code="D2_MECH", sym="OTHER", stop=97.0, target=109.0, key="k2")
    assert engine.process_candles(db, t2, gap, ok_gate, "TEST", gap_policy="REJECT") == ["REJECTED_GAP"]
    assert t2.status == "REJECTED" and acc2.reserved == 0


def test_d2_invalidated_below_stop_before_entry(db):
    acc, t = arm(db, code="D2_MECH", stop=97.0, target=109.0)
    candles = [C(98, 99, 97, 99, ts(9, 15)), C(99, 99.5, 96.5, 97.5, ts(9, 20))]
    assert engine.process_candles(db, t, candles, ok_gate, "TEST", invalidate_below_stop=True) == ["INVALIDATED"]
    assert t.status == "EXPIRED"


def test_duplicate_processing_does_not_double_fill(db):
    acc, t = arm(db, target=130.0, stop=95.0)
    candles = [C(98, 99, 97, 99, ts(9, 15)), C(99, 100.5, 98.8, 100.2, ts(9, 20))]
    engine.process_candles(db, t, candles, ok_gate, "TEST")
    engine.process_candles(db, t, candles, ok_gate, "TEST")  # same candles again (e.g. after restart)
    assert db.scalar(select(func.count()).select_from(Execution).where(Execution.trade_id == t.id)) == 1
    assert engine.fill_entry(db, t, entry_fill("CROSS_ABOVE", 100, candles[1], candles[0], 0), "TEST") is False


def test_idempotency_key_and_one_active_trade_per_stock(db):
    acc, t = arm(db, key="same")
    acc, t2 = arm(db, key="same")
    assert t.id == t2.id
    with pytest.raises(engine.TradeRejected) as e:
        arm(db, key="different")
    assert "already has an active paper trade" in str(e.value)


def test_duplicate_signal_prevented(db):
    arm(db, code="D2_MECH", stop=97.0, target=109.0, key="a", signal_key="SIG1")
    with pytest.raises(engine.TradeRejected) as e:
        arm(db, code="D2_MECH", sym="OTHER", stop=97.0, target=109.0, key="b", signal_key="SIG1")
    assert "Signal already used" in str(e.value)


def test_rejected_trade_is_persisted(db):
    with pytest.raises(engine.TradeRejected) as e:
        arm(db, alloc=500_000)
    assert e.value.trade.status == "REJECTED" and e.value.trade.reserved_amount == 0
    assert get_account(db, "D1_MTF").reserved == 0


def test_disable_auto_entry_keeps_open_position(db):
    acc, t = arm(db, target=130.0)
    engine.process_candles(db, t, [C(98, 99, 97, 99, ts(9, 15)), C(99, 100.5, 98.8, 100.2, ts(9, 20))], ok_gate, "TEST")
    assert t.status == "OPEN"
    engine.disable_auto_entry(db, t)
    assert t.status == "OPEN" and not t.auto_entry_enabled
    engine.process_candles(db, t, [C(100, 100.5, 94, 95, ts(9, 25))], ok_gate, "TEST")
    assert t.status == "CLOSED"  # still monitored for stop


def test_pause_and_resume_pending(db):
    acc, t = arm(db)
    engine.disable_auto_entry(db, t)
    assert t.status == "CONFIGURED" and acc.reserved == 0
    engine.enable_auto_entry(db, t)
    assert t.status == "PENDING_ENTRY" and acc.reserved == 20_000


def test_expiry_releases_cash(db):
    acc, t = arm(db, valid_until=datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc))  # 09:30 IST
    candles = [C(98, 99, 97, 99, ts(9, 30)), C(99, 99.5, 98, 99, ts(9, 35))]
    assert engine.process_candles(db, t, candles, ok_gate, "TEST") == ["EXPIRED"]
    assert acc.reserved == 0


def test_manual_exit_paper_only(db):
    acc, t = arm(db, target=130.0)
    engine.process_candles(db, t, [C(98, 99, 97, 99, ts(9, 15)), C(99, 100.5, 98.8, 100.2, ts(9, 20))], ok_gate, "TEST")
    engine.manual_exit(db, t, 104.0, "TEST_QUOTE")
    assert t.status == "CLOSED" and t.exit_reason == "MANUAL_EXIT" and t.gross_pnl > 0
    with pytest.raises(engine.TradeRejected):
        engine.manual_exit(db, t, None, "x")


def test_reset_requires_no_open_positions(db):
    acc, t = arm(db, target=130.0)
    engine.process_candles(db, t, [C(98, 99, 97, 99, ts(9, 15)), C(99, 100.5, 98.8, 100.2, ts(9, 20))], ok_gate, "TEST")
    with pytest.raises(engine.TradeRejected):
        engine.reset_account(db, acc)
    engine.manual_exit(db, t, 101, "TEST")
    engine.reset_account(db, acc, 250_000)
    assert acc.cash == 250_000 and acc.realized_gross == 0


def test_persistence_after_restart(tmp_path):
    from app.database import session as sm
    from app.database.models import Base

    url = f"sqlite:///{tmp_path}/restart.db"
    e1 = sm.init_engine(url)
    Base.metadata.create_all(e1)
    s = sm.SessionLocal()
    engine.ensure_accounts(s)
    acc, t = arm(s)
    s.commit()
    tid = t.id
    s.close()
    e1.dispose()
    sm.init_engine(url)  # "restart"
    s2 = sm.SessionLocal()
    t2 = s2.get(PaperTrade, tid)
    assert t2.status == "PENDING_ENTRY" and get_account(s2, "D1_MTF").reserved == 20_000
    s2.close()


def test_strategy_attribution(db):
    acc, t = arm(db)
    acc2, t2 = arm(db, code="D2_MECH", sym="OTHER", stop=97.0, target=109.0, key="x")
    assert t.strategy == "DASHBOARD1_MTF" and t2.strategy == "DASHBOARD2_MECHANICAL"
    assert t.account_id != t2.account_id
