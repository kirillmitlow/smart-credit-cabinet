"""T-115..T-118 (интеграция): mock-bank-core по разделам 7 и 8.3 на живом Postgres."""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.chaos import LostResponseError
from app.common.accounts import SETTLEMENT_IP, account_is_valid, make_account
from app.common.clock import Clock
from app.common.inn import generate_inn
from app.main import create_app
from tests.conftest import ADMIN_KEY, API_KEY, database_url, make_settings

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 21)
BIK = "040000999"
SOKOLOVA = "001234567887"
GARIPOV = generate_inn(random.Random(7), individual=True)
ROMASHKA = generate_inn(random.Random(3))
DIRECTOR = generate_inn(random.Random(11), individual=True)
OTHER = generate_inn(random.Random(12), individual=True)

API = {"X-Api-Key": API_KEY}
ADMIN = {"X-Admin-Key": ADMIN_KEY}


@pytest.fixture(scope="module")
def bank_url(postgres_url: str) -> str:
    return database_url(postgres_url, "mock_bank_core_test")


@pytest.fixture
async def app(bank_url: str) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(mock_role="bank_core", database_url=bank_url, app_today=TODAY))
    await app.state.database.migrate()
    yield app
    await app.state.database.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock", headers=API) as c:
        wiped = await c.post("/admin/wipe", headers=ADMIN)
        assert wiped.status_code == 204
        yield c


# ---- данные ----


def sokolova_body(**overrides: Any) -> dict[str, Any]:
    """Пример 8.3: ИП Соколова, один расчётный счёт и сентябрьские обороты."""
    body: dict[str, Any] = {
        "customer": {
            "type": "INDIVIDUAL_ENTREPRENEUR",
            "name": "ИП Соколова Анна Сергеевна",
            "customerSince": "2023-05-02",
        },
        "accounts": [
            {"type": "SETTLEMENT", "status": "OPEN", "openedAt": "2023-05-02", "balanceRub": 412300}
        ],
        "turnover": [
            {
                "month": "2026-09",
                "incomingRub": 912000,
                "incomingNetRub": 905000,
                "outgoingRub": 790000,
                "counterpartiesIn": 2,
                "counterpartiesOut": 25,
            }
        ],
        "loans": [],
        "compliance": {
            "aml": None,
            "zsk": {"riskLevel": "GREEN", "assessedAt": "2026-10-01"},
            "internalStopList": None,
        },
    }
    body.update(overrides)
    return body


def turnover_row(month: str) -> dict[str, Any]:
    return {
        "month": month,
        "incomingRub": 100,
        "incomingNetRub": 90,
        "outgoingRub": 80,
        "counterpartiesIn": 1,
        "counterpartiesOut": 2,
    }


def loan_body(ref: str = "APP-OLD-1", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "applicationRef": ref,
        "contractNumber": f"КД-{ref}",
        "contractUid": f"uid-{ref}",
        "productCode": "EXPRESS",
        "kind": "LOAN",
        "amountRub": 300000,
        "limitRub": None,
        "termMonths": 24,
        "ratePercent": 21.0,
        "repaymentType": "ANNUITY",
        "status": "ACTIVE",
        "disbursedAt": "2026-01-15",
    }
    body.update(overrides)
    return body


async def put_subject(
    client: httpx.AsyncClient, inn: str, body: dict[str, Any], scenario: str | None = "test"
) -> httpx.Response:
    headers = dict(ADMIN)
    if scenario:
        headers["X-Scenario-Code"] = scenario
    # Бизнес-ключ в заголовках клиента не мешает: админ-ключ проверяется отдельно
    response = await client.put(f"/admin/subjects/{inn}", json=body, headers=headers)
    assert response.status_code in (200, 201), response.text
    return response


async def settlement_number(client: httpx.AsyncClient, inn: str) -> str:
    customer = await client.get(f"/api/v1/customers/{inn}")
    number: str = customer.json()["accounts"][0]["number"]
    return number


def disbursement(account: str, ref: str = "APP-2026-000123", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "applicationRef": ref,
        "customerInn": SOKOLOVA,
        "contract": {
            "number": f"КД-{ref}",
            "uid": f"6f1c2a8e-{ref}-4",
            "signedAt": "2026-10-20T10:01:00Z",
        },
        "product": {"code": "EXPRESS", "name": "Экспресс-кредит"},
        "kind": "LOAN",
        "amountRub": 500000,
        "limitRub": None,
        "termMonths": 12,
        "ratePercent": 24.0,
        "repaymentType": "ANNUITY",
        "settlementAccount": account,
    }
    body.update(overrides)
    return body


