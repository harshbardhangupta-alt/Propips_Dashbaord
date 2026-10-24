"""End-to-end API tests through FastAPI (mocked Dhan/OpenAI, real SQLite + Alembic migration)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.database import session as sm
from tests.fakes import FakeDhan, constituents_csv, fake_get_completed, scrip_master_csv


@pytest.fixture()
def api(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/api.db"
    monkeypatch.setattr(get_settings(), "database_url", url)
    sm.init_engine(url)
    from app.main import create_app
    from app.market_data.cache import candle_cache

    candle_cache.clear()
    with TestClient(create_app()) as c:
        yield c
    sm.get_engine().dispose()


def test_paper_only_banner_and_health(api):
    h = api.get("/api/health").json()
    assert h["paper_trading_only"] and h["banner"] == "PAPER TRADING ONLY — NO LIVE ORDERS"
    st = api.get("/api/system/status").json()
    assert st["live_trading_available"] is False and all("order" not in e for e in st["allowed_dhan_endpoints"])


def test_default_accounts(api):
    accs = {a["code"]: a for a in api.get("/api/paper/accounts").json()["accounts"]}
    assert accs["D1_MTF"]["available_cash"] == 100_000 and accs["D2_MECH"]["available_cash"] == 100_000


def test_dhan_settings_masking_and_status(api, monkeypatch):
    from app.services import settings_service

    token = "eyJhbGciOiJIUzUxMiJ9.very-secret-token-abcdefgh"
    r = api.put("/api/settings/dhan", json={"client_id": "1000000001", "access_token": token}).json()
    assert r["client_id"] == "1000000001" and token not in str(r) and r["access_token_masked"].endswith("efgh")
    assert r["status"] == "UNTESTED"  # saving != connected
    # Client ID is fixed until explicit confirmation
    assert api.put("/api/settings/dhan", json={"client_id": "2000000002"}).status_code == 409
    assert api.put("/api/settings/dhan", json={"client_id": "2000000002", "confirm_replace_client_id": True}).status_code == 200
    monkeypatch.setattr(settings_service, "DhanClient", lambda creds: FakeDhan())
    t = api.post("/api/settings/dhan/test").json()
    assert t["status"] == "CONNECTED" and token not in str(t)
    monkeypatch.setattr(settings_service, "DhanClient", lambda creds: FakeDhan(fail_profile="AUTH_FAILED"))
    assert api.post("/api/settings/dhan/test").json()["status"] == "AUTH_FAILED"
    assert api.delete("/api/settings/dhan").status_code == 400
    assert api.delete("/api/settings/dhan?confirm=true").json()["status"] == "NOT_CONFIGURED"
    assert token not in api.get("/api/system/status").text


def test_openai_settings_and_disabled_explanations(api):
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    r = api.put("/api/settings/openai", json={"api_key": key, "model": "gpt-5-mini", "enabled": False}).json()
    assert key not in str(r) and r["api_key_masked"].endswith("3456") and r["model"] == "gpt-5-mini"
    assert api.put("/api/settings/openai", json={"model": "bad model!"}).status_code == 422


def _seed(api, monkeypatch, symbols=("GOOD", "WEAK")):
    files = {"file": ("scrip.csv", scrip_master_csv(symbols), "text/csv")}
    assert api.post("/api/settings/scrip-master/upload", files=files).status_code == 200
    for u in ("NIFTY100", "NIFTY250"):
        r = api.post(f"/api/settings/universe/{u}/upload", files={"file": ("c.csv", constituents_csv(symbols), "text/csv")})
        assert r.status_code == 200, r.text
    api.put("/api/settings/dhan", json={"client_id": "1000000001", "access_token": "eyJ-token-1234567890"})
    from app.services import scan_service, settings_service

    now, gc = fake_get_completed()
    monkeypatch.setattr(settings_service, "DhanClient", lambda creds: FakeDhan())
    monkeypatch.setattr(scan_service.mds, "get_completed", gc)
    return now


def test_dashboard1_preview_and_create(api, monkeypatch):
    _seed(api, monkeypatch)
    stocks = api.get("/api/d1/stocks").json()
    assert stocks["count"] == 2 and stocks["stocks"][0]["auto_trade_status"] == "NOT_CONFIGURED"
    bad = api.post("/api/d1/preview", json={"symbol": "GOOD", "allocation": 10000, "entry": 100, "stop_loss": 101, "take_profit": 110}).json()
    assert not bad["plan"]["ok"]
    low_rr = api.post("/api/d1/preview", json={"symbol": "GOOD", "allocation": 10000, "entry": 100, "stop_loss": 95, "take_profit": 105}).json()
    assert not low_rr["plan"]["ok"] and any("1:2" in e for e in low_rr["plan"]["errors"])
    body = {"symbol": "GOOD", "allocation": 10000, "entry": 100, "stop_loss": 95, "take_profit": 112}
    ok = api.post("/api/d1/preview", json=body).json()
    assert ok["plan"]["ok"] and ok["plan"]["quantity"] == 100 and ok["paper_only"]
    assert api.post("/api/d1/trades", json=body).status_code == 400  # confirmation required
    r = api.post("/api/d1/trades", json={**body, "confirm": True, "client_request_id": "abc"})
    assert r.status_code == 200 and r.json()["trade"]["status"] == "PENDING_ENTRY"
    again = api.post("/api/d1/trades", json={**body, "confirm": True, "client_request_id": "abc"})
    assert again.json()["trade"]["id"] == r.json()["trade"]["id"]  # idempotent
    dup = api.post("/api/d1/trades", json={**body, "confirm": True, "client_request_id": "other"})
    assert dup.status_code == 422
    accs = {a["code"]: a for a in api.get("/api/paper/accounts").json()["accounts"]}
    assert accs["D1_MTF"]["reserved"] == 10000 and accs["D2_MECH"]["reserved"] == 0
    tid = r.json()["trade"]["id"]
    assert api.post(f"/api/paper/trades/{tid}/disable-auto").json()["status"] == "CONFIGURED"
    assert api.post(f"/api/paper/trades/{tid}/enable-auto").json()["status"] == "PENDING_ENTRY"
    assert api.post(f"/api/paper/trades/{tid}/cancel").json()["status"] == "CANCELLED"
    book = api.get("/api/paper/trades?status=CANCELLED,REJECTED").json()
    assert {t["status"] for t in book["trades"]} == {"CANCELLED", "REJECTED"}


def test_dashboard2_flow(api, monkeypatch):
    _seed(api, monkeypatch)
    from app.services.scan_service import scan_manager

    now, gc = fake_get_completed()
    res = scan_manager.run("MANUAL", now=now)
    assert res["status"] == "SUCCESS", res
    sigs = api.get("/api/d2/signals").json()["signals"]
    assert len(sigs) == 1 and sigs[0]["symbol"] == "GOOD" and sigs[0]["grade"] in ("A", "A+")
    rej = api.get("/api/d2/signals?view=rejected").json()["signals"]
    assert rej and rej[0]["rejection_reasons"]
    sid = sigs[0]["id"]
    pv = api.post("/api/d2/preview", json={"signal_id": sid, "allocation": 20000}).json()
    assert pv["plan"]["ok"] and pv["plan"]["reward_risk"] >= 3
    # Override below 1:3 is rejected
    bad = api.post("/api/d2/preview", json={"signal_id": sid, "allocation": 20000, "override": {"entry": 144.95, "stop_loss": 140, "target": 150}}).json()
    assert not bad["plan"]["ok"]
    r = api.post("/api/d2/trades", json={"signal_id": sid, "allocation": 20000, "confirm": True})
    assert r.status_code == 200 and r.json()["trade"]["entry_trigger"] == "CROSS_ABOVE"
    r2 = api.post("/api/d2/trades", json={"signal_id": sid, "allocation": 20000, "confirm": True})
    assert r2.json()["trade"]["id"] == r.json()["trade"]["id"]  # same signal -> same trade
    # D2 min RR cannot be lowered below 3
    assert api.put("/api/paper/accounts/D2_MECH/limits", json={"min_reward_risk": 2.0}).status_code == 400
    st = api.get("/api/d2/scanner/status").json()
    assert st["last_successful"]["status"] == "SUCCESS" and st["auto_scan_enabled"] is False
    assert api.post("/api/d2/scanner/start").json()["auto_scan_enabled"] is True
    assert api.post("/api/d2/scanner/stop").json()["auto_scan_enabled"] is False


def test_manual_exit_and_reset(api, monkeypatch):
    _seed(api, monkeypatch)
    from app.database.models import PaperTrade, Quote, utcnow
    from app.paper_trading.execution import Fill
    from app.paper_trading import engine

    body = {"symbol": "GOOD", "allocation": 10000, "entry": 100, "stop_loss": 95, "take_profit": 112, "confirm": True}
    tid = api.post("/api/d1/trades", json=body).json()["trade"]["id"]
    s = sm.SessionLocal()
    t = s.get(PaperTrade, tid)
    engine.fill_entry(s, t, Fill(100, 100.05, "ENTRY", 0), "TEST")
    s.merge(Quote(instrument_id=t.instrument_id, ltp=104.0, prev_close=103.0, fetched_at=utcnow()))
    s.commit()
    s.close()
    assert api.post("/api/paper/accounts/D1_MTF/reset", json={"confirm": "RESET"}).status_code == 409  # open position
    assert api.post(f"/api/paper/trades/{tid}/manual-exit", json={}).status_code == 400
    r = api.post(f"/api/paper/trades/{tid}/manual-exit", json={"confirm": True}).json()
    assert r["status"] == "CLOSED" and r["exit_reason"] == "MANUAL_EXIT" and r["executions"][-1]["simulated"]
    assert api.post("/api/paper/accounts/D1_MTF/reset", json={"confirm": "nope"}).status_code == 400
    assert api.post("/api/paper/accounts/D1_MTF/reset", json={"confirm": "RESET"}).json()["cash"] == 100_000


def test_input_validation(api):
    assert api.post("/api/d1/preview", json={"symbol": "../etc", "allocation": 1, "entry": 1, "stop_loss": 0.5, "take_profit": 2}).status_code in (400, 404)
    assert api.post("/api/d1/preview", json={"symbol": "X", "allocation": -1, "entry": 1, "stop_loss": 0.5, "take_profit": 2}).status_code == 422
    assert api.get("/api/paper/trades?status=DROP TABLE").status_code == 400
    assert api.get("/api/system/chart/ZZZ?tf=1W").status_code == 400


def test_chart_reports_real_errors(api, monkeypatch):
    _seed(api, monkeypatch)
    r = api.get("/api/system/chart/BROKEN?tf=1D")
    assert r.status_code == 404  # not in universe
    from app.services import market_data_service as mds
    from app.integrations.dhan_client import DhanError

    def fail(*a, **k):
        raise DhanError("NETWORK_ERROR", "mocked")

    monkeypatch.setattr(mds, "get_completed", fail)
    c = api.get("/api/system/chart/GOOD?tf=1D").json()
    assert c["available"] is False and c["candles"] == [] and c["error"]["status"] == "NETWORK_ERROR"
    assert c["tradingview_symbol"] == "NSE:GOOD"
