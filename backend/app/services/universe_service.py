"""Nifty 100 / Nifty 250 (LargeMidcap 250) universe and Dhan instrument mapping.

Constituents are fetched AUTOMATICALLY from official NSE sources (niftyindices.com CSV,
NSE archive CSV, then NSE's website JSON API). Nothing is hard-coded or invented.
Instrument ids come from Dhan's public scrip master, also downloaded automatically.
``ensure_universes`` runs at startup and every 30 minutes; it only downloads what is missing
or older than its refresh interval, so failures are retried automatically.
"""
from __future__ import annotations

import json
import threading
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import iso
from app.database.models import Instrument, UniverseMember, UniverseRefresh, utcnow
from app.database.repository import audit
from app.integrations.dhan_client import SCRIP_MASTER_COMPACT_URL, DhanError, download_scrip_master
from app.market_data.instruments import (
    EXPECTED_SIZE,
    NSE_API_INDEX,
    NSE_INDEX_SOURCES,
    Constituent,
    ScripRow,
    parse_constituents_csv,
    parse_nse_api_json,
    parse_scrip_master,
)

UNIVERSES = ("NIFTY100", "NIFTY250")
UNIVERSE_LABEL = {"NIFTY100": "Nifty 100", "NIFTY250": "Nifty LargeMidcap 250 (\"Nifty 250\")"}


class UniverseError(Exception):
    pass


def _scrip_cache_path():
    return get_settings().data_dir / "scrip_master_nse_eq.json"


def load_scrip_cache() -> dict[str, ScripRow]:
    p = _scrip_cache_path()
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {k: ScripRow(**v) for k, v in raw.get("rows", {}).items()}


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,application/json,text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def download_constituents(universe: str, transport: httpx.BaseTransport | None = None) -> tuple[list[Constituent], str]:
    """Try every official source in turn; return (constituents, source_url)."""
    errors = []
    with httpx.Client(timeout=30, headers=BROWSER_HEADERS, transport=transport, follow_redirects=True) as c:
        for url in NSE_INDEX_SOURCES[universe]:
            try:
                r = c.get(url)
                r.raise_for_status()
                if "symbol" not in r.text[:500].lower():
                    raise UniverseError("response is not a constituent CSV")
                return parse_constituents_csv(r.text), url
            except Exception as exc:  # noqa: BLE001 - report every source failure
                errors.append(f"{url}: {exc}")
        # NSE website API needs session cookies from the home page first.
        api = f"https://www.nseindia.com/api/equity-stockIndices?index={NSE_API_INDEX[universe].replace(' ', '%20')}"
        try:
            c.get("https://www.nseindia.com/", headers={"Accept": "text/html"})
            r = c.get(api, headers={"Accept": "application/json", "Referer": "https://www.nseindia.com/market-data/live-equity-market"})
            r.raise_for_status()
            cons = parse_nse_api_json(r.json(), NSE_API_INDEX[universe])
            if not cons:
                raise UniverseError("NSE API returned no constituents")
            return cons, api
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{api}: {exc}")
    raise UniverseError("Could not fetch the official constituent list from any NSE source. " + " | ".join(errors))


def map_instruments(db: Session, rows: dict[str, ScripRow] | None = None) -> dict:
    rows = rows if rows is not None else load_scrip_cache()
    by_isin = {r.isin: r for r in rows.values() if r.isin}
    mapped = missing = 0
    for inst in db.scalars(select(Instrument)):
        r = rows.get(inst.symbol)
        note = None
        if r is None and inst.isin and inst.isin in by_isin:
            r = by_isin[inst.isin]
            note = f"Matched by ISIN; Dhan trading symbol is {r.symbol} (possible rename)"
        if r is None:
            if rows:
                inst.mapping_status = "MISSING_IN_SCRIP_MASTER"
                inst.mapping_note = "Symbol/ISIN not found among NSE cash-equity rows of the Dhan scrip master"
                inst.security_id = None
                missing += 1
            continue
        if inst.isin and r.isin and inst.isin != r.isin:
            note = f"ISIN mismatch (NSE {inst.isin} vs Dhan {r.isin}) — verify"
        inst.security_id = r.security_id
        inst.series = r.series
        inst.lot_size = r.lot_size
        inst.tick_size = r.tick_size
        inst.mapping_status = "MAPPED"
        inst.mapping_note = note
        inst.mapped_at = utcnow()
        mapped += 1
    return {"mapped": mapped, "missing": missing}


