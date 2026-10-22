"""T-230: журнал `integration_calls` в настоящем Postgres — отдельная транзакция, маска ИНН, сбой не ломает вызов."""

# ruff: noqa: PT018 — короткие составные assert читаются лучше, чем разбитые
from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
from sqlalchemy import select, text

import app.db_models  # noqa: F401
from app.modules.integrations import IntegrationCall, IntegrationClient, Ok, build_integrations
from app.shared import db
from app.shared.db import migrate
from app.shared.settings import Settings

pytestmark = pytest.mark.integration

BANK = "http://mock-bank-core:8000/api/v1"
CUSTOMER = {
    "meta": {"source": "BANK_CORE", "simulated": True, "requestId": "req_1"},
    "customerId": "cus_1",
    "inn": "001234567887",
    "type": "INDIVIDUAL_ENTREPRENEUR",
    "name": "ИП Соколова Анна Сергеевна",
    "customerSince": "2023-05-02",
    "accounts": [],
}


@pytest.fixture
def database(postgres_url: str) -> Iterator[db.Database]:
    database = db.configure(postgres_url)
    migrate(database.engine)
    with database.transaction() as session:
        session.execute(text("DELETE FROM integration_calls"))
    yield database
    database.dispose()


@pytest.fixture
def router() -> Iterator[Any]:
    with respx.mock(assert_all_called=False) as router:
        yield router


def rows(database: db.Database) -> list[IntegrationCall]:
    with database.transaction() as session:
        return list(session.scalars(select(IntegrationCall).order_by(IntegrationCall.id)))


def test_every_attempt_is_written_with_masked_inn(database: db.Database, router: Any) -> None:
    route = router.get(f"{BANK}/customers/001234567887")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=CUSTOMER)]
    application_id = uuid4()
    adapters = build_integrations(IntegrationClient(Settings()))
    result = adapters.bank_core.get_customer("001234567887", application_id=application_id)
    assert isinstance(result, Ok)

    first, second = rows(database)
    assert (first.attempt, first.status_code, first.error_code) == (1, 503, "HTTP_5XX")
    assert (second.attempt, second.status_code, second.error_code) == (2, 200, None)
    for row in (first, second):
        assert row.system == "bank_core" and row.method == "GET"
        assert row.path == "/api/v1/customers/0012******87"
        assert row.subject_inn_masked == "0012******87"
        assert row.circuit_state == "CLOSED"
        assert row.application_id == application_id
        assert row.request_id and row.request_id.startswith("req_")
        assert row.duration_ms >= 0
    assert first.request_id == second.request_id  # одна цепочка вызова


def test_log_survives_rollback_of_the_callers_transaction(
    database: db.Database, router: Any
) -> None:
    router.get(f"{BANK}/customers/001234567887").mock(
        return_value=httpx.Response(200, json=CUSTOMER)
    )
    adapters = build_integrations(IntegrationClient(Settings()))

    def scenario() -> None:
        with db.transaction():
            adapters.bank_core.get_customer("001234567887")
            raise RuntimeError("откат основной транзакции")

    with pytest.raises(RuntimeError, match="откат"):
        scenario()
    assert len(rows(database)) == 1


def test_unreachable_database_does_not_break_the_call(router: Any) -> None:
    db.configure(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    router.get(f"{BANK}/customers/001234567887").mock(
        return_value=httpx.Response(200, json=CUSTOMER)
    )
    adapters = build_integrations(IntegrationClient(Settings()))
    assert isinstance(adapters.bank_core.get_customer("001234567887"), Ok)
