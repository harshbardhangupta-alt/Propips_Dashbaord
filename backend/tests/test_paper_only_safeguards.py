"""Code-level verification that no live order-execution path exists."""
import ast
import re
from pathlib import Path

from app.core import config
from app.integrations.dhan_client import ALLOWED_ENDPOINTS, DhanClient

APP = Path(__file__).resolve().parents[1] / "app"
SOURCES = [p for p in APP.rglob("*.py") if "migrations" not in p.parts]

FORBIDDEN_PATTERNS = [
    r"api\.dhan\.co/v2/orders",
    r"['\"]/orders",
    r"/super/orders",
    r"/forever/orders",
    r"/positions/convert",
    r"/killswitch",
    r"/edis/",
    r"place_order",
    r"modify_order",
    r"cancel_order",
    r"place_super_order",
    r"live_trading_enabled",
    r"LIVE_TRADING",
]


def test_paper_only_constant():
    assert config.PAPER_TRADING_ONLY is True
    assert "PAPER TRADING ONLY" in config.PAPER_BANNER
    assert not any("live" in f.lower() for f in config.Settings.model_fields)


def test_no_order_endpoint_strings_in_source():
    hits = []
    for p in SOURCES:
        text = p.read_text(encoding="utf-8")
        for pat in FORBIDDEN_PATTERNS:
            for m in re.finditer(pat, text):
                line = text[: m.start()].count("\n") + 1
                hits.append(f"{p.relative_to(APP)}:{line}: {pat}")
    # dhan_client.py mentions forbidden endpoints only inside its docstring/comment.
    hits = [h for h in hits if not h.startswith("integrations/dhan_client.py")]
    assert hits == [], hits


def test_official_sdk_with_order_methods_not_imported():
    for p in SOURCES:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("dhanhq") for a in node.names), p
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("dhanhq"), p


def test_dhan_client_has_no_order_methods():
    names = [n for n in dir(DhanClient) if not n.startswith("_")]
    assert not any(k in n.lower() for n in names for k in ("order", "position", "trade", "kill", "edis", "margin"))


def test_dhan_client_only_uses_whitelisted_paths():
    src = (APP / "integrations" / "dhan_client.py").read_text()
    used = set(re.findall(r'self\._request\(\s*"(GET|POST)",\s*"([^"]+)"', src))
    assert used and used <= set(ALLOWED_ENDPOINTS)


def test_executions_are_always_simulated():
    from app.database.models import Execution, PaperAccount, PaperTrade

    for m in (Execution, PaperTrade, PaperAccount):
        assert m.__table__.c.simulated.default.arg is True


def test_openai_has_no_tools():
    src = (APP / "integrations" / "openai_client.py").read_text()
    assert "tools=" not in src and "function_call" not in src