def sync_scrip_master(db: Session, csv_text: str | None = None, source: str | None = None) -> dict:
    try:
        if csv_text is None:
            csv_text = download_scrip_master()
            source = SCRIP_MASTER_COMPACT_URL
        rows = parse_scrip_master(csv_text)
        if not rows:
            raise UniverseError("Scrip master contained no NSE cash-equity rows")
    except (DhanError, UniverseError, ValueError) as exc:
        msg = getattr(exc, "message", str(exc))
        db.add(UniverseRefresh(universe="SCRIP_MASTER", source=source or SCRIP_MASTER_COMPACT_URL, status="FAILED", message=msg))
        audit(db, "ERROR", "universe", f"Scrip master sync failed: {msg}")
        db.commit()
        raise UniverseError(msg) from exc
    _scrip_cache_path().write_text(json.dumps({"source": source, "saved_at": iso(utcnow()), "rows": {k: v.__dict__ for k, v in rows.items()}}), encoding="utf-8")
    res = map_instruments(db, rows)
    db.add(UniverseRefresh(universe="SCRIP_MASTER", source=source or "upload", status="SUCCESS", count=len(rows),
                           message=f"{len(rows)} NSE equity rows; mapped {res['mapped']}, missing {res['missing']}"))
    audit(db, "INFO", "universe", f"Scrip master synced ({len(rows)} NSE equity rows)")
    db.commit()
    return {"rows": len(rows), **res}


def sync_universe(db: Session, universe: str, csv_text: str | None = None, source: str | None = None) -> dict:
    if universe not in UNIVERSES:
        raise UniverseError(f"Unknown universe {universe}")
    try:
        if csv_text is None:
            cons, source = download_constituents(universe)
        else:
            cons = parse_constituents_csv(csv_text)
        if not cons:
            raise UniverseError("Constituent file has no rows")
    except (UniverseError, ValueError) as exc:
        db.add(UniverseRefresh(universe=universe, source=source or "download", status="FAILED", message=str(exc)))
        audit(db, "ERROR", "universe", f"{universe} sync failed: {exc}")
        db.commit()
        raise UniverseError(str(exc)) from exc
    expected = EXPECTED_SIZE[universe]
    warnings = []
    if len(cons) != expected:
        warnings.append(f"File lists {len(cons)} constituents; the index normally has {expected}. Verify you uploaded the right index file.")
    current = {m.instrument.symbol: m for m in db.scalars(select(UniverseMember).where(UniverseMember.universe == universe))}
    new_syms = {c.symbol for c in cons}
    added = removed = 0
    for c in cons:
        inst = db.scalar(select(Instrument).where(Instrument.symbol == c.symbol))
        if inst is None:
            inst = Instrument(symbol=c.symbol, company_name=c.company_name, isin=c.isin, industry=c.industry, mapping_status="UNMAPPED")
            db.add(inst)
            db.flush()
        else:
            inst.company_name = c.company_name or inst.company_name
            inst.isin = c.isin or inst.isin
            inst.industry = c.industry or inst.industry
        m = current.get(c.symbol)
        if m is None:
            db.add(UniverseMember(universe=universe, instrument_id=inst.id, active=True))
            added += 1
        elif not m.active:
            m.active, m.removed_at = True, None
            added += 1
    for sym, m in current.items():
        if sym not in new_syms and m.active:
            m.active, m.removed_at = False, utcnow()
            removed += 1
    db.flush()
    res = map_instruments(db)
    status = "SUCCESS" if not warnings else "PARTIAL"
    msg = f"{len(cons)} constituents (+{added}/-{removed}); mapped {res['mapped']}" + (f"; {' '.join(warnings)}" if warnings else "")
    if not load_scrip_cache():
        msg += "; Dhan scrip master not loaded yet — instruments are UNMAPPED until you sync it"
    db.add(UniverseRefresh(universe=universe, source=source or "upload", status=status, count=len(cons), added=added, removed=removed, message=msg))
    audit(db, "INFO", "universe", f"{universe} synced: {msg}")
    db.commit()
    return {"universe": universe, "count": len(cons), "added": added, "removed": removed, "warnings": warnings, **res}


