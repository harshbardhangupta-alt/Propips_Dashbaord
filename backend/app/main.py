"""FastAPI entrypoint. PAPER TRADING ONLY — NO LIVE ORDERS."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_dashboard1, routes_dashboard2, routes_paper_trades, routes_settings, routes_system
from app.core.config import BACKEND_DIR, PAPER_BANNER, PROJECT_DIR, get_settings
from app.core.logging_config import configure_logging
from app.database.session import get_engine, session_scope

log = logging.getLogger(__name__)


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app" / "database" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


def bootstrap() -> None:
    from app.database.repository import get_setting, set_setting
    from app.paper_trading.engine import ensure_accounts
    from app.services.settings_service import K_SCAN_AFTER, K_SCAN_AUTO

    with session_scope() as db:
        ensure_accounts(db, get_settings().default_initial_capital)
        if get_setting(db, K_SCAN_AUTO) is None:
            set_setting(db, K_SCAN_AUTO, "false")
        if get_setting(db, K_SCAN_AFTER) is None:
            set_setting(db, K_SCAN_AFTER, "true")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level)
    get_engine()
    run_migrations()
    bootstrap()
    log.info(PAPER_BANNER)
    if s.enable_scheduler:
        from app.core.scheduler import start_scheduler

        start_scheduler()
    try:
        yield
    finally:
        from app.core.scheduler import stop_scheduler

        stop_scheduler()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Paper Trading Dashboard (NSE)", description=PAPER_BANNER, version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])
    for r in (routes_dashboard1, routes_dashboard2, routes_paper_trades, routes_settings, routes_system):
        app.include_router(r.router)

    @app.get("/api/health")
    def health():
        return {"ok": True, "paper_trading_only": True, "banner": PAPER_BANNER}

    dist = PROJECT_DIR / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
