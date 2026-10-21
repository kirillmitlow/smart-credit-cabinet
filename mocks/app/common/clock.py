"""Часы стенда: единственный источник «сейчас» (раздел 2.5 спецификации).

APP_TODAY задаёт дату, время суток остаётся реальным. Границы суток и месяца — по Москве,
моменты в ответах — в UTC. Прямой вызов системного времени в остальном коде запрещён ruff.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
# Допуск на расхождение часов контейнеров (CONSENT_NOT_YET_VALID только сверх него)
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


def _system_now() -> datetime:
    return datetime.now(UTC)


class Clock:
    def __init__(
        self, app_today: date | None = None, real_now: Callable[[], datetime] = _system_now
    ) -> None:
        self._app_today = app_today
        self._real_now = real_now

    @property
    def app_today(self) -> date | None:
        return self._app_today

    def now_msk(self) -> datetime:
        real = self._real_now().astimezone(MSK)
        if self._app_today is None:
            return real
        return datetime.combine(self._app_today, real.timetz())

    def now(self) -> datetime:
        """Текущий момент в UTC с учётом APP_TODAY."""
        return self.now_msk().astimezone(UTC)

    def today(self) -> date:
        """«Сегодня» по Москве."""
        return self.now_msk().date()

    def start_of_today_utc(self) -> datetime:
        return datetime.combine(self.today(), time.min, tzinfo=MSK).astimezone(UTC)

    def is_in_future(self, moment: datetime) -> bool:
        """Момент позже «сейчас» больше чем на допуск (для CONSENT_NOT_YET_VALID)."""
        return moment - self.now() > CLOCK_SKEW_TOLERANCE


def month_start(day: date) -> date:
    return day.replace(day=1)


def last_full_month(today: date) -> date:
    """Первое число последнего полностью прошедшего месяца."""
    return month_start(month_start(today) - timedelta(days=1))


def last_reporting_year(today: date) -> int:
    """Последний год с обязательной сданной отчётностью: срок сдачи — 31 марта следующего года."""
    return today.year - 1 if today >= date(today.year, 4, 1) else today.year - 2
