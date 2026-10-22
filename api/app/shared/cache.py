"""Клиент Redis (Valkey): сессии, предохранители, сигнал воркера, шина событий SSE."""

from __future__ import annotations

from functools import lru_cache

import redis

from app.shared.settings import get_settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True
    )


WORKER_HEARTBEAT_KEY = "scc:worker:heartbeat"


def delete_prefixes(prefixes: list[str]) -> int:
    """Удалить все ключи с данными префиксами; вернуть число удалённых. Безопасно повторять.

    Служебный ключ воркера (`WORKER_HEARTBEAT_KEY`) под префиксы не попадает.
    """
    client = get_redis()
    deleted = 0
    for prefix in prefixes:
        batch = [
            key
            for key in client.scan_iter(match=f"{prefix}*", count=500)
            if key != WORKER_HEARTBEAT_KEY
        ]
        for start in range(0, len(batch), 500):
            deleted += int(client.unlink(*batch[start : start + 500]))
    return deleted
