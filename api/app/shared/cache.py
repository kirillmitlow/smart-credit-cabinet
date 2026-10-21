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
