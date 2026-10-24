"""Background jobs (APScheduler, Asia/Kolkata).

Jobs have fixed ids and ``replace_existing=True`` with an in-memory job store, so a restart
never duplicates jobs; ``max_instances=1`` + ``coalesce`` prevent overlapping runs, and the
scan manager's lock prevents a manual scan overlapping a scheduled one.

Dashboard 2 schedule (NSE trading days only):
  * regular scans every 5 minutes from 09:15 to 15:00 IST inclusive — controlled by
    Start/Stop Auto Scan (setting ``scanner_auto_enabled``)
  * one after-market scan at 19:00 IST — controlled by its OWN toggle
    (``scanner_after_market_enabled``); Stop Auto Scan does not disable it.
Monitoring only happens while this process is running.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.market_calendar import get_calendar
from app.core.timeutils import IST, now_ist
from app.database.models import utcnow
from app.database.repository import job_status
from app.database.session import SessionLocal

log = logging.getLogger(__name__)

REGULAR_START = time(9, 15)
REGULAR_END = time(15, 0)
AFTER_MARKET_AT = time(19, 0)


def regular_scan_trigger() -> OrTrigger:
    return OrTrigger([
        CronTrigger(day_of_week="mon-fri", hour=9, minute="15-55/5", timezone=IST),
        CronTrigger(day_of_week="mon-fri", hour="10-14", minute="*/5", timezone=IST),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=0, timezone=IST),
    ])


def after_market_trigger() -> CronTrigger:
    return CronTrigger(day_of_week="mon-fri", hour=19, minute=0, timezone=IST)


def is_regular_scan_slot(dt: datetime) -> bool:
    dt = dt.astimezone(IST)
    return get_calendar().is_trading_day(dt.date()) and REGULAR_START <= dt.time().replace(second=0, microsecond=0) <= REGULAR_END


def is_after_market_slot(dt: datetime) -> bool:
    dt = dt.astimezone(IST)
    return get_calendar().is_trading_day(dt.date()) and dt.time().replace(second=0, microsecond=0) >= AFTER_MARKET_AT


def is_monitor_slot(dt: datetime) -> bool:
    dt = dt.astimezone(IST)
    return get_calendar().is_trading_day(dt.date()) and time(9, 20) <= dt.time() <= time(15, 40)


def _record(job_id: str, fn: Callable[[], str | None]) -> None:
    db = SessionLocal()
    try:
        js = job_status(db, job_id)
        if not js.enabled:
            return
        js.last_run_at = utcnow()
        js.run_count += 1
        db.commit()
        try:
            msg = fn()
            js.last_status = "SKIPPED" if (msg or "").startswith("SKIPPED") else "OK"
            js.last_message = (msg or "")[:2000]
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            js.last_status = "ERROR"
            js.last_message = f"{type(e).__name__}: {e}"[:2000]
        js.last_finished_at = utcnow()
        db.merge(js)
        db.commit()
    finally:
        db.close()


# ------------------------------------------------------------------ job bodies
def job_regular_scan() -> str:
    from app.services.scan_service import scan_manager
    from app.services.settings_service import K_SCAN_AUTO, bool_setting

    now = now_ist()
    db = SessionLocal()
    try:
        if not bool_setting(db, K_SCAN_AUTO, False):
            return "SKIPPED: auto scan is stopped"
    finally:
        db.close()
    if not is_regular_scan_slot(now):
        return f"SKIPPED: {now:%Y-%m-%d %H:%M} is not a regular scan slot (holiday/outside 09:15-15:00)"
    res = scan_manager.run("SCHEDULED")
    return f"{res['status']}: {res.get('message', '')}"


def job_after_market_scan() -> str:
    from app.services.scan_service import scan_manager
    from app.services.settings_service import K_SCAN_AFTER, bool_setting

    now = now_ist()
    db = SessionLocal()
    try:
        if not bool_setting(db, K_SCAN_AFTER, True):
            return "SKIPPED: after-market scan disabled"
    finally:
        db.close()
    if not is_after_market_slot(now):
        return "SKIPPED: not a trading day"
    res = scan_manager.run("AFTER_MARKET")
    return f"{res['status']}: {res.get('message', '')}"


def job_monitor() -> str:
    from app.integrations.dhan_client import DhanError
    from app.paper_trading.position_manager import monitor
    from app.services.settings_service import get_dhan_client

    if not is_monitor_slot(now_ist()):
        from app.paper_trading.position_manager import expire_overdue

        db = SessionLocal()
        try:
            n = expire_overdue(db)
            db.commit()
        finally:
            db.close()
        return f"SKIPPED: market closed (expired {n} overdue pending entries)"
    db = SessionLocal()
    try:
        client = get_dhan_client(db)
        st = monitor(db, client)
        return f"monitored {st['trades']} trade(s) on {st['instruments']} instrument(s); actions={st['actions']}; errors={len(st['errors'])}"
    except DhanError as e:
        return f"ERROR: {e.status} {e.message}"
    finally:
        db.close()


def job_mtf_refresh() -> str:
    from app.integrations.dhan_client import DhanError
    from app.services.mtf_service import refresh_universe
    from app.services.settings_service import get_dhan_client

    from sqlalchemy import func, select

    from app.database.models import MTFSnapshot

    now = now_ist()
    in_session = get_calendar().is_trading_day(now.date()) and time(9, 15) <= now.time() <= time(15, 50)
    db = SessionLocal()
    try:
        if not in_session:
            # Outside the session, refresh at most twice a day so the table still shows the latest close.
            newest = db.scalar(select(func.max(MTFSnapshot.evaluated_at)))
            if newest is not None and (utcnow() - newest).total_seconds() < 12 * 3600:
                return "SKIPPED: outside market session (data refreshed recently)"
        res = refresh_universe(db, get_dhan_client(db), _shutdown_event)
        return f"{res['status']}: {res['done']}/{res['total']} evaluated, {res['errors']} errors"
    except DhanError as e:
        return f"ERROR: {e.status} {e.message}"
    finally:
        db.close()


def job_quotes() -> str:
    from app.integrations.dhan_client import DhanError
    from app.services import market_data_service as mds
    from app.services.settings_service import dhan_credentials, get_dhan_client
    from app.services.universe_service import members

    now = now_ist()
    cal = get_calendar()
    db = SessionLocal()
    try:
        if dhan_credentials(db) is None:
            return "SKIPPED: Dhan not configured"
        in_session = cal.is_trading_day(now.date()) and time(9, 10) <= now.time() <= time(15, 45)
        if not in_session and now.minute % 30 != 0:
            return "SKIPPED: outside session (refreshing every 30 min)"
        insts = {i.id: i for u in ("NIFTY100", "NIFTY250") for i in members(db, u, mapped_only=True)}
        res = mds.refresh_quotes(db, get_dhan_client(db), list(insts.values()))
        db.commit()
        return f"updated {res['updated']}/{res['requested']} quotes"
    except DhanError as e:
        return f"ERROR: {e.status} {e.message}"
    finally:
        db.close()


def job_signal_expiry() -> str:
    from app.services.signal_service import expire_signals

    db = SessionLocal()
    try:
        n = expire_signals(db)
        db.commit()
        return f"expired {n} signal(s)"
    finally:
        db.close()


def job_universe_sync() -> str:
    from app.services.universe_service import ensure_universes

    db = SessionLocal()
    try:
        res = ensure_universes(db)
        if not res:
            return "SKIPPED: stock lists are up to date"
        return "; ".join(f"{k}: {v.get('error') or str(v.get('count', v.get('rows', 'ok'))) + ' loaded'}" for k, v in res.items() if isinstance(v, dict))
    finally:
        db.close()


JOBS = {
    "universe_sync": ("Auto-download Nifty 100 / Nifty 250 lists and Dhan instruments (retries every 30 min)", job_universe_sync,
                      lambda: IntervalTrigger(minutes=30, timezone=IST)),
    "d2_regular_scan": ("Dashboard 2 scan every 5 min 09:15–15:00 IST", job_regular_scan, regular_scan_trigger),
    "d2_after_market_scan": ("Dashboard 2 after-market scan 19:00 IST", job_after_market_scan, after_market_trigger),
    "position_monitor": ("Paper entries/exits on completed 5m candles", job_monitor,
                         lambda: CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", second=40, timezone=IST)),
    "d1_mtf_refresh": ("Dashboard 1 Nifty 100 MTF refresh every 15 min", job_mtf_refresh,
                       lambda: CronTrigger(minute="1,16,31,46", timezone=IST)),
    "quote_refresh": ("Quote snapshots (REST) every minute in session", job_quotes, lambda: IntervalTrigger(seconds=60, timezone=IST)),
    "signal_expiry": ("Expire stale Dashboard 2 signals", job_signal_expiry, lambda: IntervalTrigger(minutes=5, timezone=IST)),
}

_shutdown_event = threading.Event()
_scheduler: BackgroundScheduler | None = None


def start_scheduler(run_startup_sync: bool = True) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _shutdown_event.clear()
    sch = BackgroundScheduler(timezone=IST, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 90})
    for job_id, (_desc, fn, trig) in JOBS.items():
        sch.add_job(_record, trig(), args=[job_id, fn], id=job_id, name=job_id, replace_existing=True)
    sch.start()
    _scheduler = sch
    # Fetch the stock lists right away on startup (in the background) instead of waiting 30 min.
    if run_startup_sync:
        sch.add_job(_record, args=["universe_sync", job_universe_sync], id="universe_sync_startup", replace_existing=True)
    log.info("Scheduler started with jobs: %s", ", ".join(JOBS))
    return sch


def stop_scheduler() -> None:
    global _scheduler
    from app.services.scan_service import scan_manager

    _shutdown_event.set()
    scan_manager.cancel()
    if _scheduler is not None:
        _scheduler.shutdown(wait=True)
        _scheduler = None


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def jobs_view() -> list[dict]:
    db = SessionLocal()
    try:
        out = []
        for job_id, (desc, _fn, _t) in JOBS.items():
            js = job_status(db, job_id)
            job = _scheduler.get_job(job_id) if _scheduler else None
            out.append({
                "id": job_id, "description": desc, "scheduler_running": bool(_scheduler and _scheduler.running),
                "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
                "last_run_at": js.last_run_at.isoformat() + "Z" if js.last_run_at else None,
                "last_finished_at": js.last_finished_at.isoformat() + "Z" if js.last_finished_at else None,
                "last_status": js.last_status, "last_message": js.last_message, "run_count": js.run_count,
            })
        db.commit()
        return out
    finally:
        db.close()


def next_run(job_id: str) -> str | None:
    job = _scheduler.get_job(job_id) if _scheduler else None
    return job.next_run_time.isoformat() if job and job.next_run_time else None


def next_valid_fire(trigger, check: Callable[[datetime], bool], now: datetime | None = None, limit: int = 500) -> str | None:
    """Next fire time of ``trigger`` that also passes ``check`` (skips holidays)."""
    now = (now or now_ist()).astimezone(IST)
    prev = None
    t = now
    for _ in range(limit):
        t = trigger.get_next_fire_time(prev, t)
        if t is None:
            return None
        if check(t):
            return t.isoformat()
        prev = t
        from datetime import timedelta

        t = t + timedelta(seconds=1)
    return None
