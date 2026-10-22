"""Запись попыток в `integration_calls` отдельной короткой транзакцией (50-08).

Журнал нужен для отладки и показа жюри, поэтому его сбой не должен ломать сам вызов:
ошибку записи логируем и идём дальше. Запись переживает откат основной транзакции сценария.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import structlog

from app.modules.integrations.models import IntegrationCall
from app.shared import db

log = structlog.get_logger("app.integrations.journal")


@dataclass(frozen=True, slots=True)
class CallRecord:
    system: str
    method: str
    path: str
    subject_inn_masked: str | None
    status_code: int | None
    error_code: str | None
    duration_ms: int
    attempt: int
    circuit_state: str | None
    request_id: str | None
    application_id: UUID | None
    idempotent_replayed: bool = False


class CallJournal(Protocol):
    def record(self, record: CallRecord) -> None: ...


class DbCallJournal:
    """Своя сессия и свой коммит на каждую запись: в транзакцию вызывающего не вмешиваемся."""

    def record(self, record: CallRecord) -> None:
        try:
            with db.transaction() as session:
                session.add(
                    IntegrationCall(
                        system=record.system,
                        method=record.method,
                        path=record.path,
                        subject_inn_masked=record.subject_inn_masked,
                        status_code=record.status_code,
                        error_code=record.error_code,
                        duration_ms=record.duration_ms,
                        attempt=record.attempt,
                        circuit_state=record.circuit_state,
                        request_id=record.request_id,
                        application_id=record.application_id,
                        idempotent_replayed=record.idempotent_replayed,
                    )
                )
        except Exception as exc:  # noqa: BLE001 — журнал не должен ронять вызов
            log.warning("integration_call_log_failed", error=type(exc).__name__)


class NullJournal:
    def record(self, record: CallRecord) -> None:
        return None
