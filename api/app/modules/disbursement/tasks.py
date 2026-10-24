"""Задача Celery `disbursement.run` (T-342, 50-05): запуск выдачи после `SIGNED`.

Её по имени ставит код подписания договора в той же транзакции, где заявка становится `SIGNED`
(`enqueue(session, "disbursement.run", application_id=...)`). Толчок несёт только `application_id`.
Задача идемпотентна: повторная доставка и параллельные вызовы дают одну выдачу. Сеть здесь не
вызывается: деньги отправляет outbox. Поломка инфраструктуры (разрыв БД, Redis) — повтор с паузами.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.modules.applications import Application, Status, hold_operation
from app.modules.disbursement import delivery, service
from app.shared import clock, db
from app.shared.operations import ResetInProgress
from app.shared.tasks import celery_app

log = structlog.get_logger("app.disbursement.task")

TASK_NAME = "disbursement.run"
RECOVER_TASK = "disbursement.recover"
SOFT_TIME_LIMIT = 20
HARD_TIME_LIMIT = 30
RETRY_PAUSES = (2, 10, 30)
INFRASTRUCTURE_ERRORS = (DBAPIError, RedisError, SoftTimeLimitExceeded, ConnectionError)

delivery.register()


def run(application_id: UUID, *, skip_locked: bool = False) -> str:
    """Тело задачи: отдельная функция, чтобы вызывать её из тестов без брокера."""
    try:
        with hold_operation(application_id) as scope:
            if scope is None:
                return service.StartResult.SKIPPED.value
            with db.transaction() as session:
                result = service.start(session, application_id, skip_locked=skip_locked)
    except ResetInProgress:
        return service.StartResult.SKIPPED.value
    log.info("disbursement_run", application=str(application_id), result=result.value)
    return result.value


def recover(limit: int = 100, *, budget_s: float = 15) -> dict[str, int]:
    """Потерянный толчок после подписи: довести SIGNED до долговечного outbox.

    Сеть АБС здесь не вызывается. Обычный запуск и сторож используют одну транзакцию,
    ключи и ограждение сброса. Занятую заявку пропускаем, а сбой одной не мешает другим.
    """
    deadline = clock.monotonic() + budget_s
    with db.transaction() as session:
        ids = session.scalars(
            select(Application.id)
            .where(Application.status == Status.SIGNED)
            .order_by(Application.updated_at, Application.id)
            .limit(limit)
        ).all()
    counts = {result.value: 0 for result in service.StartResult}
    counts["ERROR"] = 0
    for application_id in ids:
        if clock.monotonic() >= deadline:
            break
        try:
            counts[run(application_id, skip_locked=True)] += 1
        except Exception as exc:
            log.warning(
                "disbursement_recovery_failed",
                application=str(application_id),
                error_type=type(exc).__name__,
            )
            counts["ERROR"] += 1
    return counts


@celery_app.task(name=RECOVER_TASK, soft_time_limit=20, time_limit=30)  # type: ignore[untyped-decorator]
def recover_task() -> dict[str, int]:
    return recover()


@celery_app.task(  # type: ignore[untyped-decorator]
    name=TASK_NAME,
    bind=True,
    max_retries=len(RETRY_PAUSES),
    soft_time_limit=SOFT_TIME_LIMIT,
    time_limit=HARD_TIME_LIMIT,
)
def disbursement_run(self: Any, application_id: str) -> str:
    try:
        return run(UUID(application_id))
    except INFRASTRUCTURE_ERRORS as exc:
        retries = int(self.request.retries)
        log.warning("disbursement_infrastructure_error", error=type(exc).__name__, retries=retries)
        raise self.retry(
            exc=exc, countdown=RETRY_PAUSES[min(retries, len(RETRY_PAUSES) - 1)]
        ) from exc