def members(db: Session, universe: str, mapped_only: bool = False) -> list[Instrument]:
    q = (select(Instrument).join(UniverseMember, UniverseMember.instrument_id == Instrument.id)
         .where(UniverseMember.universe == universe, UniverseMember.active.is_(True)).order_by(Instrument.symbol))
    if mapped_only:
        q = q.where(Instrument.security_id.isnot(None))
    return list(db.scalars(q))


def refresh_history(db: Session, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(UniverseRefresh).order_by(UniverseRefresh.id.desc()).limit(limit))
    return [{"id": r.id, "universe": r.universe, "source": r.source, "status": r.status, "count": r.count, "added": r.added,
             "removed": r.removed, "message": r.message, "created_at": iso(r.created_at)} for r in rows]


def last_success(db: Session, universe: str) -> dict | None:
    r = db.scalar(select(UniverseRefresh).where(UniverseRefresh.universe == universe, UniverseRefresh.status.in_(("SUCCESS", "PARTIAL")))
                  .order_by(UniverseRefresh.id.desc()))
    return {"at": iso(r.created_at), "count": r.count, "source": r.source, "status": r.status} if r else None


UNIVERSE_MAX_AGE_DAYS = 7
SCRIP_MAX_AGE_HOURS = 24
_ensure_lock = threading.Lock()


def _last_ok_at(db: Session, name: str):
    r = db.scalar(select(UniverseRefresh).where(UniverseRefresh.universe == name, UniverseRefresh.status.in_(("SUCCESS", "PARTIAL")))
                  .order_by(UniverseRefresh.id.desc()))
    return r.created_at if r else None


def ensure_universes(db: Session, force: bool = False) -> dict:
    """Automatically download whatever is missing or stale. Safe to call repeatedly."""
    if not _ensure_lock.acquire(blocking=False):
        return {"status": "ALREADY_RUNNING"}
    try:
        out: dict = {}
        now = utcnow()
        last = _last_ok_at(db, "SCRIP_MASTER")
        if force or not load_scrip_cache() or last is None or now - last > timedelta(hours=SCRIP_MAX_AGE_HOURS):
            try:
                out["SCRIP_MASTER"] = sync_scrip_master(db)
            except UniverseError as e:
                out["SCRIP_MASTER"] = {"error": str(e)}
        for u in UNIVERSES:
            last = _last_ok_at(db, u)
            if force or last is None or now - last > timedelta(days=UNIVERSE_MAX_AGE_DAYS) or not members(db, u):
                try:
                    out[u] = sync_universe(db, u)
                except UniverseError as e:
                    out[u] = {"error": str(e)}
        return out
    finally:
        _ensure_lock.release()


def status(db: Session) -> dict:
    out = {}
    for u in UNIVERSES:
        insts = members(db, u)
        last_fail = db.scalar(select(UniverseRefresh).where(UniverseRefresh.universe == u).order_by(UniverseRefresh.id.desc()))
        out[u] = {"label": UNIVERSE_LABEL[u], "count": len(insts), "mapped": sum(1 for i in insts if i.security_id),
                  "last_success": last_success(db, u),
                  "last_error": last_fail.message if last_fail is not None and last_fail.status == "FAILED" else None}
    last_fail = db.scalar(select(UniverseRefresh).where(UniverseRefresh.universe == "SCRIP_MASTER").order_by(UniverseRefresh.id.desc()))
    out["SCRIP_MASTER"] = {"rows": len(load_scrip_cache()), "last_success": last_success(db, "SCRIP_MASTER"),
                           "last_error": last_fail.message if last_fail is not None and last_fail.status == "FAILED" else None}
    return out
