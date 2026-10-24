"""Parsing of official NSE index-constituent CSVs and the Dhan scrip master."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

# Official index constituent files published by NSE Indices Ltd.
NSE_INDEX_SOURCES = {
    "NIFTY100": [
        "https://niftyindices.com/IndexConstituent/ind_nifty100list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    ],
    # "Nifty 250" is interpreted as the official NIFTY LargeMidcap 250 index
    # (Nifty 100 + Nifty Midcap 150). See README "Strategy interpretation notes".
    "NIFTY250": [
        "https://niftyindices.com/IndexConstituent/ind_niftylargemidcap250list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_niftylargemidcap250list.csv",
    ],
}
EXPECTED_SIZE = {"NIFTY100": 100, "NIFTY250": 250}
# Index names used by NSE's own website API (tried when the CSV hosts refuse the request).
NSE_API_INDEX = {"NIFTY100": "NIFTY 100", "NIFTY250": "NIFTY LARGEMIDCAP 250"}


@dataclass
class Constituent:
    symbol: str
    company_name: str
    industry: str | None
    series: str | None
    isin: str | None


@dataclass
class ScripRow:
    symbol: str
    security_id: str
    series: str | None
    lot_size: int
    tick_size: float
    name: str | None
    isin: str | None


def _norm(h: str) -> str:
    return h.strip().lower().replace(" ", "_")


def parse_constituents_csv(text: str) -> list[Constituent]:
    """Parse NSE constituent CSV: Company Name, Industry, Symbol, Series, ISIN Code."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        raise ValueError("Empty CSV")
    fields = {_norm(f): f for f in reader.fieldnames}
    if "symbol" not in fields:
        raise ValueError(f"CSV has no 'Symbol' column (columns: {reader.fieldnames})")
    out: list[Constituent] = []
    seen = set()
    for row in reader:
        sym = (row.get(fields["symbol"]) or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(
            Constituent(
                symbol=sym,
                company_name=(row.get(fields.get("company_name", ""), "") or "").strip(),
                industry=(row.get(fields.get("industry", ""), "") or "").strip() or None,
                series=(row.get(fields.get("series", ""), "") or "").strip() or None,
                isin=(row.get(fields.get("isin_code", ""), "") or "").strip() or None,
            )
        )
    return out


def parse_scrip_master(text: str) -> dict[str, ScripRow]:
    """Parse Dhan scrip master (compact or detailed) -> NSE cash-equity rows keyed by symbol.

    Compact columns: SEM_EXM_EXCH_ID, SEM_SEGMENT, SEM_SMST_SECURITY_ID, SEM_INSTRUMENT_NAME,
    SEM_TRADING_SYMBOL, SEM_LOT_UNITS, SEM_TICK_SIZE, SEM_SERIES, SM_SYMBOL_NAME.
    Detailed columns: EXCH_ID, SEGMENT, SECURITY_ID, ISIN, INSTRUMENT, UNDERLYING_SYMBOL,
    SYMBOL_NAME, SERIES, LOT_SIZE, TICK_SIZE.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        raise ValueError("Empty scrip master")
    f = {h.strip().upper(): h for h in reader.fieldnames}

    def col(row, *names):
        for n in names:
            if n in f:
                v = row.get(f[n])
                if v is not None:
                    return v.strip()
        return None

    out: dict[str, ScripRow] = {}
    for row in reader:
        exch = col(row, "SEM_EXM_EXCH_ID", "EXCH_ID")
        seg = col(row, "SEM_SEGMENT", "SEGMENT")
        inst = col(row, "SEM_INSTRUMENT_NAME", "INSTRUMENT")
        if exch != "NSE" or seg != "E" or (inst and inst.upper() != "EQUITY"):
            continue
        series = col(row, "SEM_SERIES", "SERIES")
        sym = (col(row, "SEM_TRADING_SYMBOL", "UNDERLYING_SYMBOL", "SYMBOL_NAME") or "").upper()
        sid = col(row, "SEM_SMST_SECURITY_ID", "SECURITY_ID")
        if not sym or not sid:
            continue
        # Prefer the EQ series where a symbol appears in several series.
        if sym in out and out[sym].series == "EQ" and series != "EQ":
            continue
        try:
            lot = int(float(col(row, "SEM_LOT_UNITS", "LOT_SIZE") or 1))
        except ValueError:
            lot = 1
        try:
            tick = float(col(row, "SEM_TICK_SIZE", "TICK_SIZE") or 0.05)
        except ValueError:
            tick = 0.05
        # Dhan's scrip master expresses equity tick size in paise (e.g. 5.0000 = Rs 0.05).
        if tick >= 1:
            tick = tick / 100.0
        out[sym] = ScripRow(
            symbol=sym,
            security_id=str(int(float(sid))) if sid.replace(".", "", 1).isdigit() else sid,
            series=series,
            lot_size=max(1, lot),
            tick_size=tick if tick > 0 else 0.05,
            name=col(row, "SM_SYMBOL_NAME", "DISPLAY_NAME", "SYMBOL_NAME"),
            isin=col(row, "ISIN"),
        )
    return out


def parse_nse_api_json(body: dict, index_name: str) -> list[Constituent]:
    """Parse https://www.nseindia.com/api/equity-stockIndices?index=... (first row is the index itself)."""
    out: list[Constituent] = []
    seen = set()
    for row in body.get("data", []):
        sym = str(row.get("symbol", "")).strip().upper()
        if not sym or sym == index_name.upper() or sym in seen:
            continue
        meta = row.get("meta") or {}
        if not meta and row.get("priority") == 1:
            continue
        seen.add(sym)
        out.append(Constituent(symbol=sym, company_name=str(meta.get("companyName") or "").strip(),
                               industry=(meta.get("industry") or None), series=row.get("series") or "EQ", isin=meta.get("isin") or None))
    return out
