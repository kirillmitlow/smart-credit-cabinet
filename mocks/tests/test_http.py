"""T-102: ошибки problem+json, ключи доступа, X-Request-Id, маскирование в логе, схемы Swagger."""

from __future__ import annotations

import json
import logging
from typing import Annotated

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request

from app.common.auth import require_admin, require_api_key
from app.common.middleware import JsonFormatter
from app.common.problems import PROBLEM_JSON, valid_inn
from app.common.schemas import CamelModel, Meta, build_meta
from app.main import create_app
from tests.conftest import ADMIN_KEY, API_KEY, make_settings

OTHER_SYSTEM_KEY = "dev-tax-key"


class Body(CamelModel):
    amount_rub: int


class CompanyOut(CamelModel):
    inn: str
    meta: Meta


def build_app() -> FastAPI:
    app = create_app(make_settings())
    router = APIRouter()

    @router.get("/api/v1/stub/companies/{inn}", response_model=CompanyOut, response_model_by_alias=True)
    async def company(
        request: Request,
        inn: Annotated[str, Depends(valid_inn)],
        _consumer: Annotated[str, Depends(require_api_key)],
    ) -> CompanyOut:
        return CompanyOut(inn=inn, meta=build_meta(request, "EGRUL"))

    @router.post("/api/v1/echo")
    async def echo(body: Body, _consumer: Annotated[str, Depends(require_api_key)]) -> Body:
        return body

    @router.get("/admin/ping", dependencies=[Depends(require_admin)])
    async def admin_ping() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    return app


@pytest.fixture
async def stub() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://mock")


BUSINESS = "/api/v1/stub/companies/0017654322"


@pytest.mark.parametrize(
    ("headers", "path", "status", "code"),
    [
        ({"X-Api-Key": API_KEY}, BUSINESS, 200, None),
        ({}, BUSINESS, 401, "UNAUTHORIZED"),
        ({"X-Api-Key": OTHER_SYSTEM_KEY}, BUSINESS, 401, "UNAUTHORIZED"),
        ({"X-Api-Key": ADMIN_KEY}, BUSINESS, 403, "FORBIDDEN"),
        ({"X-Admin-Key": ADMIN_KEY}, BUSINESS, 403, "FORBIDDEN"),
        ({"X-Admin-Key": ADMIN_KEY}, "/admin/ping", 200, None),
        ({}, "/admin/ping", 401, "UNAUTHORIZED"),
        ({"X-Admin-Key": "wrong"}, "/admin/ping", 401, "UNAUTHORIZED"),
        ({"X-Api-Key": API_KEY}, "/admin/ping", 403, "FORBIDDEN"),
        ({"X-Admin-Key": API_KEY}, "/admin/ping", 403, "FORBIDDEN"),
    ],
)
async def test_key_matrix(
    stub: httpx.AsyncClient, headers: dict[str, str], path: str, status: int, code: str | None
) -> None:
    response = await stub.get(path, headers=headers)
    assert response.status_code == status
    if code:
        assert response.headers["content-type"] == PROBLEM_JSON
        assert response.json()["code"] == code


async def test_success_has_meta_and_camel_case(stub: httpx.AsyncClient) -> None:
    response = await stub.get(BUSINESS, headers={"X-Api-Key": API_KEY, "X-Request-Id": "req_test1"})
    meta = response.json()["meta"]
    assert meta["source"] == "EGRUL"
    assert meta["simulated"] is True
    assert meta["requestId"] == "req_test1"
    assert "retrievedAt" in meta


async def test_invalid_inn_is_the_only_400(stub: httpx.AsyncClient) -> None:
    response = await stub.get("/api/v1/stub/companies/0017654323", headers={"X-Api-Key": API_KEY})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "INN_INVALID"
    assert set(body) >= {"type", "title", "status", "code", "requestId"}
    assert body["type"].endswith("/inn-invalid")


async def test_schema_errors_are_422_with_fields(stub: httpx.AsyncClient) -> None:
    response = await stub.post(
        "/api/v1/echo", json={"amountRub": "много"}, headers={"X-Api-Key": API_KEY}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["loc"] == ["body", "amountRub"]


async def test_unknown_route_is_problem_404(stub: httpx.AsyncClient) -> None:
    response = await stub.get("/api/v1/nowhere", headers={"X-Api-Key": API_KEY})
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_request_id_echoed_or_generated(stub: httpx.AsyncClient) -> None:
    echoed = await stub.get("/health/live", headers={"X-Request-Id": "req_abc"})
    generated = await stub.get("/health/live")
    unsafe = await stub.get("/health/live", headers={"X-Request-Id": "bad id with spaces"})
    assert echoed.headers["X-Request-Id"] == "req_abc"
    assert generated.headers["X-Request-Id"].startswith("req_")
    assert unsafe.headers["X-Request-Id"].startswith("req_")


async def test_error_carries_same_request_id(stub: httpx.AsyncClient) -> None:
    response = await stub.get(BUSINESS, headers={"X-Request-Id": "req_err"})
    assert response.json()["requestId"] == "req_err"
    assert response.headers["X-Request-Id"] == "req_err"


async def test_access_log_masks_inn_and_accounts(
    stub: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.access"):
        await stub.get(BUSINESS, headers={"X-Api-Key": API_KEY})
        await stub.get("/api/v1/accounts/40802810800000001234", headers={"X-Api-Key": API_KEY})
    lines = [JsonFormatter("mock-registry").format(r) for r in caplog.records]
    text = "\n".join(lines)
    assert "0017654322" not in text
    assert "0017****22" in text
    assert "40802810800000001234" not in text
    record = json.loads(lines[0])
    assert {"ts", "level", "service", "requestId", "method", "path", "status", "durationMs"} <= set(
        record
    )


async def test_openapi_declares_both_security_schemes(stub: httpx.AsyncClient) -> None:
    spec = (await stub.get("/openapi.json")).json()
    schemes = spec["components"]["securitySchemes"]
    assert schemes["ApiKeyAuth"]["name"] == "X-Api-Key"
    assert schemes["AdminKeyAuth"]["name"] == "X-Admin-Key"
