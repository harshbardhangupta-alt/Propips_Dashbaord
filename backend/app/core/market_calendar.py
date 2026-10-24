"""NSE trading-day calendar.

Holidays are loaded from ``data/nse_holidays.json`` (editable, maintainable without
code changes). Each year in the file carries a ``verified`` flag; the System Status
page warns when the current year is unverified or missing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from app.core.timeutils import IST, MARKET_CLOSE, MARKET_OPEN

DEFAULT_HOLIDAY_FILE = Path(__file__).resolve().parents[3] / "data" / "nse_holidays.json"


@dataclass
class MarketCalendar:
    holidays: dict[date, str] = field(default_factory=dict)
    years: dict[int, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "MarketCalendar":
        path = path or DEFAULT_HOLIDAY_FILE
        cal = cls()
        if not path.exists():
            return cal
        raw = json.loads(path.read_text(encoding="utf-8"))
        for year, info in raw.get("years", {}).items():
            cal.years[int(year)] = {"verified": bool(info.get("verified")), "source": info.get("source", "")}
            for h in info.get("holidays", []):
                cal.holidays[date.fromisoformat(h["date"])] = h.get("name", "Holiday")
        return cal

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def holiday_name(self, d: date) -> str | None:
        if d.weekday() >= 5:
            return "Weekend"
        return self.holidays.get(d)

    def is_market_open(self, dt: datetime) -> bool:
        dt = dt.astimezone(IST)
        return self.is_trading_day(dt.date()) and MARKET_OPEN <= dt.time() < MARKET_CLOSE

    def next_trading_day(self, d: date) -> date:
        n = d + timedelta(days=1)
        while not self.is_trading_day(n):
            n += timedelta(days=1)
        return n

    def previous_trading_day(self, d: date) -> date:
        p = d - timedelta(days=1)
        while not self.is_trading_day(p):
            p -= timedelta(days=1)
        return p

    def year_status(self, year: int) -> dict:
        info = self.years.get(year)
        if info is None:
            return {"year": year, "present": False, "verified": False, "source": ""}
        return {"year": year, "present": True, **info}


_calendar: MarketCalendar | None = None


def get_calendar() -> MarketCalendar:
    global _calendar
    if _calendar is None:
        _calendar = MarketCalendar.load()
    return _calendar


def reload_calendar(path: Path | None = None) -> MarketCalendar:
    global _calendar
    _calendar = MarketCalendar.load(path)
    return _calendar
