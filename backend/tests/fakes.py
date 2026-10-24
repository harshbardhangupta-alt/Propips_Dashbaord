"""Mocks for external services (SYNTHETIC; tests only)."""
from __future__ import annotations

from app.integrations.dhan_client import DhanError, DhanStatus
from app.services.market_data_service import CandleSet
from app.database.models import utcnow
from tests.synthetic import daily_series, mech_scenario

NIFTY_CSV_HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def constituents_csv(symbols):
    return NIFTY_CSV_HEADER + "".join(f"{s} Ltd,Test Industry,{s},EQ,INE{i:07d}01\n" for i, s in enumerate(symbols))


def scrip_master_csv(symbols):
    rows = ["SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME"]
    for i, s in enumerate(symbols, start=100):
        rows.append(f"NSE,E,{i},EQUITY,0,{s},1.0,{s},,,,5.0000,,ES,EQ,{s} LIMITED")
        rows.append(f"BSE,E,{i + 5000},EQUITY,0,{s},1.0,{s},,,,5.0000,,ES,A,{s} LIMITED")
    rows.append("NSE,D,99999,FUTSTK,0,FOO-FUT,50,FOO,,,,5.0000,M,FUT,,FOO")
    return "\n".join(rows) + "\n"


class FakeDhan:
    def __init__(self, fail_profile=None):
        self.fail_profile = fail_profile

    def profile(self):
        if self.fail_profile:
            raise DhanError(self.fail_profile, "mocked failure")
        return {"dhanClientId": "1000000001", "tokenValidity": "24/10/2026 18:00", "dataPlan": "Active"}

    def ltp(self, ids):
        return {i: {"last_price": 144.3} for i in ids}

    def ohlc(self, ids):
        return {i: {"last_price": 144.3, "ohlc": {"open": 143.0, "high": 145.0, "low": 141.0, "close": 142.0}} for i in ids}


def fake_get_completed(now_override=None):
    now, daily, h4, h1 = mech_scenario()

    def get_completed(client, inst, tf, now=None):
        if inst.symbol == "BROKEN":
            raise DhanError(DhanStatus.MARKET_DATA_UNAVAILABLE, "mocked: no data")
        if inst.symbol == "GOOD":
            cs = {"1D": daily, "4H": h4, "1H": h1}.get(tf, h1)
        else:
            cs = {"1D": daily_series(now.date() if now else daily[-1].dt.date(), 120, 200, 140), "4H": h4, "1H": h1}.get(tf, h1)
        return CandleSet(tf, cs, "SYNTHETIC_TEST", utcnow())

    return now, get_completed
