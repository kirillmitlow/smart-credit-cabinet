from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from testcontainers.community.postgres import PostgresContainer

from app.main import create_app
from app.settings import Settings

API_KEY = "dev-registry-key"
ADMIN_KEY = "dev-admin-key"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "mock_role": "registry",
        "mock_api_keys": f"api:{API_KEY}",
        "mock_admin_key": ADMIN_KEY,
        "mock_latency_ms": "0",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    return make_settings


@pytest.fixture
def app() -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        yield c


POSTGRES_IMAGE = "postgres:17-bookworm"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Один Postgres на весь прогон (Testcontainers); базы ролей создаёт `database_url`."""
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as pg:
        yield pg.get_connection_url()


def database_url(server_url: str, name: str) -> str:
    """Отдельная база на сервере теста — как в стенде, где у каждой роли своя база (3.1)."""
    import asyncio

    import asyncpg

    plain = server_url.replace("postgresql+asyncpg://", "postgresql://")
    base, _, _ = plain.rpartition("/")

    async def create() -> None:
        conn = await asyncpg.connect(plain)
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{name}"')
        finally:
            await conn.close()

    asyncio.run(create())
    return f"{base.replace('postgresql://', 'postgresql+asyncpg://')}/{name}"
