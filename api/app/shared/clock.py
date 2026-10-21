"""Часы стенда (R9, спецификация моков 2.5): единственный источник «сегодня» и «сейчас».

`APP_TODAY` задаёт дату для бизнес-времени (подпись согласий, даты платежей, сроки), время суток
реальное, границы дня — по Москве. Для аренд, таймаутов и сторожей — `monotonic()` и `system_now()`:
они не зависят от APP_TODAY, иначе перевод «сегодня» ломал бы технические сроки (50-05).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def system_now() -> datetime:
    """Реальное время UTC для технических сроков (аренда запуска, сигнал воркера)."""
    return datetime.now(UTC)


def monotonic() -> float:
    return time.monotonic()


class Clock:
    def __init__(
        self, app_today: date | None = None, real_now: Callable[[], datetime] = system_now
    ) -> None:
        self._app_today = app_today
        self._real_now = real_now
        self._shift = timedelta()

    def now_msk(self) -> datetime:
        real = self._real_now().astimezone(MSK)
        if self._app_today is not None:
            real = datetime.combine(self._app_today, real.timetz())
        return real + self._shift

    def now(self) -> datetime:
        """Бизнес-«сейчас» в UTC."""
        return self.now_msk().astimezone(UTC)

    def today(self) -> date:
        return self.now_msk().date()

    def advance(self, delta: timedelta) -> None:
        """Перемотка в тестах: сдвигает и дату, и время суток."""
        self._shift += delta


_clock = Clock()


def configure(app_today: date | None) -> None:
    global _clock
    _clock = Clock(app_today)


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> None:
    """Подмена часов в тестах."""
    global _clock
    _clock = clock


def now() -> datetime:
    return _clock.now()


def today() -> date:
    return _clock.today()
