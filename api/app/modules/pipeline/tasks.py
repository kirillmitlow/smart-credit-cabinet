"""Задача Celery `pipeline.run` (T-270, 50-05): тонкая обёртка над `run_pipeline`.

Толчок несёт только `application_id`; всё остальное читается из базы. Бизнес-сбой источника
задачу не роняет. Поломка инфраструктуры (разрыв БД, Redis, мягкий лимит времени) — повтор до
3 раз с паузами 2/10/30 с; дальше запуск подберёт сторож (T-271). Таймаут: мягкий 60 с, жёсткий 90 с.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import RedisError
from sqlalchemy.exc import DBAPIError

from app.modules.pipeline.runner import run_pipeline
from app.shared.tasks import celery_app

log = structlog.get_logger("app.pipeline.task")

SOFT_TIME_LIMIT = 60
HARD_TIME_LIMIT = 90
RETRY_PAUSES = (2, 10, 30)
INFRASTRUCTURE_ERRORS = (DBAPIError, RedisError, SoftTimeLimitExceeded, ConnectionError)


def retry_pause(retries_done: int) -> int:
    """Пауза перед очередным повтором: 2, 10, 30 секунд."""
    return RETRY_PAUSES[min(retries_done, len(RETRY_PAUSES) - 1)]


@celery_app.task(  # type: ignore[untyped-decorator]
    name="pipeline.run",
    bind=True,
    max_retries=len(RETRY_PAUSES),
    soft_time_limit=SOFT_TIME_LIMIT,
    time_limit=HARD_TIME_LIMIT,
)
def pipeline_run(self: Any, application_id: str) -> str:
    try:
        return run_pipeline(UUID(application_id)).value
    except INFRASTRUCTURE_ERRORS as exc:
        retries = int(self.request.retries)
        log.warning("pipeline_infrastructure_error", error=type(exc).__name__, retries=retries)
        raise self.retry(exc=exc, countdown=retry_pause(retries)) from exc
