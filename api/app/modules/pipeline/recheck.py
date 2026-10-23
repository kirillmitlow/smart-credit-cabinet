"""Новый уникальный запуск проверки заявки: перепроверка источников и повтор после ответа (T-277, 20-02, 50-05).

Простой повтор `pipeline.run` не подходит: ключ прежнего запуска (`версия:причина`) уже `DONE` и
не захватывается заново. Здесь в транзакции вызывающего (R7) делается всё сразу: переход в
`CHECKING` (сравнить и поменять по версии заявки), при необходимости новая версия заявки,
новая строка `pipeline_runs` с новым `run_key` и постановка `pipeline.run` после коммита.
Откат транзакции вызывающего убирает и запуск, и задачу. Свежий отчёт БКИ этой заявки (до 30 дней)
переиспользуется обычным механизмом снимков: новый платный запрос не делается.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.applications import (
    Actor,
    Application,
    Status,
    add_version,
    current_version,
    record_event,
    transition,
)
from app.modules.pipeline.models import PipelineRun
from app.shared import clock
from app.shared.errors import AppError, not_found
from app.shared.ids import uuid7
from app.shared.tasks import enqueue

log = structlog.get_logger("app.pipeline.recheck")

PIPELINE_TASK = "pipeline.run"
VersionReason = Literal["INFO_PROVIDED", "COLLATERAL_ADDED"]
_RUNNING = (Status.SUBMITTED, Status.CHECKING)


@dataclass(frozen=True, slots=True)
class RecheckReceipt:
    application_id: UUID
    run_id: UUID
    run_key: str
    version_id: UUID
    version_number: int
    application_version: int  # версия заявки (для CAS) после перехода в CHECKING


def request_recheck(
    session: Session,
    application_id: UUID,
    *,
    expected_version: int,
    actor: Actor,
    actor_id: UUID | None = None,
    reason_code: str | None = None,
    version_reason: VersionReason | None = None,
    data_patch: dict[str, Any] | None = None,
) -> RecheckReceipt:
    """Запустить новую проверку: `NEEDS_INFO | MANUAL_REVIEW | COUNTER_OFFER → CHECKING`.

    `expected_version` — `applications.version`, который видел вызывающий. `actor` определяет, кто
    вправе делать переход (клиент: из `NEEDS_INFO` и `COUNTER_OFFER`; андеррайтер: из
    `MANUAL_REVIEW`). `version_reason` создаёт новую версию заявки (`INFO_PROVIDED` и т.п.),
    иначе запуск идёт на текущей версии. Ошибки (все 409): `RECHECK_ALREADY_RUNNING` (проверка уже
    идёт), `VERSION_CONFLICT` (заявку изменили), `INVALID_TRANSITION` (статус или роль не те).
    """
    application = session.scalars(
        select(Application).where(Application.id == application_id).with_for_update()
    ).first()
    if application is None:
        raise not_found("Заявка")
    status = Status(application.status)
    if status in _RUNNING:
        raise AppError(
            409,
            "RECHECK_ALREADY_RUNNING",
            "Проверка заявки уже идёт",
            errors=[{"currentStatus": status.value}],
        )
    if application.version != expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "Заявку уже изменили, обновите страницу",
            errors=[{"version": application.version}],
        )
    transition(
        session,
        application,
        Status.CHECKING,
        actor=actor,
        actor_id=actor_id,
        reason_code=reason_code,
        payload={"recheck": True},
    )
    version = (
        add_version(session, application, version_reason, data_patch=data_patch)
        if version_reason is not None
        else current_version(session, application)
    )
    if version is None:
        raise AppError(409, "INVALID_TRANSITION", "У заявки нет отправленной версии")
    run_key = f"{version.id}:{version.reason}:r{application.version}"
    run = PipelineRun(
        id=uuid7(),
        application_id=application.id,
        version_id=version.id,
        run_key=run_key,
        trigger=version.reason,
        status="QUEUED",
        attempts=0,
        created_at=clock.now(),
    )
    session.add(run)
    session.flush()
    record_event(
        session,
        application,
        "STEP",
        actor_type=actor,
        actor_id=actor_id,
        step_code="RECHECK_REQUESTED",
        reason_code=reason_code,
        payload={"runId": str(run.id), "versionNumber": version.number},
    )
    enqueue(session, PIPELINE_TASK, application_id=str(application.id))
    log.info("recheck_requested", application=str(application.id), run=str(run.id))
    return RecheckReceipt(
        application.id, run.id, run_key, version.id, version.number, application.version
    )
