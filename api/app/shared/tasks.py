"""Celery: приложение, постановка задач по имени после коммита, requestId в заголовке (T-205, 50-05).

Модули не импортируют друг друга ради фоновой работы: `enqueue(session, "pipeline.run", ...)`
ставит задачу по имени (R10) и только после успешного коммита транзакции. Повторная доставка
возможна (acks_late), поэтому задачи обязаны быть идемпотентными.
"""

from __future__ import annotations

from typing import Any

import structlog
from celery import Celery
from celery.signals import before_task_publish, task_postrun, task_prerun
from sqlalchemy.orm import Session

from app.shared.db import after_commit
from app.shared.settings import get_settings

QUEUES = ("pipeline", "outbox", "default")

celery_app = Celery("scc")


def configure_celery(broker_url: str | None = None) -> Celery:
    celery_app.conf.update(
        broker_url=broker_url or get_settings().celery_broker_url,
        task_serializer="json",
        accept_content=["json"],
        result_backend=None,
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=200,
        broker_transport_options={"visibility_timeout": 15 * 60},
        task_default_queue="default",
        task_routes={"pipeline.*": {"queue": "pipeline"}, "outbox.*": {"queue": "outbox"}},
        broker_connection_retry_on_startup=True,
    )
    return celery_app


def queue_for(name: str) -> str:
    prefix = name.split(".", 1)[0]
    return prefix if prefix in QUEUES else "default"


def send_now(name: str, **kwargs: Any) -> None:
    celery_app.send_task(name, kwargs=kwargs, queue=queue_for(name))


def enqueue(session: Session, name: str, **kwargs: Any) -> None:
    """Поставить задачу по имени после коммита; при откате транзакции задачи не будет."""
    after_commit(session, lambda: send_now(name, **kwargs))


def _attach_request_id(headers: dict[str, Any] | None = None, **_: Any) -> None:
    request_id = structlog.contextvars.get_contextvars().get("requestId")
    if headers is not None and request_id:
        headers["requestId"] = request_id


def _bind_request_id(task: Any = None, **_: Any) -> None:
    request_id = getattr(getattr(task, "request", None), "requestId", None)
    structlog.contextvars.bind_contextvars(requestId=request_id, task=getattr(task, "name", None))


def _unbind_request_id(**_: Any) -> None:
    structlog.contextvars.unbind_contextvars("requestId", "task")


# Подключаем без декораторов: у Celery нет аннотаций типов, а строгий mypy их требует
before_task_publish.connect(_attach_request_id, weak=False)
task_prerun.connect(_bind_request_id, weak=False)
task_postrun.connect(_unbind_request_id, weak=False)
