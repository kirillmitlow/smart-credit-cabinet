"""Интерфейс предохранителя для слоя устойчивости (T-231 даёт настоящую реализацию в Redis).

Здесь только контракт и заглушка «всегда закрыт»: клиент уже спрашивает разрешение перед каждой
попыткой и сообщает исход, так что предохранитель подключается без правки клиента.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.modules.integrations.results import System


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True, slots=True)
class Permit:
    allowed: bool
    state: BreakerState
    # Это единственный пробный запрос полуоткрытого предохранителя
    probe: bool = False


class CircuitBreaker(Protocol):
    def acquire(self, system: System) -> Permit: ...

    def success(self, system: System, permit: Permit) -> None: ...

    def failure(self, system: System, permit: Permit) -> None: ...


class NullBreaker:
    """Всегда закрыт. Подставляется, пока предохранитель не настроен (и в большинстве unit-тестов)."""

    def acquire(self, system: System) -> Permit:
        return Permit(True, BreakerState.CLOSED)

    def success(self, system: System, permit: Permit) -> None:
        return None

    def failure(self, system: System, permit: Permit) -> None:
        return None
