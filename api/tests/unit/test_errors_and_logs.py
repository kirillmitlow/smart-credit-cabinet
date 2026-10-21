"""T-202: problem+json для любых ошибок, X-Request-Id, маскирование логов."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import structlog
from fastapi import FastAPI
from pydantic import BaseModel

from app.shared.errors import AppError, install_error_handlers
from app.shared.logs import configure_logging, mask_text, scrub_event
from app.shared.request_context import RequestContextMiddleware

pytestmark = pytest.mark.unit


class Body(BaseModel):
    amount_rub: int


def build() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.post("/things")
    def create(body: Body) -> Body:
        return body

    @app.post("/conflict")
    def conflict() -> None:
        raise AppError(409, "INVALID_TRANSITION", "Переход из APPROVED в DRAFT запрещён")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("секретная подробность со стеком")

    return app


@pytest.fixture
def client() -> Iterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=build(), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://api")


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("POST", "/things", 422, "VALIDATION_ERROR"),
        ("GET", "/missing", 404, "NOT_FOUND"),
        ("POST", "/conflict", 409, "INVALID_TRANSITION"),
        ("GET", "/boom", 500, "INTERNAL_ERROR"),
        ("GET", "/things", 405, "METHOD_NOT_ALLOWED"),
    ],
)
async def test_every_error_is_problem_json(
    client: httpx.AsyncClient, method: str, path: str, status: int, code: str
) -> None:
    response = await client.request(
        method, path, json={"amountRub": "x"}, headers={"X-Request-Id": "req_t"}
    )
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == code
    assert body["requestId"] == "req_t"
    assert "секретная" not in response.text


async def test_request_id_generated_and_instance_id_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/missing")
    assert response.headers["X-Request-Id"].startswith("req_")
    assert response.headers["X-Instance-Id"]


def test_mask_text_hides_inn_and_accounts() -> None:
    text = "ИНН 0017654322, ИП 001234567887, счёт 40802810800000001234"
    masked = mask_text(text)
    assert "0017****22" in masked
    assert "0012******87" in masked
    assert "40802810800000001234" not in masked


def test_scrub_drops_sensitive_fields_recursively() -> None:
    event = {
        "event": "login 001234567887",
        "fullName": "Соколова Анна Сергеевна",
        "user": {"last_name": "Соколова", "inn": "001234567887", "otp_code": "123456"},
        "password": "x",
        "account_number": "40802810800000001234",
    }
    scrubbed = scrub_event(None, "info", dict(event))
    dump = json.dumps(scrubbed, ensure_ascii=False)
    for secret in ("Соколова", "001234567887", "123456", "40802810800000001234"):
        assert secret not in dump


def test_configured_logger_writes_masked_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("api-test")
    structlog.get_logger("t").info("check", inn="0017654322", fio="Иванов Иван")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["service"] == "api-test"
    assert record["inn"] == "0017****22"
    assert record["fio"] == "[скрыто]"
    assert {"ts", "level", "msg"} <= set(record)