def idem(key: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": key or f"k-{uuid.uuid4()}"}


async def disburse(
    client: httpx.AsyncClient, body: dict[str, Any], key: str | None = None, **headers: str
) -> httpx.Response:
    return await client.post("/api/v1/disbursements", json=body, headers={**idem(key), **headers})


async def balance(client: httpx.AsyncClient, number: str) -> int:
    response = await client.get(f"/api/v1/accounts/{number}")
    assert response.status_code == 200
    value: int = response.json()["balanceRub"]
    return value


async def loans_of(client: httpx.AsyncClient, inn: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/customers/{inn}/loans")
    assert response.status_code == 200
    loans: list[dict[str, Any]] = response.json()["loans"]
    return loans


# ---- номера счетов из примеров спецификации ----


def test_spec_account_examples_have_valid_keys() -> None:
    assert make_account(BIK, SETTLEMENT_IP, 1234) == "40802810800000001234"
    assert make_account(BIK, "45406", 41) == "45406810000000000041"


# ---- T-115: чтение ----


async def test_sokolova_admin_example_round_trips_to_reads(client: httpx.AsyncClient) -> None:
    created = await put_subject(client, SOKOLOVA, sokolova_body())
    assert created.status_code == 201
    assert created.json()["scenarioCode"] == "test"

    customer = (await client.get(f"/api/v1/customers/{SOKOLOVA}")).json()
    assert customer["meta"]["source"] == "BANK_CORE"
    assert customer["meta"]["simulated"] is True
    assert customer["customerId"].startswith("cus_")
    assert customer["inn"] == SOKOLOVA
    assert customer["type"] == "INDIVIDUAL_ENTREPRENEUR"
    assert customer["name"] == "ИП Соколова Анна Сергеевна"
    assert customer["customerSince"] == "2023-05-02"
    [account] = customer["accounts"]
    assert account["type"] == "SETTLEMENT"
    assert account["currency"] == "RUB"
    assert account["status"] == "OPEN"
    assert account["balanceRub"] == 412300
    assert account["openedAt"] == "2023-05-02"
    assert account["number"].startswith("40802")
    assert account_is_valid(BIK, account["number"])

    turnover = (await client.get(f"/api/v1/customers/{SOKOLOVA}/turnover")).json()
    assert turnover["accountNumbers"] == [account["number"]]
    assert turnover["months"] == [
        {
            "month": "2026-09",
            "incomingRub": 912000,
            "incomingNetRub": 905000,
            "outgoingRub": 790000,
            "counterpartiesIn": 2,
            "counterpartiesOut": 25,
        }
    ]
    assert await loans_of(client, SOKOLOVA) == []


async def test_given_account_number_is_kept(client: httpx.AsyncClient) -> None:
    body = sokolova_body()
    body["accounts"][0]["number"] = "40802810800000001234"
    await put_subject(client, SOKOLOVA, body)
    assert await settlement_number(client, SOKOLOVA) == "40802810800000001234"


async def test_not_a_customer_is_404(client: httpx.AsyncClient) -> None:
    for path in ("", "/turnover", "/loans"):
        response = await client.get(f"/api/v1/customers/{GARIPOV}{path}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "CUSTOMER_NOT_FOUND"


async def test_invalid_inn_is_400_and_key_is_required(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/customers/123")
    assert (response.status_code, response.json()["code"]) == (400, "INN_INVALID")
    anonymous = await client.get(f"/api/v1/customers/{SOKOLOVA}", headers={"X-Api-Key": "nope"})
    assert anonymous.status_code == 401
    admin_on_business = await client.get(
        f"/api/v1/customers/{SOKOLOVA}", headers={"X-Api-Key": ADMIN_KEY}
    )
    assert admin_on_business.status_code == 403


async def test_turnover_months_range_is_validated(client: httpx.AsyncClient) -> None:
    await put_subject(client, SOKOLOVA, sokolova_body())
    for months in (0, 25, -1):
        response = await client.get(f"/api/v1/customers/{SOKOLOVA}/turnover?months={months}")
        assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_ERROR")
    for months in (1, 24):
        response = await client.get(f"/api/v1/customers/{SOKOLOVA}/turnover?months={months}")
        assert response.status_code == 200


def month_list(first: str, count: int) -> list[str]:
    year, month = int(first[:4]), int(first[5:])
    result = []
    for i in range(count):
        index = year * 12 + month - 1 + i
        result.append(f"{index // 12}-{index % 12 + 1:02d}")
    return result


async def test_turnover_window_follows_the_clock(app: FastAPI, client: httpx.AsyncClient) -> None:
    # 2024-09 (старше окна 24 мес.), 2024-10…2026-09 и текущий неполный 2026-10
    months = month_list("2024-09", 26)
    body = sokolova_body(turnover=[turnover_row(m) for m in months])
    await put_subject(client, SOKOLOVA, body)

    def window(response: httpx.Response) -> list[str]:
        return [m["month"] for m in response.json()["months"]]

    path = f"/api/v1/customers/{SOKOLOVA}/turnover"
    default = window(await client.get(path))
    assert default == month_list("2025-10", 12)  # 12 по умолчанию, последний полный — 2026-09
    assert window(await client.get(f"{path}?months=3")) == ["2026-07", "2026-08", "2026-09"]
    assert window(await client.get(f"{path}?months=24")) == month_list("2024-10", 24)

    app.state.clock = Clock(
        date(2026, 12, 5)
    )  # последний полный месяц — 2026-11, данных до 2026-10
    assert window(await client.get(f"{path}?months=3")) == ["2026-09", "2026-10"]
    app.state.clock = Clock(date(2026, 10, 1))  # 2026-10 ещё не закончился даже в первый день
    assert window(await client.get(f"{path}?months=1")) == ["2026-09"]


async def test_new_customer_has_only_months_since_service_start(client: httpx.AsyncClient) -> None:
    # «Быстрый старт»: обслуживается три месяца, обороты в данных — и до начала обслуживания
    body = sokolova_body(turnover=[turnover_row(m) for m in month_list("2026-04", 6)])
    body["customer"]["customerSince"] = "2026-07-01"
    body["accounts"][0]["openedAt"] = "2026-07-01"
    await put_subject(client, SOKOLOVA, body)
    response = await client.get(f"/api/v1/customers/{SOKOLOVA}/turnover?months=12")
    assert [m["month"] for m in response.json()["months"]] == ["2026-07", "2026-08", "2026-09"]


async def test_blocked_account_is_visible_on_customer(client: httpx.AsyncClient) -> None:
    body = sokolova_body()
    body["accounts"][0]["status"] = "BLOCKED"
    await put_subject(client, SOKOLOVA, body)
    customer = (await client.get(f"/api/v1/customers/{SOKOLOVA}")).json()
    assert customer["accounts"][0]["status"] == "BLOCKED"


async def test_scenario_loan_gets_loan_account_and_uid(client: httpx.AsyncClient) -> None:
    uid = "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4"
    loan = loan_body(contractUid=uid)
    await put_subject(client, SOKOLOVA, sokolova_body(loans=[loan]))
    settlement = await settlement_number(client, SOKOLOVA)

    [got] = await loans_of(client, SOKOLOVA)
    assert got["contractUid"] == uid
    assert got["contractNumber"] == "КД-APP-OLD-1"
    assert got["applicationRef"] == "APP-OLD-1"
    assert got["outstandingRub"] == got["amountRub"] == 300000
    assert got["status"] == "ACTIVE"
    assert got["disbursedAt"] == "2026-01-15"
    assert got["settlementAccount"] == settlement
    assert got["loanAccount"].startswith("45406")
    assert account_is_valid(BIK, got["loanAccount"])
    assert got["loanId"].startswith("loan_")

    one = (await client.get(f"/api/v1/loans/{got['loanId']}")).json()
    assert one["meta"]["source"] == "BANK_CORE"
    assert {k: v for k, v in one.items() if k != "meta"} == got

    account = (await client.get(f"/api/v1/accounts/{got['loanAccount']}")).json()
    assert account["type"] == "LOAN"
    assert account["balanceRub"] == 300000
    assert account["recentPostings"] == []


async def test_loan_and_account_not_found(client: httpx.AsyncClient) -> None:
    for loan_id in ("loan_999999", "garbage"):
        response = await client.get(f"/api/v1/loans/{loan_id}")
        assert (response.status_code, response.json()["code"]) == (404, "LOAN_NOT_FOUND")
    response = await client.get("/api/v1/accounts/40802810800000009999")
    assert (response.status_code, response.json()["code"]) == (404, "ACCOUNT_NOT_FOUND")
    response = await client.get("/api/v1/accounts/123")
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_ERROR")


# ---- T-116: выдача ----


async def prepared(client: httpx.AsyncClient) -> str:
    await put_subject(client, SOKOLOVA, sokolova_body())
    return await settlement_number(client, SOKOLOVA)


async def test_disbursement_moves_money_once_and_replays(client: httpx.AsyncClient) -> None:
    account = await prepared(client)
    body = disbursement(account)
    key = "key-1"
    first = await disburse(client, body, key)
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["status"] == "COMPLETED"
    assert data["disbursementId"].startswith("dsb_")
    assert data["settlementAccount"] == account
    assert data["amountRub"] == 500000
    assert data["valueDate"] == "2026-10-21"
    assert data["settlementBalanceRub"] == 412300 + 500000
    assert data["loanAccount"].startswith("45406")
    assert account_is_valid(BIK, data["loanAccount"])
    # серийный номер ссудного счёта — номер кредита (loan_000041 → ...0041)
    assert int(data["loanAccount"][-7:]) == int(data["loanId"].removeprefix("loan_"))
    [posting] = data["postings"]
    assert posting["debit"] == data["loanAccount"]
    assert posting["credit"] == account
    assert posting["amountRub"] == 500000
    assert posting["purpose"] == (
        "Выдача кредита по договору № КД-APP-2026-000123 от 20.10.2026. НДС не облагается"
    )

    replay = await disburse(client, body, key)
    assert replay.status_code == 201
    assert replay.json() == data
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert await balance(client, account) == 912300

    [loan] = await loans_of(client, SOKOLOVA)
    assert loan["loanId"] == data["loanId"]
    assert loan["outstandingRub"] == loan["amountRub"] == 500000
    assert loan["contractUid"] == body["contract"]["uid"]
    assert loan["status"] == "ACTIVE"
    assert loan["disbursedAt"] == "2026-10-21"

    # проводки сходятся: списание ссудного счёта = зачисление на расчётный
    loan_account = (await client.get(f"/api/v1/accounts/{data['loanAccount']}")).json()
    settlement = (await client.get(f"/api/v1/accounts/{account}")).json()
    assert loan_account["balanceRub"] == 500000
    assert loan_account["recentPostings"] == settlement["recentPostings"]
    assert settlement["recentPostings"][0]["amountRub"] == 500000
    assert settlement["recentPostings"][0]["valueDate"] == "2026-10-21"


async def test_parallel_identical_requests_pay_out_exactly_once(
    client: httpx.AsyncClient,
) -> None:
    account = await prepared(client)
    body = disbursement(account)
    responses = await asyncio.gather(*(disburse(client, body, "same-key") for _ in range(5)))
    for r in responses:
        assert r.status_code in (201, 409), r.text
        if r.status_code == 409:
            assert r.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
            assert r.headers["Retry-After"] == "1"
    created = [
        r for r in responses if r.status_code == 201 and "Idempotent-Replayed" not in r.headers
    ]
    assert len(created) == 1
    assert len(await loans_of(client, SOKOLOVA)) == 1
    assert await balance(client, account) == 912300
    # тот, кому не повезло, повторяет и получает сохранённый результат
    again = await disburse(client, body, "same-key")
    assert again.status_code == 201
    assert again.json() == created[0].json()
    assert again.headers["Idempotent-Replayed"] == "true"
    settlement = (await client.get(f"/api/v1/accounts/{account}")).json()
    assert len(settlement["recentPostings"]) == 1


async def test_other_key_for_same_application_is_already_disbursed(
    client: httpx.AsyncClient,
) -> None:
    account = await prepared(client)
    body = disbursement(account)
    assert (await disburse(client, body, "first")).status_code == 201
    second = await disburse(client, body, "second")
    assert (second.status_code, second.json()["code"]) == (409, "ALREADY_DISBURSED")
    assert "Idempotent-Replayed" not in second.headers
    # даже с другим телом, но той же заявкой, и с другой заявкой, но тем же договором
    changed = await disburse(client, disbursement(account, amountRub=100000), "third")
    assert changed.json()["code"] == "ALREADY_DISBURSED"
    same_contract = disbursement(account, ref="APP-OTHER")
    same_contract["contract"]["uid"] = body["contract"]["uid"]
    assert (await disburse(client, same_contract, "fourth")).json()["code"] == "ALREADY_DISBURSED"
    assert len(await loans_of(client, SOKOLOVA)) == 1
    assert await balance(client, account) == 912300


async def test_parallel_requests_with_different_keys_cannot_double_pay(
    client: httpx.AsyncClient,
) -> None:
    account = await prepared(client)
    body = disbursement(account)
    responses = await asyncio.gather(*(disburse(client, body, f"race-{i}") for i in range(5)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409, 409], [r.text for r in responses]
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {"ALREADY_DISBURSED"}
    assert len(await loans_of(client, SOKOLOVA)) == 1
    assert await balance(client, account) == 912300


async def test_parallel_different_applications_all_credit_the_account(
    client: httpx.AsyncClient,
) -> None:
    account = await prepared(client)
    bodies = [disbursement(account, ref=f"APP-{i}", amountRub=100000) for i in range(4)]
    responses = await asyncio.gather(*(disburse(client, b) for b in bodies))
    assert [r.status_code for r in responses] == [201] * 4
    assert await balance(client, account) == 412300 + 400000
    assert len({r.json()["loanId"] for r in responses}) == 4


async def test_same_key_with_other_body_is_rejected(client: httpx.AsyncClient) -> None:
    account = await prepared(client)
    assert (await disburse(client, disbursement(account), "k")).status_code == 201
    other = await disburse(client, disbursement(account, amountRub=1000), "k")
    assert (other.status_code, other.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")


async def test_lost_response_then_retry_returns_stored_result(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    account = await prepared(client)
    body = disbursement(account)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock", headers=API) as lossy:
        with pytest.raises(LostResponseError):
            await disburse(lossy, body, "lost", **{"X-Mock-Scenario": "LOST_RESPONSE"})
    # данные записаны, клиент ответа не получил
    assert len(await loans_of(client, SOKOLOVA)) == 1
    assert await balance(client, account) == 912300

    retry = await disburse(client, body, "lost")
    assert retry.status_code == 201
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert retry.json()["settlementBalanceRub"] == 912300
    assert len(await loans_of(client, SOKOLOVA)) == 1
    assert await balance(client, account) == 912300
    # и новый ключ тоже не задвоит выдачу
    assert (await disburse(client, body, "lost-2")).json()["code"] == "ALREADY_DISBURSED"


async def test_idempotency_key_is_required(client: httpx.AsyncClient) -> None:
    account = await prepared(client)
    response = await client.post("/api/v1/disbursements", json=disbursement(account))
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_ERROR")
    assert await loans_of(client, SOKOLOVA) == []


async def test_disbursement_error_codes(client: httpx.AsyncClient) -> None:
    account = await prepared(client)

    unknown = await disburse(client, disbursement(account, customerInn=GARIPOV))
    assert (unknown.status_code, unknown.json()["code"]) == (404, "CUSTOMER_NOT_FOUND")

    bad_inn = await disburse(client, disbursement(account, customerInn="123"))
    assert (bad_inn.status_code, bad_inn.json()["code"]) == (400, "INN_INVALID")

    # чужой счёт: он существует, но принадлежит другому клиенту
    await put_subject(client, OTHER, sokolova_body(customer={**sokolova_body()["customer"]}))
    foreign = await settlement_number(client, OTHER)
    not_owned = await disburse(client, disbursement(foreign, ref="APP-FOREIGN"))
    assert (not_owned.status_code, not_owned.json()["code"]) == (409, "ACCOUNT_NOT_OWNED")
    ghost = await disburse(client, disbursement("40802810800000009999", ref="APP-GHOST"))
    assert ghost.json()["code"] == "ACCOUNT_NOT_OWNED"
    assert await balance(client, foreign) == 412300

    blocked_body = sokolova_body()
    blocked_body["accounts"][0]["status"] = "BLOCKED"
    await put_subject(client, SOKOLOVA, blocked_body)
    blocked = await disburse(client, disbursement(await settlement_number(client, SOKOLOVA)))
    assert (blocked.status_code, blocked.json()["code"]) == (409, "ACCOUNT_BLOCKED")
    assert await loans_of(client, SOKOLOVA) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"amountRub": 0},
        {"amountRub": -5},
        {"termMonths": 0},
        {"limitRub": 100000},
        {"repaymentType": "REVOLVING"},
        {"kind": "CREDIT_LINE", "limitRub": None, "repaymentType": "REVOLVING"},
        {"kind": "CREDIT_LINE", "limitRub": 100, "amountRub": 500, "repaymentType": "REVOLVING"},
        {"kind": "OVERDRAFT", "limitRub": 100000, "repaymentType": "ANNUITY", "amountRub": 0},
        {"kind": "NOPE"},
        {"settlementAccount": "123"},
    ],
)
async def test_disbursement_validation_is_422_and_releases_key(
    client: httpx.AsyncClient, overrides: dict[str, Any]
) -> None:
    account = await prepared(client)
    response = await disburse(client, disbursement(account, **overrides), "bad")
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_ERROR")
    assert await loans_of(client, SOKOLOVA) == []
    # ошибка не занимает ключ: исправленный запрос с тем же ключом проходит
    assert (await disburse(client, disbursement(account), "bad")).status_code == 201


async def test_business_error_releases_the_key(client: httpx.AsyncClient) -> None:
    account = await prepared(client)
    missing = await disburse(client, disbursement(account, customerInn=GARIPOV), "retry")
    assert missing.status_code == 404
    fixed = await disburse(client, disbursement(account), "retry")
    assert fixed.status_code == 201


async def test_credit_line_and_overdraft_open_limit_only(client: httpx.AsyncClient) -> None:
    account = await prepared(client)
    line = await disburse(
        client,
        disbursement(
            account,
            ref="APP-LINE",
            kind="CREDIT_LINE",
            amountRub=0,
            limitRub=1_000_000,
            repaymentType="REVOLVING",
        ),
    )
    assert line.status_code == 201, line.text
    assert line.json()["postings"] == []
    assert line.json()["settlementBalanceRub"] == 412300
    overdraft = await disburse(
        client,
        disbursement(
            account,
            ref="APP-OD",
            kind="OVERDRAFT",
            amountRub=0,
            limitRub=200_000,
            repaymentType="REVOLVING",
        ),
    )
    assert overdraft.status_code == 201
    loans = {x["applicationRef"]: x for x in await loans_of(client, SOKOLOVA)}
    assert loans["APP-LINE"]["kind"] == "CREDIT_LINE"
    assert loans["APP-LINE"]["limitRub"] == 1_000_000
    assert loans["APP-LINE"]["outstandingRub"] == 0
    assert loans["APP-OD"]["kind"] == "OVERDRAFT"
    assert await balance(client, account) == 412300


async def test_chaos_error_before_handler_stores_nothing(
    client: httpx.AsyncClient,
) -> None:
    account = await prepared(client)
    body = disbursement(account)
    failed = await disburse(client, body, "k", **{"X-Mock-Scenario": "ERROR"})
    assert failed.status_code == 503
    assert await loans_of(client, SOKOLOVA) == []
    assert (await disburse(client, body, "k")).status_code == 201


# ---- T-117: открытие счёта ----


def open_body(inn_type: str = "INDIVIDUAL_ENTREPRENEUR", name: str = "ИП Гарипов Рустам") -> Any:
    return {"type": "SETTLEMENT", "currency": "RUB", "customer": {"type": inn_type, "name": name}}


async def open_account(
    client: httpx.AsyncClient, inn: str, body: dict[str, Any], key: str | None = None
) -> httpx.Response:
    return await client.post(f"/api/v1/customers/{inn}/accounts", json=body, headers=idem(key))


async def test_open_account_creates_customer_and_allows_disbursement(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get(f"/api/v1/customers/{GARIPOV}")).status_code == 404
    opened = await open_account(client, GARIPOV, open_body(), "open-1")
    assert opened.status_code == 201, opened.text
    data = opened.json()
    assert data["meta"]["source"] == "BANK_CORE"
    assert data["type"] == "SETTLEMENT"
    assert data["currency"] == "RUB"
    assert data["status"] == "OPEN"
    assert data["balanceRub"] == 0
    assert data["openedAt"] == "2026-10-21"
    assert data["number"].startswith("40802")
    assert account_is_valid(BIK, data["number"])

    customer = (await client.get(f"/api/v1/customers/{GARIPOV}")).json()
    assert customer["customerSince"] == "2026-10-21"
    assert customer["name"] == "ИП Гарипов Рустам"
    assert [a["number"] for a in customer["accounts"]] == [data["number"]]
    assert customer["customerId"] == data["customerId"]

    paid = await disburse(
        client, disbursement(data["number"], customerInn=GARIPOV, amountRub=200000)
    )
    assert paid.status_code == 201
    assert paid.json()["settlementBalanceRub"] == 200000


async def test_open_account_replay_and_second_account_conflict(client: httpx.AsyncClient) -> None:
    first = await open_account(client, GARIPOV, open_body(), "open-1")
    replay = await open_account(client, GARIPOV, open_body(), "open-1")
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"

    again = await open_account(client, GARIPOV, open_body(), "open-2")
    assert (again.status_code, again.json()["code"]) == (409, "ACCOUNT_ALREADY_EXISTS")
    customer = (await client.get(f"/api/v1/customers/{GARIPOV}")).json()
    assert len(customer["accounts"]) == 1

    other = await open_account(client, GARIPOV, open_body(name="ИП Другой"), "open-1")
    assert (other.status_code, other.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")


async def test_open_account_key_is_scoped_to_customer(client: httpx.AsyncClient) -> None:
    other_inn = generate_inn(random.Random(21), individual=True)
    first = await open_account(client, GARIPOV, open_body(), "shared-key")
    second = await open_account(client, other_inn, open_body(), "shared-key")
    assert second.status_code == 201
    assert "Idempotent-Replayed" not in second.headers
    assert second.json()["number"] != first.json()["number"]


async def test_parallel_open_account_creates_one_account(client: httpx.AsyncClient) -> None:
    responses = await asyncio.gather(
        *(open_account(client, GARIPOV, open_body(), f"open-{i}") for i in range(5))
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409, 409], [r.text for r in responses]
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {
        "ACCOUNT_ALREADY_EXISTS"
    }
    customer = (await client.get(f"/api/v1/customers/{GARIPOV}")).json()
    assert len(customer["accounts"]) == 1


async def test_open_account_for_legal_entity_and_existing_customer(
    client: httpx.AsyncClient,
) -> None:
    legal = await open_account(client, ROMASHKA, open_body("LEGAL_ENTITY", "ООО Ромашка"))
    assert legal.json()["number"].startswith("40702")

    # клиент без расчётного счёта (все закрыты): новый счёт открывается, customer не нужен
    body = sokolova_body()
    body["accounts"][0]["status"] = "CLOSED"
    await put_subject(client, SOKOLOVA, body)
    reopened = await open_account(client, SOKOLOVA, {"type": "SETTLEMENT", "currency": "RUB"})
    assert reopened.status_code == 201
    assert reopened.json()["number"].startswith("40802")


async def test_open_account_validation(client: httpx.AsyncClient) -> None:
    no_key = await client.post(f"/api/v1/customers/{GARIPOV}/accounts", json=open_body())
    assert (no_key.status_code, no_key.json()["code"]) == (422, "VALIDATION_ERROR")
    no_customer = await open_account(client, GARIPOV, {"type": "SETTLEMENT", "currency": "RUB"})
    assert (no_customer.status_code, no_customer.json()["code"]) == (422, "VALIDATION_ERROR")
    wrong_type = await open_account(client, GARIPOV, open_body("LEGAL_ENTITY", "ООО"))
    assert wrong_type.status_code == 422
    wrong_currency = await open_account(client, GARIPOV, {**open_body(), "currency": "USD"})
    assert wrong_currency.status_code == 422
    bad_inn = await open_account(client, "123", open_body())
    assert (bad_inn.status_code, bad_inn.json()["code"]) == (400, "INN_INVALID")
    assert (await client.get(f"/api/v1/customers/{GARIPOV}")).status_code == 404


# ---- T-118: комплаенс ----


async def screen(client: httpx.AsyncClient, *subjects: tuple[str, str]) -> httpx.Response:
    return await client.post(
        "/api/v1/compliance/screening",
        json={"subjects": [{"inn": i, "role": r} for i, r in subjects]},
    )


async def test_screening_clean_subjects(client: httpx.AsyncClient) -> None:
    await put_subject(
        client,
        ROMASHKA,
        {"compliance": {"zsk": {"riskLevel": "GREEN", "assessedAt": "2026-10-01"}}},
    )
    response = await screen(
        client, (ROMASHKA, "COMPANY"), (DIRECTOR, "DIRECTOR"), (DIRECTOR, "FOUNDER")
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["meta"]["source"] == "COMPLIANCE"
    assert data["screeningId"].startswith("scr_")
    assert data["overall"] == "CLEAR"
    company, director, founder = data["results"]
    assert company == {
        "inn": ROMASHKA,
        "role": "COMPANY",
        "amlList": {"listed": False, "listName": None},
        "zsk": {"riskLevel": "GREEN", "assessedAt": "2026-10-01"},
        "internalStopList": {"listed": False, "reason": None},
    }
    assert director["role"] == "DIRECTOR"
    assert director["zsk"] is None
    assert director["amlList"] == {"listed": False, "listName": None}
    assert founder["role"] == "FOUNDER"


async def test_screening_hits_in_lists(client: httpx.AsyncClient) -> None:
    await put_subject(
        client,
        DIRECTOR,
        {
            "compliance": {
                "aml": {"listName": "ROSFINMONITORING_TERRORISM_EXTREMISM", "reason": "в перечне"},
                # у физлица рейтинг ЗСК не отдаётся, даже если он есть в справочнике
                "zsk": {"riskLevel": "RED", "assessedAt": "2026-09-01"},
            }
        },
    )
    await put_subject(
        client, ROMASHKA, {"compliance": {"internalStopList": {"reason": "мошенничество"}}}
    )
    response = await screen(
        client, (ROMASHKA, "COMPANY"), (DIRECTOR, "DIRECTOR"), (OTHER, "FOUNDER")
    )
    data = response.json()
    assert data["overall"] == "HIT"
    company, director, founder = data["results"]
    assert company["internalStopList"] == {"listed": True, "reason": "мошенничество"}
    assert company["amlList"]["listed"] is False
    assert director["amlList"] == {
        "listed": True,
        "listName": "ROSFINMONITORING_TERRORISM_EXTREMISM",
    }
    assert director["zsk"] is None
    assert founder["amlList"]["listed"] is False

    only_clean = await screen(client, (OTHER, "FOUNDER"))
    assert only_clean.json()["overall"] == "CLEAR"
    as_ie = await screen(client, (DIRECTOR, "IE"))
    assert as_ie.json()["results"][0]["zsk"] == {"riskLevel": "RED", "assessedAt": "2026-09-01"}


async def test_screening_works_for_non_customers_and_matches_admin_listing(
    client: httpx.AsyncClient,
) -> None:
    await put_subject(
        client, DIRECTOR, {"compliance": {"aml": {"listName": "MVK_FREEZE", "reason": None}}}
    )
    assert (await client.get(f"/api/v1/customers/{DIRECTOR}")).status_code == 404
    hit = (await screen(client, (DIRECTOR, "DIRECTOR"))).json()
    assert hit["results"][0]["amlList"]["listName"] == "MVK_FREEZE"
    stored = (await client.get(f"/admin/subjects/{DIRECTOR}", headers=ADMIN)).json()
    assert stored["data"]["compliance"]["aml"] == {"listName": "MVK_FREEZE", "reason": None}


async def test_screening_input_errors(client: httpx.AsyncClient) -> None:
    empty = await client.post("/api/v1/compliance/screening", json={"subjects": []})
    assert (empty.status_code, empty.json()["code"]) == (422, "VALIDATION_ERROR")
    no_body = await client.post("/api/v1/compliance/screening", json={})
    assert no_body.status_code == 422
    bad_role = await screen(client, (DIRECTOR, "BOSS"))
    assert bad_role.status_code == 422
    bad_inn = await screen(client, (DIRECTOR, "DIRECTOR"), ("1234567890", "COMPANY"))
    assert (bad_inn.status_code, bad_inn.json()["code"]) == (400, "INN_INVALID")
    assert "1234567890" in bad_inn.json()["detail"]


# ---- админ-API данных ----


async def test_admin_patch_keeps_loans_and_numbers(client: httpx.AsyncClient) -> None:
    await put_subject(client, SOKOLOVA, sokolova_body(loans=[loan_body()]))
    account = await settlement_number(client, SOKOLOVA)
    [before] = await loans_of(client, SOKOLOVA)
    runtime = await disburse(client, disbursement(account, ref="APP-RT"))
    assert runtime.status_code == 201

    # «Счёт заблокирован»: массив accounts заменяется целиком, номер остаётся прежним
    patch = {
        "accounts": [
            {"number": account, "status": "BLOCKED", "openedAt": "2023-05-02", "balanceRub": 5}
        ]
    }
    response = await client.patch(
        f"/admin/subjects/{SOKOLOVA}",
        content=json.dumps(patch),
        headers={**ADMIN, "Content-Type": "application/merge-patch+json"},
    )
    assert response.status_code == 200, response.text
    customer = (await client.get(f"/api/v1/customers/{SOKOLOVA}")).json()
    assert customer["accounts"][0]["status"] == "BLOCKED"
    assert customer["accounts"][0]["balanceRub"] == 5
    loans = {x["applicationRef"]: x for x in await loans_of(client, SOKOLOVA)}
    assert set(loans) == {"APP-OLD-1", "APP-RT"}
    assert loans["APP-OLD-1"]["loanId"] == before["loanId"]
    assert loans["APP-OLD-1"]["loanAccount"] == before["loanAccount"]
    assert loans["APP-RT"]["loanId"] == runtime.json()["loanId"]

    # вторая выдача по уже выданной заявке невозможна и после правки
    blocked = await disburse(client, disbursement(account, ref="APP-RT"))
    assert blocked.json()["code"] == "ALREADY_DISBURSED"


async def test_admin_view_shows_runtime_records(client: httpx.AsyncClient) -> None:
    account = await prepared(client)
    await disburse(client, disbursement(account))
    view = (await client.get(f"/admin/subjects/{SOKOLOVA}", headers=ADMIN)).json()
    assert view["scenarioCode"] == "test"
    assert view["origin"] == "SCENARIO"
    assert view["data"]["customer"]["name"] == "ИП Соколова Анна Сергеевна"
    assert [x["applicationRef"] for x in view["runtime"]["loans"]] == ["APP-2026-000123"]
    assert view["runtime"]["loans"][0]["origin"] == "RUNTIME"
    assert len(view["runtime"]["loanAccounts"]) == 1
    assert len(view["runtime"]["postings"]) == 1


async def test_admin_list_scenarios_delete_and_wipe(client: httpx.AsyncClient) -> None:
    await put_subject(client, SOKOLOVA, sokolova_body(), "alpha")
    await put_subject(
        client, DIRECTOR, {"compliance": {"aml": {"listName": "MVK_FREEZE"}}}, "alpha"
    )
    await put_subject(client, OTHER, sokolova_body(), "beta")
    runtime_only = await open_account(client, GARIPOV, open_body())
    assert runtime_only.status_code == 201

    listing = (await client.get("/admin/subjects?limit=10", headers=ADMIN)).json()
    assert listing["total"] == 4
    by_inn = {i["inn"]: i for i in listing["items"]}
    assert by_inn[SOKOLOVA]["title"] == "ИП Соколова Анна Сергеевна"
    assert by_inn[DIRECTOR]["title"] is None
    assert by_inn[GARIPOV]["origin"] == "RUNTIME"
    only_alpha = (await client.get("/admin/subjects?scenario=alpha", headers=ADMIN)).json()
    assert only_alpha["total"] == 2
    runtime_list = (await client.get("/admin/subjects?origin=RUNTIME", headers=ADMIN)).json()
    assert [i["inn"] for i in runtime_list["items"]] == [GARIPOV]
    scenarios = (await client.get("/admin/scenarios", headers=ADMIN)).json()
    assert scenarios == [
        {"scenarioCode": "alpha", "subjects": 2},
        {"scenarioCode": "beta", "subjects": 1},
    ]

    deleted = await client.delete("/admin/scenarios/alpha", headers=ADMIN)
    assert deleted.json() == {"deleted": 2}
    assert (await client.get(f"/api/v1/customers/{SOKOLOVA}")).status_code == 404
    assert (await screen(client, (DIRECTOR, "DIRECTOR"))).json()["overall"] == "CLEAR"

    assert (await client.delete(f"/admin/subjects/{GARIPOV}", headers=ADMIN)).status_code == 204
    missing = await client.delete(f"/admin/subjects/{GARIPOV}", headers=ADMIN)
    assert (missing.status_code, missing.json()["code"]) == (404, "SUBJECT_NOT_FOUND")

    assert (await client.post("/admin/wipe", headers=ADMIN)).status_code == 204
    assert (await client.get("/admin/subjects", headers=ADMIN)).json()["total"] == 0


async def test_wipe_also_forgets_idempotency_keys(client: httpx.AsyncClient) -> None:
    account = await prepared(client)
    assert (await disburse(client, disbursement(account), "k")).status_code == 201
    await client.post("/admin/wipe", headers=ADMIN)
    account = await prepared(client)
    again = await disburse(client, disbursement(account), "k")
    assert again.status_code == 201
    assert "Idempotent-Replayed" not in again.headers


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda b: b.update(customer=None), "только у клиента"),
        (lambda b: b["customer"].update(type="LEGAL_ENTITY"), "10 цифр"),
        (lambda b: b["accounts"][0].update(number="40802810800000001235"), "неверный ключ"),
        (lambda b: b["accounts"][0].update(number="40702810600000001234"), "не 40802"),
        (lambda b: b.update(accounts=[]) or b.update(loans=[loan_body()]), "добавьте accounts"),
        (lambda b: b.update(loans=[loan_body(), loan_body()]), "Повторяются"),
        (lambda b: b.update(turnover=[turnover_row("2026-09")] * 2), "Повторяются"),
        (lambda b: b.update(loans=[loan_body(kind="CREDIT_LINE")]), "limitRub"),
        (
            lambda b: b.update(loans=[loan_body(settlementAccount="40802810800000001234")]),
            "accounts[].number",
        ),
        (lambda b: b["turnover"][0].update(month="2026-13"), "month"),
    ],
)
async def test_admin_body_validation(client: httpx.AsyncClient, mutate: Any, fragment: str) -> None:
    body = sokolova_body()
    mutate(body)
    response = await client.put(f"/admin/subjects/{SOKOLOVA}", json=body, headers=ADMIN)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert fragment in response.text


async def test_admin_rejects_loan_or_account_of_another_customer(
    client: httpx.AsyncClient,
) -> None:
    await put_subject(client, SOKOLOVA, sokolova_body(loans=[loan_body()]))
    clash = await client.put(
        f"/admin/subjects/{OTHER}", json=sokolova_body(loans=[loan_body()]), headers=ADMIN
    )
    assert (clash.status_code, clash.json()["code"]) == (422, "VALIDATION_ERROR")
    number = await settlement_number(client, SOKOLOVA)
    body = sokolova_body()
    body["accounts"][0]["number"] = number
    taken = await client.put(f"/admin/subjects/{OTHER}", json=body, headers=ADMIN)
    assert taken.status_code == 422
    # неудачная замена ничего не сломала у первого клиента
    assert len(await loans_of(client, SOKOLOVA)) == 1


async def test_admin_put_replaces_everything_and_status_codes(client: httpx.AsyncClient) -> None:
    first = await put_subject(client, SOKOLOVA, sokolova_body(loans=[loan_body()]))
    assert first.status_code == 201
    second = await put_subject(client, SOKOLOVA, sokolova_body(), None)
    assert second.status_code == 200
    assert second.json()["origin"] == "RUNTIME"
    assert await loans_of(client, SOKOLOVA) == []
    anonymous = await client.get(f"/admin/subjects/{SOKOLOVA}")
    assert anonymous.status_code == 403  # бизнес-ключ на админ-API
    nothing = await client.get(f"/admin/subjects/{GARIPOV}", headers=ADMIN)
    assert nothing.status_code == 404
