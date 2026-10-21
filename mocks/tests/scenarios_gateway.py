"""Изолировать CRUD/валидацию от сети; реальная раскладка проверяется в test_scenarios_apply."""

from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from app.roles.scenarios.gateway import AdminGateway, get_gateway


def stub_gateway(app: FastAPI) -> None:
    async def dependency() -> AsyncIterator[AdminGateway]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"deleted": 0}))
        ) as client:
            yield AdminGateway(client, app.state.settings)

    app.dependency_overrides[get_gateway] = dependency
