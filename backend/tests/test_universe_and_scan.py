"""Universe sync, instrument mapping and the Dashboard 2 scanner with mocked Dhan data."""
import threading

import pytest
from sqlalchemy import func, select

from app.database.models import Instrument, ScanRun, Signal
from app.market_data.instruments import parse_constituents_csv, parse_scrip_master
from app.services import scan_service as ss
from app.services import universe_service as us
from tests.fakes import FakeDhan, constituents_csv, fake_get_completed, scrip_master_csv


def test_parse_constituents_and_scrip_master():
    cons = parse_constituents_csv(constituents_csv(["AAA", "BBB", "AAA"]))
    assert [c.symbol for c in cons] == ["AAA", "BBB"] and cons[0].isin
    rows = parse_scrip_master(scrip_master_csv(["AAA", "M&M"]))
    assert set(rows) == {"AAA", "M&M"} and rows["AAA"].security_id == "100" and rows["AAA"].tick_size == 0.05
    with pytest.raises(ValueError):
        parse_constituents_csv("foo,bar\n1,2\n")


def test_sync_universe_mapping_and_missing(db):
    us.sync_scrip_master(db, scrip_master_csv(["AAA", "BBB"]), "test")
    res = us.sync_universe(db, "NIFTY100", constituents_csv(["AAA", "BBB", "ZZZ"]), "test")
    assert res["count"] == 3 and res["warnings"]  # not 100 constituents -> warning, never padded
    z = db.scalar(select(Instrument).where(Instrument.symbol == "ZZZ"))
    assert z.mapping_status == "MISSING_IN_SCRIP_MASTER" and z.security_id is None
    assert len(us.members(db, "NIFTY100", mapped_only=True)) == 2
    # removal is detected on the next sync
    res2 = us.sync_universe(db, "NIFTY100", constituents_csv(["AAA"]), "test")
    assert res2["removed"] == 2 and len(us.members(db, "NIFTY100")) == 1


def test_universes_are_separate(db):
    us.sync_universe(db, "NIFTY100", constituents_csv(["AAA"]), "t")
    us.sync_universe(db, "NIFTY250", constituents_csv(["AAA", "BBB"]), "t")
    assert len(us.members(db, "NIFTY100")) == 1 and len(us.members(db, "NIFTY250")) == 2


def test_failed_download_is_recorded(db, monkeypatch):
    import httpx

    def boom(req):
        raise httpx.ConnectError("blocked")

    with pytest.raises(us.UniverseError):
        us.download_constituents("NIFTY100", transport=httpx.MockTransport(boom))


def _setup_scan(db, monkeypatch, symbols=("GOOD", "WEAK", "BROKEN", "NOMAP")):
    us.sync_scrip_master(db, scrip_master_csv([s for s in symbols if s != "NOMAP"]), "t")
    us.sync_universe(db, "NIFTY250", constituents_csv(symbols), "t")
    now, gc = fake_get_completed()
    monkeypatch.setattr(ss, "get_dhan_client", lambda db: FakeDhan())
    monkeypatch.setattr(ss.mds, "get_completed", gc)
    return now


def test_scan_partial_status_and_signals(db, monkeypatch):
    now = _setup_scan(db, monkeypatch)
    res = ss.ScanManager().run("MANUAL", now=now)
    assert res["status"] == "PARTIAL"  # one data error + one unmapped instrument
    run = db.get(ScanRun, res["run_id"])
    db.refresh(run)
    assert run.scanned == 4 and run.qualified == 1 and run.rejected == 1 and run.errors == 1 and run.unavailable == 1
    good = db.scalar(select(Signal).join(Instrument).where(Instrument.symbol == "GOOD", Signal.is_latest.is_(True)))
    assert good.status == "QUALIFIED" and good.entry == 144.95 and good.suggested_qty >= 1
    weak = db.scalar(select(Signal).join(Instrument).where(Instrument.symbol == "WEAK", Signal.is_latest.is_(True)))
    assert weak.status == "REJECTED" and any("Rule A" in r for r in weak.rejection_reasons)


def test_scan_success_when_all_ok(db, monkeypatch):
    now = _setup_scan(db, monkeypatch, ("GOOD", "WEAK"))
    assert ss.ScanManager().run("SCHEDULED", now=now)["status"] == "SUCCESS"


def test_repeat_scans_do_not_duplicate_signals(db, monkeypatch):
    now = _setup_scan(db, monkeypatch, ("GOOD",))
    m = ss.ScanManager()
    m.run("SCHEDULED", now=now)
    m.run("SCHEDULED", now=now)
    db.expire_all()
    n = db.scalar(select(func.count()).select_from(Signal).where(Signal.status == "QUALIFIED"))
    assert n == 1
    s = db.scalar(select(Signal).where(Signal.status == "QUALIFIED"))
    assert s.is_new is False  # seen again in the second scan


def test_after_market_scan_labelled(db, monkeypatch):
    now = _setup_scan(db, monkeypatch, ("GOOD",))
    res = ss.ScanManager().run("AFTER_MARKET", now=now)
    run = db.get(ScanRun, res["run_id"])
    db.refresh(run)
    assert run.label == "AFTER-MARKET SCAN — NOT LIVE MARKET ACTIVITY"
    s = db.scalar(select(Signal).where(Signal.status == "QUALIFIED"))
    db.refresh(s)
    assert s.after_market


def test_scan_fails_without_credentials(db):
    res = ss.ScanManager().run("MANUAL")
    assert res["status"] == "FAILED" and "NOT_CONFIGURED" in res["message"]


def test_scan_fails_on_empty_universe(db, monkeypatch):
    monkeypatch.setattr(ss, "get_dhan_client", lambda db: FakeDhan())
    assert ss.ScanManager().run("MANUAL")["status"] == "FAILED"


def test_no_concurrent_scans_and_cancel(db, monkeypatch):
    now = _setup_scan(db, monkeypatch, ("GOOD", "WEAK"))
    m = ss.ScanManager()
    started, release = threading.Event(), threading.Event()
    orig = ss.mds.get_completed

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return orig(*a, **k)

    monkeypatch.setattr(ss.mds, "get_completed", slow)
    out = {}
    th = threading.Thread(target=lambda: out.update(m.run("MANUAL", now=now)))
    th.start()
    started.wait(5)
    assert m.run("MANUAL")["status"] == "SKIPPED"
    assert m.cancel() is True
    release.set()
    th.join(10)
    assert out["status"] == "CANCELLED"
    assert not m.running


def test_signal_invalidated_when_setup_breaks(db, monkeypatch):
    from app.services.signal_service import signal_entry_gate

    now = _setup_scan(db, monkeypatch, ("GOOD",))
    m = ss.ScanManager()
    m.run("MANUAL", now=now)
    sig = db.scalar(select(Signal).where(Signal.status == "QUALIFIED"))
    assert signal_entry_gate(db, sig.id)[0]
    # Next scan sees a broken daily trend for GOOD with the same impulse/confirmation.
    from tests.synthetic import daily_series, mech_scenario

    n, daily, h4, h1 = mech_scenario()
    from app.services.market_data_service import CandleSet
    from app.database.models import utcnow

    monkeypatch.setattr(ss.mds, "get_completed", lambda c, i, tf, now=None: CandleSet(tf, {"1D": daily_series(n.date(), 120, 200, 140), "4H": h4}.get(tf, h1), "SYN", utcnow()))
    m.run("MANUAL", now=now)
    db.expire_all()
    sig = db.get(Signal, sig.id)
    assert sig.validity == "INVALIDATED" and not signal_entry_gate(db, sig.id)[0]
