"""Test configuration. External APIs are always mocked; no real credentials are needed."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="pt-tests-")
os.environ["PT_DATA_DIR"] = _TMP
os.environ["PT_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["PT_ENABLE_SCHEDULER"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.database import session as session_mod  # noqa: E402
from app.database.models import Base  # noqa: E402
from app.market_data.cache import candle_cache  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    engine = session_mod.init_engine(f"sqlite:///{tmp_path}/unit.db")
    Base.metadata.create_all(engine)
    s = session_mod.SessionLocal()
    from app.paper_trading.engine import ensure_accounts

    ensure_accounts(s)
    s.commit()
    candle_cache.clear()
    yield s
    s.close()
    engine.dispose()
