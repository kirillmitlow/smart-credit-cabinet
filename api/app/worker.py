"""Celery-воркер и beat (T-205, 50-05). Запуск: `celery -A app.worker worker -Q pipeline,outbox,default`.

Задачи модулей регистрируются импортом их `tasks` здесь, по мере появления модулей.
"""

from __future__ import annotations

from datetime import timedelta

from app import document_tasks
from app.modules import disbursement
from app.modules.disbursement import tasks as disbursement_tasks  # noqa: F401 — disbursement.run
from app.modules.pipeline import tasks as pipeline_tasks  # noqa: F401 — регистрирует pipeline.run
from app.shared import clock, db, outbox
from app.shared.cache import WORKER_HEARTBEAT_KEY, get_redis
from app.shared.logs import configure_logging
from app.shared.settings import get_settings
from app.shared.tasks import celery_app, configure_celery
from app.wiring import wire_modules

_settings = get_settings()
configure_logging("worker", _settings.log_level)
clock.configure(_settings.app_today)
db.configure(_settings.sqlalchemy_url)
configure_celery()
wire_modules()
disbursement.register()  # обработчики outbox: выдача в АБС и OBLIGATION_OPENED в БКИ
outbox.set_dead_letter_hook(disbursement.audit_dead_letter)

HEARTBEAT_EVERY = timedelta(seconds=30)
RELAY_SAFETY_NET_EVERY = timedelta(seconds=30)  # «страховка» к толчку после коммита (Q-055, C)


@celery_app.task(name="default.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> None:
    """Сигнал «воркер жив» для /health/deps; повтор безопасен."""
    get_redis().set(WORKER_HEARTBEAT_KEY, clock.system_now().isoformat(), ex=600)


celery_app.conf.beat_schedule = {
    "worker-heartbeat": {"task": "default.heartbeat", "schedule": HEARTBEAT_EVERY},
    "outbox-relay-safety-net": {"task": outbox.RELAY_TASK, "schedule": RELAY_SAFETY_NET_EVERY},
    "statement-recovery": {"task": document_tasks.RECOVER_TASK, "schedule": timedelta(seconds=60)},
}

app = celery_app
