"""Результат вызова внешней системы: данные или недоступность. Исключений наружу нет (50-08).

Адаптер всегда возвращает `Ok` или `SourceUnavailable`; что делать с недоступностью
(`MANUAL_REVIEW`, ручной ввод, отложить в outbox), решает вызывающий модуль.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class System(StrEnum):
    """Внешние системы. Значение попадает в `integration_calls.system` и метрики."""

    REGISTRY = "registry"
    TAX = "tax"
    CREDIT_BUREAU = "credit_bureau"
    BANK_CORE = "bank_core"


class Reason(StrEnum):
    """Почему данных нет.

    Первые четыре причины из 50-08. Остальные добавлены, чтобы не врать в журнале:
    обрыв соединения, лимит запросов и отказ по нашей вине (`4xx`, например нет согласия).
    """

    TIMEOUT = "TIMEOUT"
    HTTP_5XX = "HTTP_5XX"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class SnapshotMeta:
    """Сведения для `source_snapshots`: откуда, когда, на какую дату актуальны данные."""

    system: System
    source: str | None
    request_id: str | None
    retrieved_at: datetime
    data_actual_at: date | None = None
    simulated: bool = True
    # Мок вернул сохранённый ответ (заголовок Idempotent-Replayed): второго платного запроса не было
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class Ok[T]:
    """Успех. `data` равно `None` только там, где `404` — нормальный ответ (нет самозанятого, клиента…).

    `raw` — ответ системы как есть, для `source_snapshots` (пишет конвейер). В `repr` и логи не попадает.
    """

    data: T
    snapshot_meta: SnapshotMeta
    raw: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class SourceUnavailable:
    system: System
    reason: Reason
    status_code: int | None = None
    # Машинный код отказа системы (`CONSENT_EXPIRED`, `INN_INVALID`…) или нашей проверки
    error_code: str | None = None
    attempts: int = 0
    resource: str = ""

    @property
    def retryable_later(self) -> bool:
        """Имеет смысл повторить позже: сбой источника, а не наша ошибка запроса."""
        if self.error_code == "IDEMPOTENCY_IN_PROGRESS":
            return True  # первый запрос с этим ключом ещё идёт: позже ответ будет
        return self.reason not in (Reason.REJECTED, Reason.SCHEMA_ERROR)


type Result[T] = Ok[T] | SourceUnavailable
