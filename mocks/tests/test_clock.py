"""T-103: часы APP_TODAY, московские границы, относительные даты, год отчётности."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.common.clock import Clock, last_full_month, last_reporting_year
from app.common.reldate import RelDateError, add_months, resolve


def fixed(moment: datetime) -> Clock:
    return Clock(None, real_now=lambda: moment)


def test_without_app_today_real_time_is_used() -> None:
    moment = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    assert fixed(moment).now() == moment


def test_app_today_replaces_date_but_keeps_time_of_day() -> None:
    real = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)  # 12:30 МСК
    clock = Clock(date(2026, 11, 20), real_now=lambda: real)
    assert clock.today() == date(2026, 11, 20)
    assert clock.now() == datetime(2026, 11, 20, 9, 30, tzinfo=UTC)


def test_shift_app_today_by_30_days_shifts_today() -> None:
    real = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    base = Clock(date(2026, 10, 21), real_now=lambda: real)
    later = Clock(date(2026, 10, 21) + timedelta(days=30), real_now=lambda: real)
    assert later.today() - base.today() == timedelta(days=30)


def test_day_and_month_boundaries_follow_moscow() -> None:
    # 23:30 UTC 31 октября — уже 1 ноября в Москве
    clock = fixed(datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    assert clock.today() == date(2026, 11, 1)
    assert last_full_month(clock.today()) == date(2026, 10, 1)
    assert clock.start_of_today_utc() == datetime(2026, 10, 31, 21, 0, tzinfo=UTC)


def test_future_moment_respects_five_minute_tolerance() -> None:
    now = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    clock = fixed(now)
    assert not clock.is_in_future(now + timedelta(minutes=5))
    assert clock.is_in_future(now + timedelta(minutes=5, seconds=1))


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("-3M", date(2026, 7, 21)),
        ("-9y", date(2017, 10, 21)),
        ("-14d", date(2026, 10, 7)),
        ("-2y3M", date(2024, 7, 21)),
        ("+3M", date(2027, 1, 21)),
        ("-1y2M10d", date(2025, 8, 11)),
    ],
)
def test_relative_dates(expr: str, expected: date) -> None:
    assert resolve(expr, date(2026, 10, 21)) == expected


def test_month_shift_clamps_to_month_end_and_leap_year() -> None:
    assert add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert add_months(date(2028, 3, 31), -1) == date(2028, 2, 29)
    assert resolve("-1y", date(2028, 2, 29)) == date(2027, 2, 28)


@pytest.mark.parametrize("expr", ["", "3M", "-", "-3m", "-M", "-3M2y", "--3M", "-3 M"])
def test_bad_relative_date_has_clear_message(expr: str) -> None:
    with pytest.raises(RelDateError, match="относительная дата"):
        resolve(expr, date(2026, 10, 21))


@pytest.mark.parametrize(
    ("today", "year"),
    [
        (date(2026, 3, 31), 2024),
        (date(2026, 4, 1), 2025),
        (date(2026, 10, 21), 2025),
        (date(2027, 1, 15), 2025),
    ],
)
def test_last_reporting_year_switches_on_april_first(today: date, year: int) -> None:
    assert last_reporting_year(today) == year
