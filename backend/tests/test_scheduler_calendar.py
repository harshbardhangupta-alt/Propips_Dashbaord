from datetime import date, datetime, timedelta

from app.core.market_calendar import MarketCalendar, get_calendar
from app.core.scheduler import (
    JOBS,
    after_market_trigger,
    is_after_market_slot,
    is_regular_scan_slot,
    next_valid_fire,
    regular_scan_trigger,
)
from app.core.timeutils import IST


def fire_times(trigger, start, end):
    out, prev, t = [], None, start
    while True:
        n = trigger.get_next_fire_time(prev, t)
        if n is None or n > end:
            return out
        out.append(n)
        prev, t = n, n + timedelta(seconds=1)


def test_regular_scan_every_five_minutes_0915_to_1500():
    day = datetime(2026, 10, 26, 0, 0, tzinfo=IST)  # Monday
    times = fire_times(regular_scan_trigger(), day, day + timedelta(hours=23, minutes=59))
    hm = [t.strftime("%H:%M") for t in times]
    assert hm[0] == "09:15" and hm[-1] == "15:00"
    assert len(hm) == 70  # 9:15..9:55 (9) + 10:00..14:55 (60) + 15:00 (1)
    assert all((b - a) == timedelta(minutes=5) for a, b in zip(times, times[1:]) if a.date() == b.date())
    assert all(t.tzinfo is not None and t.utcoffset() == timedelta(hours=5, minutes=30) for t in times)


def test_after_market_scan_once_at_1900():
    day = datetime(2026, 10, 26, 0, 0, tzinfo=IST)
    times = fire_times(after_market_trigger(), day, day + timedelta(hours=23, minutes=59))
    assert [t.strftime("%H:%M") for t in times] == ["19:00"]


def test_weekend_and_holiday_skipped():
    sat = datetime(2026, 10, 24, 10, 0, tzinfo=IST)
    assert not is_regular_scan_slot(sat)
    hol = datetime(2026, 11, 10, 10, 0, tzinfo=IST)  # listed holiday in data/nse_holidays.json
    assert not is_regular_scan_slot(hol) and not is_after_market_slot(hol.replace(hour=19))
    assert next_valid_fire(regular_scan_trigger(), is_regular_scan_slot, datetime(2026, 11, 9, 15, 1, tzinfo=IST)) == "2026-11-11T09:15:00+05:30"


def test_slot_boundaries():
    d = datetime(2026, 10, 26, 9, 14, tzinfo=IST)
    assert not is_regular_scan_slot(d)
    assert is_regular_scan_slot(d.replace(minute=15))
    assert is_regular_scan_slot(d.replace(hour=15, minute=0))
    assert not is_regular_scan_slot(d.replace(hour=15, minute=5))


def test_calendar_loading(tmp_path):
    p = tmp_path / "h.json"
    p.write_text('{"years": {"2030": {"verified": true, "holidays": [{"date": "2030-01-01", "name": "X"}]}}}')
    cal = MarketCalendar.load(p)
    assert not cal.is_trading_day(date(2030, 1, 1)) and cal.year_status(2030)["verified"]
    assert cal.next_trading_day(date(2029, 12, 31)) == date(2030, 1, 2)
    assert not MarketCalendar.load(tmp_path / "missing.json").holidays


def test_market_hours():
    cal = get_calendar()
    assert cal.is_market_open(datetime(2026, 10, 26, 9, 15, tzinfo=IST))
    assert not cal.is_market_open(datetime(2026, 10, 26, 15, 30, tzinfo=IST))
    # Timezone handling: 04:00 UTC == 09:30 IST
    from datetime import timezone

    assert cal.is_market_open(datetime(2026, 10, 26, 4, 0, tzinfo=timezone.utc))


def test_scheduler_no_duplicate_jobs_and_clean_shutdown(monkeypatch):
    from app.core import scheduler as sch

    s1 = sch.start_scheduler(run_startup_sync=False)
    s2 = sch.start_scheduler(run_startup_sync=False)  # second start must not add jobs
    try:
        assert s1 is s2
        ids = [j.id for j in s1.get_jobs()]
        assert sorted(ids) == sorted(JOBS) and len(ids) == len(set(ids))
    finally:
        sch.stop_scheduler()
    assert sch.get_scheduler() is None
    s3 = sch.start_scheduler(run_startup_sync=False)  # "restart"
    try:
        assert len(s3.get_jobs()) == len(JOBS)
    finally:
        sch.stop_scheduler()
