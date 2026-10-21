from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

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
