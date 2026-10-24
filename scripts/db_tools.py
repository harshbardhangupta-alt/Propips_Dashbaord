"""Backup or reset the local SQLite database.

  python scripts/db_tools.py backup          # copies data/trading.db to data/backups/
  python scripts/db_tools.py reset --yes     # deletes data/trading.db (paper history is lost)

Stop the backend before resetting. The encryption key (data/.secret.key) is kept so a
restored backup can still decrypt its saved credentials.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "trading.db"


def backup() -> Path:
    if not DB.exists():
        sys.exit(f"No database at {DB}")
    out_dir = DATA / "backups"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"trading-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(DB) as src, sqlite3.connect(out) as dst:
        src.backup(dst)  # consistent online backup (works while the app runs)
    return out


def reset(confirmed: bool) -> None:
    if not confirmed:
        sys.exit("Refusing to reset without --yes. This deletes all paper trades, signals and settings.")
    b = backup() if DB.exists() else None
    for p in (DB, DB.with_suffix(".db-wal"), DB.with_suffix(".db-shm")):
        if p.exists():
            p.unlink()
    print(f"Database removed{f' (backup saved to {b})' if b else ''}. It is recreated on next backend start.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["backup", "reset"])
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    if a.action == "backup":
        print(f"Backup written to {backup()}")
    else:
        reset(a.yes)
