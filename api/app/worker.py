"""Celery-воркер и beat (T-205, 50-05). Запуск: `celery -A app.worker worker -Q pipeline,outbox,default`.

Задачи модулей регистрируются импортом их `tasks` здесь, по мере появления модулей.
"""

from __future__ import annotations

from datetime import timedelta

from app.shared import clock, db
from app.shared.cache import WORKER_HEARTBEAT_KEY, get_redis
from app.shared.logs import configure_logging
from app.shared.settings import get_settings
from app.shared.tasks import celery_app, configure_celery

_settings = get_settings()
configure_logging("worker", _settings.log_level)
clock.configure(_settings.app_today)
db.configure(_settings.sqlalchemy_url)
configure_celery()

HEARTBEAT_EVERY = timedelta(seconds=30)


@celery_app.task(name="default.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> None:
    """Сигнал «воркер жив» для /health/deps; повтор безопасен."""
    get_redis().set(WORKER_HEARTBEAT_KEY, clock.system_now().isoformat(), ex=600)


celery_app.conf.beat_schedule = {
    "worker-heartbeat": {"task": "default.heartbeat", "schedule": HEARTBEAT_EVERY},
}

app = celery_app
