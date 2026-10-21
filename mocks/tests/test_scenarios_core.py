"""T-119 (интеграция): модель сценария, пресеты, CRUD, идемпотентный POST, PATCH, удаление."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.roles.scenarios.schemas import ScenarioSpec
from tests.conftest import ADMIN_KEY, API_KEY, database_url, make_settings

pytestmark = pytest.mark.integration

JURY_EXAMPLE: dict[str, Any] = {
    "title": "ООО 2 года, выручка 5 млн/мес, просрочка 40 дней",
    "preset": "LLC_HEALTHY",
    "company": {"ageMonths": 24, "okved": "47.19", "regionCode": "77"},
    "finance": {"avgMonthlyRevenueRub": 5000000},
    "bki": {"company": {"currentOverdueDays": 40}},
}

STANKOPROM: dict[str, Any] = {
    "code": "stankoprom",
    "title": "ООО «СтанкоПром» — крупная сумма с залогом, ручное рассмотрение",
    "builtinVersion": 3,
    "expectedOutcome": "MANUAL_REVIEW",
    "expectedFinalOutcome": "APPROVED",
    "expectedReasonCodes": ["AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"],
    "application": {
        "productCode": "INVESTMENT",
        "amountRub": 15000000,
        "termMonths": 60,
        "collateral": {"description": "Покупаемая линия оборудования", "valueRub": 25000000},
        "guarantor": None,
    },
    "preset": "LLC_HEALTHY",
    "company": {
        "form": "LLC",
        "inn": "0017654322",
        "ogrn": "1170000004569",
        "kpp": "001701001",
        "name": "СтанкоПром",
        "registrationDate": "2017-03-14",
        "okved": "25.62",
        "regionCode": "66",
    },
    "people": {
        "director": {
            "ref": "kuznetsov",
            "inn": "001310000115",
            "fullName": "Кузнецов Игорь Петрович",
            "birthDate": "1979-02-11",
            "sharePercent": 100,
        }
    },
    "finance": {
        "avgMonthlyRevenueRub": 35000000,
        "taxRegime": "OSNO",
        "headcount": 60,
        "noisePercent": 0,
    },
    "bki": {
        "owner": None,  # Директор-владелец описан одним блоком, без конфликтующего пресета.
        "company": {
            "historyYears": 6,
            "activeLoans": [],
            "closedLoans": [
                {
                    "kind": "LOAN",
                    "amountRub": 22000000,
                    "openedAt": "2020-11-16",
                    "closedAt": "2026-03-20",
                    "repayment": "BULLET",
                    "secured": True,
                }
            ],
        },
        "director": {
            "activeLoans": [{"kind": "CREDIT_CARD", "limitRub": 300000, "balanceRub": 90000}]
        },
    },
    "bank": {"isCustomer": False},
    "raw": {
        "tax": {
            "financials": [
                {
                    "year": 2025,
                    "formType": "FULL",
                    "lines": {
                        "1100": 182000000,
                        "1200": 141000000,
                        "1300": 196000000,
                        "1400": 22000000,
                        "1500": 105000000,
                        "1600": 323000000,
                        "2110": 420000000,
                        "2200": 32600000,
                        "2330": 1900000,
                        "2400": 30700000,
                    },
                }
            ]
        }
    },
    "users": [
        {"login": "kuznetsov", "role": "DIRECTOR", "personRef": "kuznetsov"},
        {
            "login": "belova",
            "role": "ACCOUNTANT",
            "fullName": "Белова Ольга Николаевна",
            "inn": "001310000299",
            "powerOfAttorney": True,
        },
    ],
}


def stanko(code: str) -> dict[str, Any]:
    """Копия СтанкоПрома без реквизитов: ИНН у сценариев уникален."""
    body = copy.deepcopy(STANKOPROM)
    for field in ("inn", "ogrn", "kpp"):
        body["company"].pop(field)
    body["people"]["director"].pop("inn")
    return {**body, "code": code}


def test_model_accepts_spec_examples() -> None:
    ScenarioSpec.model_validate(JURY_EXAMPLE)
    spec = ScenarioSpec.model_validate(STANKOPROM)
    assert spec.application is not None
    assert spec.application.collateral is not None
    assert spec.application.collateral.value_rub == 25000000


@pytest.mark.parametrize(
    ("patch", "fragment"),
    [
        ({"unknownField": 1}, "unknownField"),
        (
            {"company": {"form": "JSC"}, "people": {"founders": [{"fullName": "Иванов И. И."}]}},
            "АО",
        ),
        ({"company": {"form": "IP", "kpp": "001701001"}}, "КПП"),
        ({"company": {"ogrn": "1170000004569", "ageMonths": 12}}, "registrationDate"),
        ({"activeLoans": [{"kind": "CREDIT_LINE"}]}, "limitRub"),
        ({"finance": {"noisePercent": 80}}, "noisePercent"),
    ],
)
def test_model_rejects_unknown_and_incompatible(patch: dict[str, Any], fragment: str) -> None:
    body = {**copy.deepcopy(JURY_EXAMPLE), **patch}
    with pytest.raises(ValueError, match=fragment):
        ScenarioSpec.model_validate(body)


@pytest.fixture(scope="module")
def scenarios_url(postgres_url: str) -> str:
    return database_url(postgres_url, "mock_scenarios_core_test")


@pytest.fixture
async def app(scenarios_url: str) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(mock_role="scenarios", database_url=scenarios_url))
    await app.state.database.migrate()
    yield app
    await app.state.database.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Admin-Key": ADMIN_KEY}
    ) as c:
        yield c


async def test_presets_are_listed(client: httpx.AsyncClient) -> None:
    presets = (await client.get("/api/v1/presets")).json()
    assert [p["code"] for p in presets] == [
        "IP_HEALTHY",
        "LLC_HEALTHY",
        "LLC_HIGH_DEBT_LOAD",
        "STARTUP",
        "SELF_EMPLOYED",
        "PROBLEM_DEBTOR",
    ]


async def test_create_is_idempotent_with_key(client: httpx.AsyncClient) -> None:
    headers = {"Idempotency-Key": "jury-1"}
    first = await client.post("/api/v1/scenarios", json=JURY_EXAMPLE, headers=headers)
    again = await client.post("/api/v1/scenarios", json=JURY_EXAMPLE, headers=headers)
    assert first.status_code == again.status_code == 201
    assert first.json()["code"] == again.json()["code"]
    assert first.json()["code"].startswith("custom-")
    assert first.json()["status"] == "PENDING"
    listed = (await client.get("/api/v1/scenarios", params={"origin": "CUSTOM"})).json()
    assert [s["code"] for s in listed].count(first.json()["code"]) == 1


async def test_get_returns_application_users_and_spec(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/scenarios", json={**STANKOPROM, "code": "stanko-copy"})
    view = (await client.get("/api/v1/scenarios/stanko-copy")).json()
    assert view["application"]["collateral"]["valueRub"] == 25000000
    assert [u["login"] for u in view["users"]] == ["kuznetsov", "belova"]
    assert view["expectedReasonCodes"] == ["AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"]
    assert view["inn"] == "0017654322"
    assert "meta" not in view


async def test_duplicate_code_is_409(client: httpx.AsyncClient) -> None:
    body = {**JURY_EXAMPLE, "code": "dup-check"}
    assert (await client.post("/api/v1/scenarios", json=body)).status_code == 201
    second = await client.post("/api/v1/scenarios", json=body)
    assert second.status_code == 409
    assert second.json()["code"] == "SCENARIO_EXISTS"
    await client.post("/api/v1/scenarios", json={**STANKOPROM, "code": "inn-first"})
    same_inn = await client.post("/api/v1/scenarios", json={**STANKOPROM, "code": "inn-twin"})
    assert same_inn.status_code == 409
    assert same_inn.json()["code"] == "SCENARIO_INN_EXISTS"


async def test_patch_merges_and_replaces_arrays(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/scenarios", json=stanko("stanko-patch"))
    response = await client.patch(
        "/api/v1/scenarios/stanko-patch",
        json={"finance": {"headcount": 70}, "users": [{"login": "kuz", "role": "DIRECTOR"}]},
    )
    assert response.status_code == 200
    spec = response.json()["spec"]
    assert spec["finance"] == {
        "avgMonthlyRevenueRub": 35000000,
        "taxRegime": "OSNO",
        "headcount": 70,
        "noisePercent": 0,
    }
    assert spec["users"] == [{"login": "kuz", "role": "DIRECTOR"}]


async def test_patch_breaking_model_is_422(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/scenarios", json={**JURY_EXAMPLE, "code": "bad-patch"})
    response = await client.patch("/api/v1/scenarios/bad-patch", json={"company": {"form": "PLC"}})
    assert response.status_code == 422


async def test_builtin_cannot_be_deleted_and_patch_marks_modified(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from app.roles.scenarios import service
    from app.roles.scenarios.schemas import ScenarioOrigin

    async with app.state.database.sessions() as session:
        await service.create(
            session,
            ScenarioSpec.model_validate(stanko("builtin-check")),
            app.state.clock,
            ScenarioOrigin.BUILTIN,
        )
        await session.commit()
    deleted = await client.delete("/api/v1/scenarios/builtin-check")
    assert deleted.status_code == 409
    assert deleted.json()["code"] == "BUILTIN_SCENARIO"
    patched = await client.patch("/api/v1/scenarios/builtin-check", json={"title": "Изменён"})
    assert patched.json()["modified"] is True
    custom = await client.post("/api/v1/scenarios", json={**JURY_EXAMPLE, "code": "to-delete"})
    assert custom.status_code == 201
    assert (await client.delete("/api/v1/scenarios/to-delete")).status_code == 204
    assert (await client.get("/api/v1/scenarios/to-delete")).json()["code"] == "SCENARIO_NOT_FOUND"


async def test_everything_requires_admin_key(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        assert (await c.get("/api/v1/presets")).status_code == 401
        assert (await c.get("/api/v1/scenarios", headers={"X-Api-Key": API_KEY})).status_code == 403


async def test_preview_is_repeatable_and_writes_nothing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from app.common.clock import Clock

    app.state.clock = Clock(app_today=date(2026, 10, 25))
    before = (await client.get("/api/v1/scenarios")).json()
    body = {**JURY_EXAMPLE, "code": "preview-only"}
    first = await client.post("/api/v1/scenarios/preview", json=body)
    again = await client.post("/api/v1/scenarios/preview", json=body)
    assert first.status_code == again.status_code == 200
    assert first.content == again.content
    assert first.json()["identity"]["registrationDate"] == "2024-10-25"
    assert first.json()["registry"]["entity"]["inn"] == first.json()["identity"]["inn"]
    assert (await client.get("/api/v1/scenarios")).json() == before
    assert (await client.get("/api/v1/scenarios/preview-only")).status_code == 404


async def test_preview_observes_occupied_inns_and_excludes_own_scenario(
    client: httpx.AsyncClient,
) -> None:
    preview_body = {**JURY_EXAMPLE, "code": "preview-owner"}
    generated = (await client.post("/api/v1/scenarios/preview", json=preview_body)).json()[
        "identity"
    ]
    body = {
        **preview_body,
        "company": {**JURY_EXAMPLE["company"], "inn": generated["inn"]},
        "people": {"director": {"inn": generated["director"]["inn"]}},
    }
    assert (await client.post("/api/v1/scenarios", json=body)).status_code == 201
    assert (await client.post("/api/v1/scenarios/preview", json=body)).status_code == 200
    conflict = await client.post(
        "/api/v1/scenarios/preview", json={**body, "code": "preview-other"}
    )
    assert conflict.status_code == 422
    assert conflict.json()["code"] == "VALIDATION_ERROR"
    person_conflict = await client.post(
        "/api/v1/scenarios/preview",
        json={
            "code": "preview-person",
            "title": "Другой сценарий",
            "preset": "LLC_HEALTHY",
            "people": body["people"],
        },
    )
    assert person_conflict.status_code == 422
    assert "человека" in person_conflict.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"title": "Без формы и пресета"},
        {"title": "Без формы", "company": {"name": "Маяк"}},
        {"title": "ОГРН без даты", "preset": "LLC_HEALTHY", "company": {"ogrn": "1170000004569"}},
        {
            "title": "Другая дата",
            "preset": "LLC_HEALTHY",
            "company": {"ogrn": "1170000004569", "registrationDate": "2018-01-01"},
        },
        {
            "title": "Директор ИП из пресета",
            "preset": "IP_HEALTHY",
            "people": {"director": {"ref": "boss"}},
        },
    ],
)
async def test_preview_invalid_input_is_problem_json(
    client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    response = await client.post("/api/v1/scenarios/preview", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_preview_without_code_still_repeatable_and_requires_admin(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    first = await client.post("/api/v1/scenarios/preview", json=JURY_EXAMPLE)
    second = await client.post("/api/v1/scenarios/preview", json=JURY_EXAMPLE)
    assert first.status_code == 200
    assert first.content == second.content
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock"
    ) as anonymous:
        assert (
            await anonymous.post("/api/v1/scenarios/preview", json=JURY_EXAMPLE)
        ).status_code == 401


async def test_create_requires_explicit_form_or_preset(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/scenarios", json={"title": "Не угадывать форму"})
    assert response.status_code == 422
    assert "company.form" in response.json()["errors"][0]["msg"]


async def test_preview_finance_uses_app_bik_and_exact_persona_numbers(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from app.common.accounts import account_is_valid

    app.state.settings = app.state.settings.model_copy(update={"bank_bik": "040000111"})
    response = await client.post(
        "/api/v1/scenarios/preview",
        json={
            "code": "preview-finance-http",
            "title": "Финансы",
            "preset": "IP_HEALTHY",
            "finance": {
                "avgMonthlyRevenueRub": 905000,
                "noisePercent": 0,
                "netMarginPercent": 10,
                "minMonthlySurplusRub": 110000,
            },
        },
    )
    assert response.status_code == 200
    bank = response.json()["bankCore"]
    assert account_is_valid("040000111", bank["accounts"][0]["number"])
    assert {(r["incomingNetRub"], r["outgoingRub"]) for r in bank["turnover"]} == {(905000, 795000)}
    assert response.json()["tax"]["financials"] == []


async def test_create_keeps_nulls_that_clear_preset_bank_parameters(
    client: httpx.AsyncClient,
) -> None:
    body = {
        "code": "clear-preset-bank",
        "title": "Без обслуживания",
        "preset": "IP_HEALTHY",
        "bank": {"isCustomer": False, "balanceRub": None, "customerSinceMonths": None},
    }
    created = await client.post("/api/v1/scenarios", json=body)
    assert created.status_code == 201
    saved = created.json()["spec"]
    assert saved["bank"] == body["bank"]
    preview = await client.post("/api/v1/scenarios/preview", json=saved)
    assert preview.status_code == 200
    assert preview.json()["bankCore"]["customer"] is None
    assert preview.json()["bankCore"]["turnover"] == []
