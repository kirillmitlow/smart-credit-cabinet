"""T-103 (интеграция): миграции роли при старте и /health/ready на живом Postgres."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from app.common.db import Database, head_revision, version_table
from app.main import create_app
from app.settings import Role
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

POSTGRES_IMAGE = "postgres:17-bookworm"


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as pg:
        yield pg.get_connection_url()


async def test_migrations_bring_each_role_to_head(postgres_url: str) -> None:
    for role in Role:
        database = Database(postgres_url, role)
        assert not await database.is_ready()
        await database.migrate()
        await database.migrate()  # повторный старт ничего не ломает
        assert await database.is_ready()
        async with database.engine.connect() as conn:
            stored = await conn.scalar(text(f"SELECT version_num FROM {version_table(role)}"))  # noqa: S608
        assert stored == head_revision(role)
        await database.dispose()


async def test_parallel_starts_are_serialized_by_lock(postgres_url: str) -> None:
    first, second = Database(postgres_url, Role.TAX), Database(postgres_url, Role.TAX)
    await asyncio.gather(first.migrate(), second.migrate())
    assert await first.is_ready()
    assert await second.is_ready()
    await first.dispose()
    await second.dispose()


@pytest.fixture
async def ready_client(postgres_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(mock_role="bki", database_url=postgres_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
            yield client


async def test_ready_turns_200_after_startup_migrations(ready_client: httpx.AsyncClient) -> None:
    for _ in range(50):
        response = await ready_client.get("/health/ready")
        if response.status_code == 200:
            break
        await asyncio.sleep(0.1)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


async def test_ready_is_503_while_database_unreachable() -> None:
    url = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"
    app = create_app(make_settings(mock_role="tax", database_url=url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
            assert (await client.get("/health/live")).status_code == 200
            response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["db"] == "unavailable"
