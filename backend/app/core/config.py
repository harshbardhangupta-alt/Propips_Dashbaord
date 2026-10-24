"""Application configuration.

Values come from environment variables (prefix ``PT_``) or ``backend/.env``.
There is intentionally NO setting that enables live trading: this application
is paper-trading only and that cannot be changed by configuration.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

# Hard-coded, not configurable. Checked by tests and exposed by /api/system/status.
PAPER_TRADING_ONLY = True
PAPER_BANNER = "PAPER TRADING ONLY — NO LIVE ORDERS"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PT_", env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite:///{DATA_DIR / 'trading.db'}"
    data_dir: Path = DATA_DIR
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    # Disable background jobs (used by tests and for read-only inspection).
    enable_scheduler: bool = True
    log_level: str = "INFO"

    # Default paper capital per dashboard account (INR).
    default_initial_capital: float = 100_000.0


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
