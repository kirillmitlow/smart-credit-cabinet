"""Пять настоящих приложений и пять БД Postgres; управляемый разрыв HTTP между ролями."""

import asyncio
from dataclasses import dataclass

import httpx
from fastapi import FastAPI


class RoleNetwork(httpx.AsyncBaseTransport):
    def __init__(self, apps: dict[str, FastAPI]) -> None:
        self.transports = {
            role: httpx.ASGITransport(app=app, raise_app_exceptions=False)
            for role, app in apps.items()
            if role != "scenarios"
        }
        self.hosts = {
            "mock-registry": "registry",
            "mock-tax": "tax",
            "mock-credit-bureau": "bki",
            "mock-bank-core": "bank_core",
        }
        self.down: set[str] = set()
        self.lose_after_put: str | None = None
        self.bad_status: tuple[str, int] | None = None
        self.pause: str | None = None
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.calls: list[tuple[str, str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        role = self.hosts[request.url.host]
        self.calls.append((role, request.method, request.headers["X-Scenario-Code"]))
        if role in self.down:
            raise httpx.ConnectError("Остановленный мок", request=request)
        if request.method == "PUT":
            if self.pause == role:
                self.entered.set()
                await self.release.wait()
            if self.bad_status and self.bad_status[0] == role:
                return httpx.Response(self.bad_status[1], json={"detail": "Тест сбоя"})
        response = await self.transports[role].handle_async_request(request)
        if request.method == "PUT" and self.lose_after_put == role:
            await response.aread()
            assert response.status_code in (200, 201), response.text
            self.lose_after_put = None
            self.down.add(role)
            raise httpx.ReadError("Запись выполнена, ответ потерян", request=request)
        return response


@dataclass
class Harness:
    apps: dict[str, FastAPI]
    clients: dict[str, httpx.AsyncClient]
    network: RoleNetwork

    @property
    def api(self) -> httpx.AsyncClient:
        return self.clients["scenarios"]
