"""T-209: ready смотрит Postgres, Redis и ревизию схемы; deps — свежесть сигнала воркера."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.main import create_app
from app.shared import db
from app.shared.cache import WORKER_HEARTBEAT_KEY, get_redis
from app.shared.clock import system_now
from app.shared.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    db.migrate(db.get_database().engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as c:
        yield c
    db.get_database().dispose()


async def test_ready_ok_when_postgres_redis_and_schema_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"postgres": True, "redis": True}


async def test_ready_is_problem_503_without_postgres(
    redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", redis_url)
    app = create_app(Settings(database_url="postgresql+psycopg://x:y@127.0.0.1:1/none"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as c:
        response = await c.get("/health/ready")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_READY"


async def test_deps_shows_stale_then_fresh_worker(client: httpx.AsyncClient) -> None:
    get_redis().delete(WORKER_HEARTBEAT_KEY)
    stale = (await client.get("/health/deps")).json()
    assert stale["worker"]["stale"] is True
    assert stale["systems"]["bki"]["circuit"] == "UNKNOWN"
    get_redis().set(WORKER_HEARTBEAT_KEY, system_now().isoformat())
    fresh = (await client.get("/health/deps")).json()
    assert fresh["worker"]["stale"] is False


async def test_worker_heartbeat_task_is_idempotent(
    redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", redis_url)
    from app.worker import heartbeat

    heartbeat()
    heartbeat()  # повторная доставка той же задачи ничего не ломает
    assert get_redis().get(WORKER_HEARTBEAT_KEY)
