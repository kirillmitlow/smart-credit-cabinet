"""Календарные помощники ядра: сдвиг на месяцы, полные месяцы между датами.

«Сегодня» ядру всегда передают (`APP_TODAY`): `date.today()` здесь запрещён (ruff, 30-13).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def add_months(value: date, months: int) -> date:
    """Сдвиг на `months` месяцев (можно отрицательное); день обрезается до длины месяца."""
    index = value.year * 12 + (value.month - 1) + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def full_months_between(start: date, end: date) -> int:
    """Полные календарные месяцы от `start` до `end` (не меньше нуля)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def ceil_months_between(start: date, end: date) -> int:
    """Месяцы от `start` до `end`, неполный месяц считается за целый."""
    whole = full_months_between(start, end)
    return whole + (1 if add_months(start, whole) < end else 0)


def next_business_day(value: date, holidays: frozenset[date] = frozenset()) -> date:
    """Ближайший рабочий день не раньше `value` (суббота и воскресенье переносятся вперёд)."""
    current = value
    while current.weekday() >= 5 or current in holidays:
        current += timedelta(days=1)
    return current
