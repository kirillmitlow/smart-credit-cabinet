"""T-106: режимы сбоев, X-Mock-Scenario, лимит, until; обрыв соединения на живом сервере."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated, Any

import httpx
import pytest
import uvicorn
from fastapi import APIRouter, Depends, FastAPI

from app import chaos
from app.chaos import ChaosMode, LostResponseError, ServerSendShim
from app.common.auth import require_api_key
from app.common.clock import Clock
from app.main import create_app
from tests.conftest import ADMIN_KEY, API_KEY, make_settings

ADMIN = {"X-Admin-Key": ADMIN_KEY}
API = {"X-Api-Key": API_KEY}


class Counter:
    def __init__(self) -> None:
        self.calls = 0


def build_app(counter: Counter) -> FastAPI:
    app = create_app(make_settings())
    router = APIRouter()

    @router.post("/api/v1/reports")
    async def reports(_c: Annotated[str, Depends(require_api_key)]) -> dict[str, int]:
        counter.calls += 1
        return {"n": counter.calls}

    @router.post("/api/v1/submissions")
    async def submissions(_c: Annotated[str, Depends(require_api_key)]) -> dict[str, bool]:
        counter.calls += 1
        return {"ok": True}

    app.include_router(router)
    return app


@pytest.fixture
def counter() -> Counter:
    return Counter()


@pytest.fixture
def app(counter: Counter) -> FastAPI:
    return build_app(counter)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        yield c


async def set_mode(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.put("/admin/chaos", json=body, headers=ADMIN)


async def test_default_mode_is_ok_and_visible(client: httpx.AsyncClient) -> None:
    response = await client.get("/admin/chaos", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["mode"] == "OK"


async def test_lowercase_mode_is_rejected(client: httpx.AsyncClient) -> None:
    response = await set_mode(client, mode="error")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_chaos_admin_requires_admin_key(client: httpx.AsyncClient) -> None:
    assert (await client.get("/admin/chaos")).status_code == 401
    assert (await client.get("/admin/chaos", headers=API)).status_code == 403


@pytest.mark.parametrize("mode", ["DOWN", "ERROR"])
async def test_down_and_error_fail_before_handler(
    client: httpx.AsyncClient, counter: Counter, mode: str
) -> None:
    await set_mode(client, mode=mode, errorRate=1.0)
    response = await client.post("/api/v1/reports", headers=API)
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    assert response.headers["Retry-After"] == "1"
    assert counter.calls == 0


async def test_error_rate_zero_never_breaks(client: httpx.AsyncClient, counter: Counter) -> None:
    await set_mode(client, mode="ERROR", errorRate=0)
    for _ in range(5):
        assert (await client.post("/api/v1/reports", headers=API)).status_code == 200
    assert counter.calls == 5


async def test_health_and_admin_are_never_broken(client: httpx.AsyncClient) -> None:
    await set_mode(client, mode="DOWN")
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/admin/chaos", headers=ADMIN)).json()["mode"] == "DOWN"


async def test_paths_break_only_listed_prefixes(client: httpx.AsyncClient) -> None:
    await set_mode(client, mode="DOWN", paths=["/api/v1/reports"])
    assert (await client.post("/api/v1/reports", headers=API)).status_code == 503
    assert (await client.post("/api/v1/submissions", headers=API)).status_code == 200


async def test_slow_delays_but_answers(client: httpx.AsyncClient) -> None:
    await set_mode(client, mode="SLOW", latencyMs=300)
    loop = asyncio.get_running_loop()
    started = loop.time()
    response = await client.post("/api/v1/reports", headers=API)
    assert response.status_code == 200
    assert loop.time() - started >= 0.3


async def test_timeout_hangs_longer_than_client_waits(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chaos, "TIMEOUT_SECONDS", 0.5)
    await set_mode(client, mode="TIMEOUT")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(client.post("/api/v1/reports", headers=API), timeout=0.2)


async def test_rate_limit_answers_429_with_retry_after(
    client: httpx.AsyncClient, counter: Counter
) -> None:
    await set_mode(client, mode="OK", rateLimitPerMinute=2)
    statuses = [(await client.post("/api/v1/reports", headers=API)).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    limited = await client.post("/api/v1/reports", headers=API)
    assert limited.json()["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1
    assert counter.calls == 2


async def test_until_returns_to_ok_by_itself(app: FastAPI, client: httpx.AsyncClient) -> None:
    now = app.state.clock.now()
    await set_mode(client, mode="DOWN", until=(now + timedelta(hours=1)).isoformat())
    assert (await client.post("/api/v1/reports", headers=API)).status_code == 503
    app.state.chaos._clock = Clock(app.state.clock.today() + timedelta(days=1))
    assert (await client.post("/api/v1/reports", headers=API)).status_code == 200
    assert (await client.get("/admin/chaos", headers=ADMIN)).json()["mode"] == "OK"


async def test_header_breaks_exactly_one_request(client: httpx.AsyncClient) -> None:
    broken = await client.post("/api/v1/reports", headers={**API, "X-Mock-Scenario": "ERROR"})
    healthy = await client.post("/api/v1/reports", headers=API)
    assert broken.status_code == 503
    assert healthy.status_code == 200
    assert (await client.get("/admin/chaos", headers=ADMIN)).json()["mode"] == "OK"


@pytest.mark.parametrize("value", ["error", "DOWN", "SLOW:abc", "ERROR:5"])
async def test_bad_scenario_header_is_422(client: httpx.AsyncClient, value: str) -> None:
    response = await client.post("/api/v1/reports", headers={**API, "X-Mock-Scenario": value})
    assert response.status_code == 422


async def test_slow_header_with_explicit_delay(client: httpx.AsyncClient) -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()
    response = await client.post("/api/v1/reports", headers={**API, "X-Mock-Scenario": "SLOW:250"})
    assert response.status_code == 200
    assert loop.time() - started >= 0.25


async def test_lost_response_runs_handler_without_answer(app: FastAPI, counter: Counter) -> None:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        with pytest.raises(LostResponseError):
            await c.post("/api/v1/reports", headers={**API, "X-Mock-Scenario": "LOST_RESPONSE"})
    assert counter.calls == 1


def test_scenario_header_parser() -> None:
    assert chaos.parse_scenario_header("SLOW:3000") == (ChaosMode.SLOW, 3000)
    assert chaos.parse_scenario_header("LOST_RESPONSE") == (ChaosMode.LOST_RESPONSE, None)
    assert chaos.parse_scenario_header("OK") is None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_lost_response_drops_real_connection(counter: Counter) -> None:
    port = _free_port()
    config = uvicorn.Config(
        ServerSendShim(build_app(counter)), host="127.0.0.1", port=port, log_config=None
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as c:
            with pytest.raises(httpx.RemoteProtocolError):
                await c.post("/api/v1/reports", headers={**API, "X-Mock-Scenario": "LOST_RESPONSE"})
            after = await c.post("/api/v1/reports", headers=API)
        assert counter.calls == 2  # первый запрос выполнился, хотя ответа не было
        assert after.json() == {"n": 2}
    finally:
        server.should_exit = True
        await task
