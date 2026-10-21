"""HTTP к админ-API: зависимости подменяются только в тестах, бизнес-API не вызывается."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request

from app.roles.scenarios.split import System
from app.settings import Settings


class AdminGateway:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.urls = {
            System.REGISTRY: settings.registry_url,
            System.TAX: settings.tax_url,
            System.BKI: settings.bki_url,
            System.BANK_CORE: settings.bank_core_url,
        }
        self.admin_key = settings.mock_admin_key

    async def send(
        self,
        system: System,
        action: str,
        code: str,
        inn: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        path = f"/subjects/{inn}" if action == "PUT" else f"/scenarios/{code}"
        return await self.client.request(
            action,
            f"{self.urls[system].rstrip('/')}/admin{path}",
            json=body,
            headers={"X-Admin-Key": self.admin_key, "X-Scenario-Code": code},
        )


async def get_gateway(request: Request) -> AsyncIterator[AdminGateway]:
    settings: Settings = request.app.state.settings
    async with httpx.AsyncClient(timeout=settings.scenario_request_timeout_seconds) as client:
        yield AdminGateway(client, settings)


Gateway = Annotated[AdminGateway, Depends(get_gateway)]
