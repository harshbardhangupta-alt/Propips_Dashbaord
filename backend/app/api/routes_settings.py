"""Settings & API credentials, universe synchronisation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.market_calendar import get_calendar, reload_calendar
from app.core.timeutils import now_ist
from app.database.models import Instrument, UniverseMember
from app.database.session import get_db
from app.services import explanation_service, settings_service as ss
from app.services import universe_service as us

router = APIRouter(prefix="/api/settings", tags=["settings"])
MAX_UPLOAD = 120 * 1024 * 1024


class DhanIn(BaseModel):
    client_id: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    access_token: str | None = Field(default=None, min_length=10, max_length=4096)
    confirm_replace_client_id: bool = False


@router.get("/dhan")
def get_dhan(db: Session = Depends(get_db)):
    return ss.dhan_view(db)


@router.put("/dhan")
def put_dhan(body: DhanIn, db: Session = Depends(get_db)):
    cur = ss.dhan_view(db)
    if body.client_id is not None and cur["client_id"] and body.client_id != cur["client_id"] and not body.confirm_replace_client_id:
        raise HTTPException(409, "A Client ID is already saved. Confirm replacement explicitly (confirm_replace_client_id=true).")
    if body.client_id is None and body.access_token is None:
        raise HTTPException(400, "Nothing to update")
    ss.save_dhan(db, body.client_id, body.access_token)
    db.commit()
    return ss.dhan_view(db)


@router.delete("/dhan")
def delete_dhan(confirm: bool = False, db: Session = Depends(get_db)):
    if not confirm:
        raise HTTPException(400, "Pass confirm=true to delete Dhan credentials")
    ss.delete_dhan(db)
    db.commit()
    return ss.dhan_view(db)


@router.post("/dhan/test")
def test_dhan(db: Session = Depends(get_db)):
    res = ss.test_dhan(db)
    db.commit()
    return {**ss.dhan_view(db), "result": res}


class OpenAIIn(BaseModel):
    api_key: str | None = Field(default=None, min_length=10, max_length=512)
    model: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._:\-]+$")
    enabled: bool | None = None


@router.get("/openai")
def get_openai(db: Session = Depends(get_db)):
    return ss.openai_view(db)


@router.put("/openai")
def put_openai(body: OpenAIIn, db: Session = Depends(get_db)):
    ss.save_openai(db, body.api_key, body.model, body.enabled)
    db.commit()
    return ss.openai_view(db)


@router.delete("/openai")
def delete_openai(confirm: bool = False, db: Session = Depends(get_db)):
    if not confirm:
        raise HTTPException(400, "Pass confirm=true to delete the OpenAI API key")
    ss.delete_openai(db)
    db.commit()
    return ss.openai_view(db)


@router.post("/openai/test")
def test_openai(db: Session = Depends(get_db)):
    res = explanation_service.test_openai(db)
    return {**ss.openai_view(db), "result": res}


# ------------------------------------------------------------------ universes
@router.get("/universe")
def universe(db: Session = Depends(get_db)):
    out = {}
    for u in us.UNIVERSES:
        ms = list(db.scalars(select(UniverseMember).where(UniverseMember.universe == u, UniverseMember.active.is_(True))))
        insts = [m.instrument for m in ms]
        out[u] = {
            "label": us.UNIVERSE_LABEL[u], "count": len(insts), "mapped": sum(1 for i in insts if i.security_id),
            "issues": [{"symbol": i.symbol, "status": i.mapping_status, "note": i.mapping_note} for i in insts if i.mapping_status != "MAPPED" or i.mapping_note],
            "last_success": us.last_success(db, u),
        }
    out["SCRIP_MASTER"] = {"last_success": us.last_success(db, "SCRIP_MASTER"), "cached_rows": len(us.load_scrip_cache())}
    out["history"] = us.refresh_history(db)
    out["sources"] = us.NSE_INDEX_SOURCES
    return out


def _uerr(e: Exception):
    raise HTTPException(502, str(e))


@router.get("/universe/status")
def universe_status(db: Session = Depends(get_db)):
    return {**us.status(db), "refreshing": us._ensure_lock.locked()}


@router.post("/universe/refresh", status_code=202)
def universe_refresh():
    """Re-download the Dhan instrument list and both index lists in the background."""
    import threading

    from app.database.session import SessionLocal

    if us._ensure_lock.locked():
        return {"status": "ALREADY_RUNNING"}

    def work():
        s = SessionLocal()
        try:
            us.ensure_universes(s, force=True)
        finally:
            s.close()

    threading.Thread(target=work, name="universe-refresh", daemon=True).start()
    return {"status": "STARTED"}


@router.post("/universe/{universe}/sync")
def sync_universe(universe: str, db: Session = Depends(get_db)):
    try:
        return us.sync_universe(db, universe.upper())
    except us.UniverseError as e:
        _uerr(e)


async def _read(f: UploadFile) -> str:
    raw = await f.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "File too large")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


@router.post("/universe/{universe}/upload")
async def upload_universe(universe: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = await _read(file)
    try:
        return us.sync_universe(db, universe.upper(), text, f"upload:{(file.filename or 'file.csv')[:100]}")
    except us.UniverseError as e:
        raise HTTPException(400, str(e))


@router.post("/scrip-master/sync")
def sync_scrip(db: Session = Depends(get_db)):
    try:
        return us.sync_scrip_master(db)
    except us.UniverseError as e:
        _uerr(e)


@router.post("/scrip-master/upload")
async def upload_scrip(file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = await _read(file)
    try:
        return us.sync_scrip_master(db, text, f"upload:{(file.filename or 'scrip.csv')[:100]}")
    except us.UniverseError as e:
        raise HTTPException(400, str(e))


@router.get("/calendar")
def calendar():
    cal = get_calendar()
    today = now_ist().date()
    return {"today": today.isoformat(), "is_trading_day": cal.is_trading_day(today), "holiday_name": cal.holiday_name(today),
            "next_trading_day": cal.next_trading_day(today).isoformat(), "year_status": cal.year_status(today.year),
            "holidays": [{"date": d.isoformat(), "name": n} for d, n in sorted(cal.holidays.items())],
            "file": "data/nse_holidays.json"}


@router.post("/calendar/reload")
def calendar_reload():
    reload_calendar()
    return calendar()


@router.get("/instruments/{symbol}")
def instrument(symbol: str, db: Session = Depends(get_db)):
    i = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()[:32]))
    if i is None:
        raise HTTPException(404, "Unknown symbol")
    return {"symbol": i.symbol, "company_name": i.company_name, "isin": i.isin, "security_id": i.security_id, "segment": i.exchange_segment,
            "tick_size": i.tick_size, "lot_size": i.lot_size, "mapping_status": i.mapping_status, "mapping_note": i.mapping_note}
