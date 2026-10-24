"""TradingView integration helpers.

Two supported, non-scraping integrations are used by the frontend:
  1. TradingView Lightweight Charts (open-source library, Apache-2.0) renders the SAME
     validated Dhan OHLC the engines use, with entry/stop/target/Fibonacci/zone price lines.
  2. The official TradingView Advanced Chart embed widget (display only, TradingView's own
     data feed). Some NSE symbols may be restricted in embedded widgets by exchange licensing;
     the UI says so instead of pretending the chart is connected.
"""
from __future__ import annotations

import re

_CLEAN = re.compile(r"[^A-Z0-9_]")


def symbol_for(nse_symbol: str) -> str:
    """NSE:SYMBOL format used by TradingView. '&' and '-' are replaced with '_' (e.g. M&M -> NSE:M_M)."""
    return "NSE:" + _CLEAN.sub("_", nse_symbol.upper())
