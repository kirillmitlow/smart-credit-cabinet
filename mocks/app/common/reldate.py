"""Относительные даты сценариев: «-3M», «-9y», «-14d», «-2y3M», «+3M» (раздел 2.5)."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_PATTERN = re.compile(r"^(?P<sign>[+-])(?:(?P<y>\d+)y)?(?:(?P<m>\d+)M)?(?:(?P<d>\d+)d)?$")


class RelDateError(ValueError):
    pass


def add_months(day: date, months: int) -> date:
    """Сдвиг на месяцы; день прижимается к концу месяца (31.03 − 1M = 28/29.02)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    last_day = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last_day))


def resolve(expr: str, today: date) -> date:
    """Превратить относительную дату в абсолютную относительно «сегодня»."""
    match = _PATTERN.match(expr.strip())
    if not match or not any(match.group(k) for k in ("y", "m", "d")):
        raise RelDateError(
            f"Неверная относительная дата {expr!r}: ожидается знак и части y/M/d, например «-2y3M»"
        )
    sign = -1 if match["sign"] == "-" else 1
    years, months, days = (int(match[k] or 0) for k in ("y", "m", "d"))
    shifted = add_months(today, sign * (years * 12 + months))
    return shifted + timedelta(days=sign * days)
