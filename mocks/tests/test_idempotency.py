"""T-104 (интеграция): правила идемпотентности из раздела 2.7 на живом Postgres."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse, Response
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.common.auth import require_api_key
from app.common.clock import Clock
from app.common.idempotency import (
    IdempotencyDep,
    OptionalIdempotencyDep,
    idempotency_keys,
    purge_expired,
)
from app.common.schemas import CamelModel
from app.main import create_app
from tests.conftest import API_KEY, database_url, make_settings

pytestmark = pytest.mark.integration


class Order(CamelModel):
    amount_rub: int
    fail_with: int | None = None
    delay_ms: int = 0
    note: dict[str, Any] | None = None


@dataclass
class Calls:
    count: int = 0
    seen: list[int] = field(default_factory=list)


def build_app(postgres_url: str, calls: Calls) -> FastAPI:
    app = create_app(make_settings(mock_role="bank_core", database_url=postgres_url))
    router = APIRouter()

    async def handle(order: Order) -> Response:
        calls.count += 1
        calls.seen.append(order.amount_rub)
        await asyncio.sleep(order.delay_ms / 1000)
        if order.fail_with == 500:
            raise RuntimeError("обработчик упал")
        if order.fail_with:
            return JSONResponse({"error": True}, status_code=order.fail_with)
        return JSONResponse({"id": str(uuid.uuid4()), "amountRub": order.amount_rub}, 201)

    @router.post("/api/v1/stub/disbursements", dependencies=[Depends(require_api_key)])
    async def required(order: Order, idem: IdempotencyDep) -> Response:
        return await idem.run(lambda: handle(order))

    @router.post("/api/v1/stub/reports", dependencies=[Depends(require_api_key)])
    async def optional(order: Order, idem: OptionalIdempotencyDep) -> Response:
        return await idem.run(lambda: handle(order))

    app.include_router(router)
    return app


@pytest.fixture(scope="module")
def idem_url(postgres_url: str) -> str:
    return database_url(postgres_url, "mock_idempotency_test")


@pytest.fixture
def calls() -> Calls:
    return Calls()


@pytest.fixture
async def app(idem_url: str, calls: Calls) -> AsyncIterator[FastAPI]:
    app = build_app(idem_url, calls)
    await app.state.database.migrate()
    yield app
    await app.state.database.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        yield c


DISBURSE = "/api/v1/stub/disbursements"


def headers(key: str | None = None) -> dict[str, str]:
    result = {"X-Api-Key": API_KEY}
    if key:
        result["Idempotency-Key"] = key
    return result


def new_key() -> str:
    return f"k-{uuid.uuid4()}"


async def test_repeat_returns_same_response_once_executed(
    client: httpx.AsyncClient, calls: Calls
) -> None:
    key = new_key()
    first = await client.post(DISBURSE, json={"amountRub": 100}, headers=headers(key))
    second = await client.post(DISBURSE, json={"amountRub": 100}, headers=headers(key))
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert calls.count == 1


async def test_field_order_does_not_change_body_hash(
    client: httpx.AsyncClient, calls: Calls
) -> None:
    key = new_key()
    json_headers = {**headers(key), "Content-Type": "application/json"}
    await client.post(
        DISBURSE, content=b'{"amountRub": 5, "note": {"a": 1, "b": 2}}', headers=json_headers
    )
    again = await client.post(
        DISBURSE, content=b'{"note": {"b": 2, "a": 1}, "amountRub": 5}', headers=json_headers
    )
    assert again.status_code == 201
    assert calls.count == 1


async def test_same_key_other_body_is_409_reused(client: httpx.AsyncClient) -> None:
    key = new_key()
    await client.post(DISBURSE, json={"amountRub": 100}, headers=headers(key))
    response = await client.post(DISBURSE, json={"amountRub": 999}, headers=headers(key))
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_missing_required_key_is_422(client: httpx.AsyncClient, calls: Calls) -> None:
    response = await client.post(DISBURSE, json={"amountRub": 1}, headers=headers())
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert calls.count == 0


async def test_optional_key_absent_means_every_call_is_new(
    client: httpx.AsyncClient, calls: Calls
) -> None:
    for _ in range(2):
        assert (
            await client.post("/api/v1/stub/reports", json={"amountRub": 1}, headers=headers())
        ).status_code == 201
    key = new_key()
    a = await client.post("/api/v1/stub/reports", json={"amountRub": 1}, headers=headers(key))
    b = await client.post("/api/v1/stub/reports", json={"amountRub": 1}, headers=headers(key))
    assert a.json() == b.json()
    assert calls.count == 3


@pytest.mark.parametrize("failure", [422, 503, 500])
async def test_failed_attempt_releases_key(
    client: httpx.AsyncClient, calls: Calls, failure: int
) -> None:
    key = new_key()
    body: dict[str, Any] = {"amountRub": 7, "failWith": failure}
    first = await client.post(DISBURSE, json=body, headers=headers(key))
    assert first.status_code == failure
    second = await client.post(DISBURSE, json=body, headers=headers(key))
    assert second.status_code == failure
    assert calls.count == 2  # ошибка не сохраняется: повтор выполнился заново


async def test_parallel_duplicates_give_one_success_and_one_in_progress(
    client: httpx.AsyncClient, calls: Calls
) -> None:
    key = new_key()
    body = {"amountRub": 50, "delayMs": 400}
    responses = await asyncio.gather(
        *(client.post(DISBURSE, json=body, headers=headers(key)) for _ in range(5))
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409, 409, 409, 409]
    busy = [r for r in responses if r.status_code == 409]
    assert all(r.json()["code"] == "IDEMPOTENCY_IN_PROGRESS" for r in busy)
    assert all(r.headers["Retry-After"] == "1" for r in busy)
    assert calls.count == 1
    replay = await client.post(DISBURSE, json=body, headers=headers(key))
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"


async def _row_set(app: FastAPI, key: str, **values: Any) -> None:
    t = idempotency_keys
    async with app.state.database.engine.begin() as conn:
        await conn.execute(sa.update(t).where(t.c.key == key).values(**values))


async def test_abandoned_in_progress_key_is_executed_again(
    app: FastAPI, client: httpx.AsyncClient, calls: Calls
) -> None:
    key = new_key()
    await client.post(DISBURSE, json={"amountRub": 3}, headers=headers(key))
    now = app.state.clock.now()
    await _row_set(app, key, state="IN_PROGRESS", claimed_at=now - timedelta(seconds=61))
    response = await client.post(DISBURSE, json={"amountRub": 3}, headers=headers(key))
    assert response.status_code == 201
    assert "Idempotent-Replayed" not in response.headers
    assert calls.count == 2


async def test_fresh_in_progress_key_is_not_taken_over(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    key = new_key()
    await client.post(DISBURSE, json={"amountRub": 3}, headers=headers(key))
    now = app.state.clock.now()
    await _row_set(app, key, state="IN_PROGRESS", claimed_at=now - timedelta(seconds=30))
    response = await client.post(DISBURSE, json={"amountRub": 3}, headers=headers(key))
    assert response.status_code == 409


async def test_key_older_than_24h_is_new_again(
    app: FastAPI, client: httpx.AsyncClient, calls: Calls
) -> None:
    key = new_key()
    await client.post(DISBURSE, json={"amountRub": 9}, headers=headers(key))
    later = app.state.clock.today() + timedelta(days=2)
    app.state.clock = Clock(later)  # APP_TODAY сдвинули на двое суток
    response = await client.post(DISBURSE, json={"amountRub": 10}, headers=headers(key))
    assert response.status_code == 201
    assert calls.count == 2
    assert await purge_expired(app.state.database, Clock(later + timedelta(days=2))) >= 1


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.lists(st.sampled_from(["A", "B"]), min_size=1, max_size=6))
def test_any_sequence_of_retries_executes_once(idem_url: str, bodies: list[str]) -> None:
    async def scenario() -> None:
        calls = Calls()
        app = build_app(idem_url, calls)
        await app.state.database.migrate()
        transport = httpx.ASGITransport(app=app)
        key = new_key()
        amounts = {"A": 1, "B": 2}
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
            results = [
                await c.post(DISBURSE, json={"amountRub": amounts[b]}, headers=headers(key))
                for b in bodies
            ]
        await app.state.database.dispose()
        first = bodies[0]
        for body, response in zip(bodies, results, strict=True):
            expected = 201 if body == first else 409
            assert response.status_code == expected
        assert calls.count == 1
        assert len({r.text for r, b in zip(results, bodies, strict=True) if b == first}) == 1

    asyncio.run(scenario())
