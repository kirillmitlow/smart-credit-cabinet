"""T-109..T-111 (интеграция): mock-tax — профиль, отчётность, МСП, НПД, ЕИС и блокировки."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from tests.conftest import ADMIN_KEY, database_url, make_settings

pytestmark = pytest.mark.integration

TAX_KEY = "dev-tax-key"
ROMASHKA = "0015557771"
STANKOPROM = "0017654322"
VEKTOR = "0012221117"  # пример МСП из 5.3
SUPPLIER = "0012345673"  # пример ЕИС из 5.6
SOKOLOVA = "001234567887"  # ИП: отчётности нет
ORLOV = "001211122200"  # самозанятый
OUR_BIK = "040000999"
OTHER_BIK = "040000111"

LINES_2025 = {
    "1100": 182000000,
    "1200": 141000000,
    "1300": 196000000,
    "1400": 22000000,
    "1500": 105000000,
    "1600": 323000000,
    "2110": 420000000,
    "2200": 41500000,
    "2330": 1900000,
    "2400": 30700000,
}
LINES_2024 = {
    "1100": 171000000,
    "1200": 128000000,
    "1300": 165300000,
    "1400": 31000000,
    "1500": 102700000,
    "1600": 299000000,
    "2110": 388000000,
    "2200": 36900000,
    "2330": 3100000,
    "2400": 27400000,
}


def profile(inn: str = ROMASHKA) -> dict[str, Any]:
    return {
        "inn": inn,
        "taxRegimes": [{"code": "USN_INCOME_MINUS_EXPENSES", "year": 2025}],
        "avgHeadcount": {"value": 12, "year": 2025},
        "taxesPaid": [{"year": 2025, "totalRub": 3410000}, {"year": 2024, "totalRub": 3120000}],
        "debts": {
            "asOf": "2026-10-01",
            "taxDebtRub": 1150000,
            "penaltiesRub": 42000,
            "finesRub": 0,
        },
        "incomeExpenses": {"year": 2025, "incomeRub": 95000000, "expensesRub": 91000000},
        "taxOffenses": {"year": 2025, "count": 1, "finesRub": 5000},
        "riskFlags": {
            "massAddress": False,
            "massDirector": False,
            "massFounder": False,
            "disqualifiedManagement": False,
            "noReportsOverYear": False,
        },
    }


def statements() -> list[dict[str, Any]]:
    return [
        {"year": 2025, "formType": "FULL", "submittedAt": "2026-03-28", "lines": dict(LINES_2025)},
        {
            "year": 2024,
            "formType": "SIMPLIFIED",
            "submittedAt": "2025-03-20",
            "lines": dict(LINES_2024),
        },
    ]


def contract(number: str = "1001500002826000127", **over: Any) -> dict[str, Any]:
    base = {
        "registryNumber": number,
        "customer": {"name": "ГБУЗ «Городская больница № 5» (синтетическая)", "inn": "0015000028"},
        "subject": "Поставка медицинских изделий и расходных материалов",
        "priceRub": 12000000,
        "concludedAt": "2026-09-01",
        "executionDeadline": "2026-12-15",
        "paymentDeadline": "2027-01-15",
        "status": "IN_PROGRESS",
        "paidRub": 0,
    }
    return base | over


def block(**over: Any) -> dict[str, Any]:
    base = {
        "number": "4512",
        "date": "2026-09-15",
        "taxAuthorityCode": "0015",
        "bik": OTHER_BIK,
        "reason": "TAX_DEBT_COLLECTION",
        "liftedAt": None,
    }
    return base | over


def romashka_body() -> dict[str, Any]:
    return {
        "taxProfile": profile(),
        "financials": statements(),
        "sme": {
            "category": "SMALL",
            "includedAt": "2019-05-10",
            "isNewlyCreated": False,
            "isSocialEnterprise": False,
        },
        "npd": None,
        "accountBlocks": [block()],
        "contracts": [contract()],
    }


@pytest.fixture(scope="module")
def tax_url(postgres_url: str) -> str:
    return database_url(postgres_url, "mock_tax_test")


@pytest.fixture
async def app(tax_url: str) -> AsyncIterator[FastAPI]:
    app = create_app(
        make_settings(
            mock_role="tax",
            mock_api_keys=f"api:{TAX_KEY}",
            database_url=tax_url,
            app_today="2026-10-20",
        )
    )
    await app.state.database.migrate()
    yield app
    await app.state.database.dispose()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Admin-Key": ADMIN_KEY}
    ) as c:
        assert (await c.post("/admin/wipe")).status_code == 204
        yield c


@pytest.fixture
async def client(app: FastAPI, admin: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Api-Key": TAX_KEY}
    ) as c:
        yield c


async def put(
    admin: httpx.AsyncClient, inn: str, body: dict[str, Any], scenario: str | None = "demo"
) -> httpx.Response:
    headers = {"X-Scenario-Code": scenario} if scenario else {}
    return await admin.put(f"/admin/subjects/{inn}", json=body, headers=headers)


# --- 5.1 налоговый профиль -----------------------------------------------------------------------


async def test_tax_profile_round_trip_matches_spec_example(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    assert (await put(admin, ROMASHKA, romashka_body())).status_code == 201
    response = await client.get(f"/api/v1/tax-profile/{ROMASHKA}")
    assert response.status_code == 200
    body = response.json()
    meta = body.pop("meta")
    assert meta["source"] == "FNS_TRANSPARENT_BUSINESS"
    assert meta["simulated"] is True
    assert meta["dataActualAt"] == "2026-10-01"  # первое число текущего месяца
    assert body == profile()


async def test_tax_profile_nulls_for_entrepreneur(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    entrepreneur = profile(SOKOLOVA) | {
        "incomeExpenses": None,
        "avgHeadcount": None,
        "taxOffenses": None,
    }
    assert (await put(admin, SOKOLOVA, {"taxProfile": entrepreneur})).status_code == 201
    body = (await client.get(f"/api/v1/tax-profile/{SOKOLOVA}")).json()
    assert body["incomeExpenses"] is None
    assert body["avgHeadcount"] is None
    assert body["taxOffenses"] is None


async def test_tax_profile_risk_flags_and_debts(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    body = romashka_body()
    body["taxProfile"]["riskFlags"] |= {"massAddress": True, "disqualifiedManagement": True}
    body["taxProfile"]["debts"] |= {"taxDebtRub": 250000, "finesRub": 7000}
    await put(admin, ROMASHKA, body)
    card = (await client.get(f"/api/v1/tax-profile/{ROMASHKA}")).json()
    assert card["riskFlags"]["massAddress"] is True
    assert card["riskFlags"]["disqualifiedManagement"] is True
    assert card["riskFlags"]["massDirector"] is False
    assert card["debts"]["taxDebtRub"] == 250000
    assert card["debts"]["finesRub"] == 7000


async def test_tax_profile_missing_is_404_and_orlov_has_no_profile(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, ORLOV, {"npd": {"registeredAt": "2024-01-10"}})
    for inn in (ROMASHKA, ORLOV):
        response = await client.get(f"/api/v1/tax-profile/{inn}")
        assert response.status_code == 404
        assert response.json()["code"] == "ENTITY_NOT_FOUND"


# --- 5.2 отчётность ------------------------------------------------------------------------------


async def test_financials_latest_year_with_previous_and_summary(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, STANKOPROM, {"financials": statements()})
    response = await client.get(f"/api/v1/financials/{STANKOPROM}")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["source"] == "FNS_GIR_BO"
    assert body["inn"] == STANKOPROM
    assert body["year"] == 2025
    assert body["availableYears"] == [2025, 2024]
    assert body["formType"] == "FULL"
    assert body["submittedAt"] == "2026-03-28"
    assert body["lines"]["1100"] == {"current": 182000000, "previous": 171000000}
    assert body["lines"]["2400"] == {"current": 30700000, "previous": 27400000}
    assert set(body["lines"]) == set(LINES_2025)
    assert body["summary"] == {
        "revenueRub": 420000000,
        "salesProfitRub": 41500000,
        "interestPayableRub": 1900000,
        "netProfitRub": 30700000,
        "totalAssetsRub": 323000000,
        "equityRub": 196000000,
        "longTermLiabilitiesRub": 22000000,
        "shortTermLiabilitiesRub": 105000000,
    }


async def test_financials_explicit_year_without_previous_has_null_previous(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, STANKOPROM, {"financials": statements()})
    body = (await client.get(f"/api/v1/financials/{STANKOPROM}", params={"year": 2024})).json()
    assert body["year"] == 2024
    assert body["formType"] == "SIMPLIFIED"
    assert body["availableYears"] == [2025, 2024]
    assert all(pair["previous"] is None for pair in body["lines"].values())
    assert body["lines"]["2110"]["current"] == 388000000


async def test_financials_last_available_year_when_filed_year_is_old(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, STANKOPROM, {"financials": statements()[1:]})
    body = (await client.get(f"/api/v1/financials/{STANKOPROM}")).json()
    assert body["year"] == 2024
    assert body["availableYears"] == [2024]


async def test_financials_not_found_cases(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, STANKOPROM, {"financials": statements()})
    cases = [
        (f"/api/v1/financials/{STANKOPROM}?year=2023", "год не подан"),
        (f"/api/v1/financials/{ROMASHKA}", "компания без отчётности (моложе года)"),
        (f"/api/v1/financials/{SOKOLOVA}", "ИП"),
        (f"/api/v1/financials/{ORLOV}", "самозанятый"),
        ("/api/v1/financials/001310000115", "любой верный 12-значный ИНН"),
    ]
    for url, why in cases:
        response = await client.get(url)
        assert response.status_code == 404, why
        assert response.json()["code"] == "STATEMENTS_NOT_FOUND", why


async def test_financials_errors_400_and_422(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/financials/001234567888")).status_code == 400
    bad = await client.get(f"/api/v1/financials/{STANKOPROM}", params={"year": "abc"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda lines: lines.update({"1600": 323000001}), "Баланс"),
        (lambda lines: lines.update({"1200": 140000000}), "Баланс"),
        (lambda lines: lines.update({"1300": 195000000}), "Баланс"),
        (lambda lines: lines.pop("2400"), "2400"),
        (lambda lines: lines.update({"9999": 1}), "9999"),
        (lambda lines: lines.update({"1100": "много"}), "1100"),
    ],
)
async def test_unbalanced_or_incomplete_statement_is_422(
    admin: httpx.AsyncClient, mutate: Any, needle: str
) -> None:
    records = statements()
    mutate(records[0]["lines"])
    response = await put(admin, STANKOPROM, {"financials": records})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert needle in response.text


async def test_duplicate_years_and_entrepreneur_statements_are_422(
    admin: httpx.AsyncClient,
) -> None:
    twice = statements()[:1] * 2
    assert (await put(admin, STANKOPROM, {"financials": twice})).status_code == 422
    response = await put(admin, SOKOLOVA, {"financials": statements()})
    assert response.status_code == 422
    assert "ИП" in response.json()["detail"]
    rich = profile(SOKOLOVA)  # у ИП incomeExpenses должен быть null
    assert (await put(admin, SOKOLOVA, {"taxProfile": rich})).status_code == 422


# --- 5.3 МСП -------------------------------------------------------------------------------------


async def test_sme_in_registry(admin: httpx.AsyncClient, client: httpx.AsyncClient) -> None:
    body = {
        "sme": {
            "category": "MICRO",
            "includedAt": "2026-08-10",
            "isNewlyCreated": True,
            "isSocialEnterprise": False,
        }
    }
    await put(admin, VEKTOR, body)
    response = await client.get(f"/api/v1/sme-status/{VEKTOR}")
    assert response.status_code == 200
    data = response.json()
    meta = data.pop("meta")
    assert meta["source"] == "FNS_RMSP"
    assert meta["dataActualAt"] == "2026-10-10"
    assert data == {
        "inn": VEKTOR,
        "inRegistry": True,
        "category": "MICRO",
        "includedAt": "2026-08-10",
        "isNewlyCreated": True,
        "isSocialEnterprise": False,
    }


async def test_not_in_registry_is_200_not_404(client: httpx.AsyncClient) -> None:
    for inn in (VEKTOR, SOKOLOVA):
        response = await client.get(f"/api/v1/sme-status/{inn}")
        assert response.status_code == 200
        body = response.json()
        assert body["inRegistry"] is False
        assert body["category"] is None
        assert body["includedAt"] is None
    assert (await client.get("/api/v1/sme-status/0012221118")).status_code == 400


async def test_sme_data_actual_at_before_the_tenth_is_previous_month(
    tax_url: str, admin: httpx.AsyncClient
) -> None:
    app = create_app(
        make_settings(
            mock_role="tax",
            mock_api_keys=f"api:{TAX_KEY}",
            database_url=tax_url,
            app_today="2026-10-05",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Api-Key": TAX_KEY}
    ) as c:
        body = (await c.get(f"/api/v1/sme-status/{VEKTOR}")).json()
    await app.state.database.dispose()
    assert body["meta"]["dataActualAt"] == "2026-09-10"


# --- 5.4 НПД -------------------------------------------------------------------------------------


async def npd(client: httpx.AsyncClient, inn: str, day: str = "2026-10-20") -> httpx.Response:
    return await client.post("/api/v1/self-employed/status", json={"inn": inn, "requestDate": day})


async def test_self_employed_status_matches_spec_example(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, ORLOV, {"npd": {"registeredAt": "2024-01-10"}})
    response = await npd(client, ORLOV)
    assert response.status_code == 200
    assert response.json() == {
        "status": True,
        "message": f"{ORLOV} является плательщиком налога на профессиональный доход",
    }
    assert response.headers["x-mock-simulated"] == "true"
    assert "meta" not in response.json()


async def test_not_self_employed_and_dates(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, ORLOV, {"npd": {"registeredAt": "2024-01-10", "deregisteredAt": "2025-06-01"}})
    assert (await npd(client, ORLOV, "2024-01-09")).json()["status"] is False
    assert (await npd(client, ORLOV, "2025-05-31")).json()["status"] is True
    after = await npd(client, ORLOV, "2026-10-20")
    assert after.json() == {
        "status": False,
        "message": f"{ORLOV} не является плательщиком налога на профессиональный доход",
    }
    assert after.headers["x-mock-simulated"] == "true"
    stranger = await npd(client, "001310000115")
    assert stranger.json()["status"] is False
    organisation = await npd(client, STANKOPROM)
    assert organisation.status_code == 200
    assert organisation.json()["status"] is False


async def test_self_employed_errors(client: httpx.AsyncClient) -> None:
    bad = await npd(client, "001211122201")
    assert bad.status_code == 400
    assert bad.json()["code"] == "INN_INVALID"
    assert (
        await client.post("/api/v1/self-employed/status", json={"inn": ORLOV})
    ).status_code == 422
    wrong_date = await npd(client, ORLOV, "вчера")
    assert wrong_date.status_code == 422
    assert wrong_date.json()["code"] == "VALIDATION_ERROR"


async def test_npd_only_for_people(admin: httpx.AsyncClient) -> None:
    response = await put(admin, STANKOPROM, {"npd": {"registeredAt": "2024-01-10"}})
    assert response.status_code == 422


# --- 5.5 блокировки ------------------------------------------------------------------------------


async def test_account_blocks_with_and_without_bik(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, ROMASHKA, {"accountBlocks": [block()]})
    everything = (await client.get(f"/api/v1/account-blocks/{ROMASHKA}")).json()
    assert everything["meta"]["source"] == "FNS_BLOCKS"
    assert everything["inn"] == ROMASHKA
    assert everything["checkedAt"].startswith("2026-10-20T")
    assert everything["decisions"] == [
        {
            "number": "4512",
            "date": "2026-09-15",
            "taxAuthorityCode": "0015",
            "bik": OTHER_BIK,
            "reason": "TAX_DEBT_COLLECTION",
        }
    ]
    ours = (await client.get(f"/api/v1/account-blocks/{ROMASHKA}", params={"bik": OUR_BIK})).json()
    assert ours["decisions"] == []  # решение по счёту в другом банке
    theirs = (
        await client.get(f"/api/v1/account-blocks/{ROMASHKA}", params={"bik": OTHER_BIK})
    ).json()
    assert len(theirs["decisions"]) == 1


async def test_account_block_on_our_bik_and_lifted_one_is_hidden(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    blocks = [
        block(number="1", bik=OUR_BIK, date="2026-10-01"),
        block(number="2", bik=OUR_BIK, date="2026-05-01", liftedAt="2026-06-01"),
        block(number="3", reason="NON_SUBMISSION_OF_DECLARATION", date="2026-10-10"),
    ]
    await put(admin, ROMASHKA, {"accountBlocks": blocks})
    url = f"/api/v1/account-blocks/{ROMASHKA}"
    ours = (await client.get(url, params={"bik": OUR_BIK})).json()["decisions"]
    assert [d["number"] for d in ours] == ["1"]
    allbanks = (await client.get(url)).json()["decisions"]
    assert [d["number"] for d in allbanks] == ["3", "1"]  # новые сверху, снятое скрыто
    stored = (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()["data"]["accountBlocks"]
    assert [b["liftedAt"] for b in stored] == [None, "2026-06-01", None]  # админ-API видит всё


async def test_no_blocks_is_empty_list_and_bad_bik_is_422(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/account-blocks/{ROMASHKA}")
    assert response.status_code == 200
    assert response.json()["decisions"] == []
    assert (await client.get(f"/api/v1/account-blocks/{ROMASHKA}?bik=12")).status_code == 422
    assert (await client.get("/api/v1/account-blocks/0015557772")).status_code == 400


async def test_invalid_block_is_422(admin: httpx.AsyncClient) -> None:
    for bad in (
        block(bik="123"),
        block(reason="BECAUSE"),
        block(liftedAt="2026-01-01"),
        block(taxAuthorityCode="15"),
    ):
        assert (await put(admin, ROMASHKA, {"accountBlocks": [bad]})).status_code == 422, bad


# --- 5.6 госзакупки ------------------------------------------------------------------------------


async def test_contracts_list_matches_spec_example(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, SUPPLIER, {"contracts": [contract()]})
    response = await client.get("/api/v1/contracts", params={"supplierInn": SUPPLIER})
    assert response.status_code == 200
    body = response.json()
    meta = body.pop("meta")
    assert meta["source"] == "EIS"
    assert meta["dataActualAt"] == "2026-10-19"
    assert body == {"supplierInn": SUPPLIER, "contracts": [contract()]}


async def test_contracts_sorted_newest_first_and_filtered_by_status(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    old = contract(
        "1001500002825000044",
        concludedAt="2025-02-01",
        executionDeadline="2025-05-01",
        paymentDeadline="2025-06-01",
        status="EXECUTED",
        paidRub=12000000,
    )
    await put(admin, SUPPLIER, {"contracts": [old, contract()]})
    url = "/api/v1/contracts"
    allc = (await client.get(url, params={"supplierInn": SUPPLIER})).json()["contracts"]
    assert [c["registryNumber"] for c in allc] == ["1001500002826000127", "1001500002825000044"]
    done = (await client.get(url, params={"supplierInn": SUPPLIER, "status": "EXECUTED"})).json()
    assert [c["status"] for c in done["contracts"]] == ["EXECUTED"]
    other = (await client.get(url, params={"supplierInn": SUPPLIER, "status": "TERMINATED"})).json()
    assert other["contracts"] == []


async def test_contracts_without_any_are_empty_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/contracts", params={"supplierInn": ROMASHKA})
    assert response.status_code == 200
    assert response.json()["contracts"] == []


async def test_contracts_query_errors(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/contracts")
    assert missing.status_code == 422
    assert missing.json()["code"] == "VALIDATION_ERROR"
    unknown = await client.get("/api/v1/contracts", params={"supplierInn": SUPPLIER, "status": "X"})
    assert unknown.status_code == 422
    bad = await client.get("/api/v1/contracts", params={"supplierInn": "0012345674"})
    assert bad.status_code == 400
    assert bad.json()["code"] == "INN_INVALID"


@pytest.mark.parametrize(
    "bad",
    [
        {"executionDeadline": "2026-08-31"},
        {"paymentDeadline": "2026-08-31"},
        {"paidRub": 12000001},
        {"customer": {"name": "Больница", "inn": "0015000029"}},
        {"customer": {"name": "ИП", "inn": "001234567887"}},
        {"registryNumber": "123"},
        {"status": "DONE"},
        {"priceRub": 0},
    ],
)
async def test_invalid_contract_is_422(admin: httpx.AsyncClient, bad: dict[str, Any]) -> None:
    response = await put(admin, SUPPLIER, {"contracts": [contract(**bad)]})
    assert response.status_code == 422, response.text


async def test_contract_number_cannot_belong_to_two_suppliers(admin: httpx.AsyncClient) -> None:
    await put(admin, SUPPLIER, {"contracts": [contract()]})
    response = await put(admin, ROMASHKA, {"contracts": [contract()]})
    assert response.status_code == 422
    assert "1001500002826000127" in response.json()["detail"]
    twice = await put(admin, ROMASHKA, {"contracts": [contract(), contract()]})
    assert twice.status_code == 422


# --- админ-API -----------------------------------------------------------------------------------


async def test_admin_get_returns_exactly_what_was_put(admin: httpx.AsyncClient) -> None:
    body = romashka_body()
    assert (await put(admin, ROMASHKA, body, scenario="romashka")).status_code == 201
    view = (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()
    assert view["scenarioCode"] == "romashka"
    assert view["origin"] == "SCENARIO"
    assert view["data"] == body
    replaced = await put(admin, ROMASHKA, {"sme": None}, scenario="romashka")
    assert replaced.status_code == 200
    data = (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()["data"]
    assert data["taxProfile"] is None
    assert data["financials"] == []
    assert data["contracts"] == []


async def test_patch_adds_debt_and_replaces_arrays(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, ROMASHKA, romashka_body())
    response = await admin.patch(
        f"/admin/subjects/{ROMASHKA}",
        json={"taxProfile": {"debts": {"taxDebtRub": 2000000}}, "contracts": []},
    )
    assert response.status_code == 200, response.text
    card = (await client.get(f"/api/v1/tax-profile/{ROMASHKA}")).json()
    assert card["debts"] == {
        "asOf": "2026-10-01",
        "taxDebtRub": 2000000,
        "penaltiesRub": 42000,
        "finesRub": 0,
    }
    contracts = (await client.get("/api/v1/contracts", params={"supplierInn": ROMASHKA})).json()
    assert contracts["contracts"] == []
    bad = await admin.patch(
        f"/admin/subjects/{ROMASHKA}", json={"taxProfile": {"debts": {"taxDebtRub": -1}}}
    )
    assert bad.status_code == 422


async def test_path_inn_must_match_profile(admin: httpx.AsyncClient) -> None:
    response = await put(admin, STANKOPROM, {"taxProfile": profile(ROMASHKA)})
    assert response.status_code == 422
    assert "в пути" in response.json()["detail"]


async def test_list_scenarios_delete_and_wipe(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, ROMASHKA, romashka_body(), scenario="romashka")
    await put(admin, ORLOV, {"npd": {"registeredAt": "2024-01-10"}}, scenario="orlov")
    await put(admin, VEKTOR, {"sme": None}, scenario=None)
    assert (await admin.get("/admin/subjects")).json()["total"] == 3
    runtime = (await admin.get("/admin/subjects", params={"origin": "RUNTIME"})).json()
    assert [i["inn"] for i in runtime["items"]] == [VEKTOR]
    assert (await admin.get("/admin/scenarios")).json() == [
        {"scenarioCode": "orlov", "subjects": 1},
        {"scenarioCode": "romashka", "subjects": 1},
    ]
    assert (await admin.delete("/admin/scenarios/romashka")).json() == {"deleted": 1}
    assert (await client.get(f"/api/v1/tax-profile/{ROMASHKA}")).status_code == 404
    assert (await client.get(f"/api/v1/financials/{ROMASHKA}")).status_code == 404
    assert (await npd(client, ORLOV)).json()["status"] is True
    assert (await admin.delete(f"/admin/subjects/{ORLOV}")).status_code == 204
    assert (await admin.delete(f"/admin/subjects/{ORLOV}")).status_code == 404
    assert (await npd(client, ORLOV)).json()["status"] is False
    assert (await admin.post("/admin/wipe")).status_code == 204
    assert (await admin.get("/admin/subjects")).json()["total"] == 0


# --- ключи и OpenAPI -----------------------------------------------------------------------------

BUSINESS_GETS = [
    f"/api/v1/tax-profile/{ROMASHKA}",
    f"/api/v1/financials/{STANKOPROM}",
    f"/api/v1/sme-status/{VEKTOR}",
    f"/api/v1/account-blocks/{ROMASHKA}",
    f"/api/v1/contracts?supplierInn={SUPPLIER}",
]


async def test_keys_are_checked_on_every_endpoint(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        calls = [lambda h, u=u: c.get(u, headers=h) for u in BUSINESS_GETS]
        calls.append(
            lambda h: c.post(
                "/api/v1/self-employed/status",
                json={"inn": ORLOV, "requestDate": "2026-10-20"},
                headers=h,
            )
        )
        for call in calls:
            assert (await call({})).status_code == 401
            assert (await call({"X-Api-Key": "dev-registry-key"})).status_code == 401
            assert (await call({"X-Admin-Key": ADMIN_KEY})).status_code == 403
            assert (await call({"X-Api-Key": ADMIN_KEY})).status_code == 403


async def test_openapi_describes_all_endpoints_and_errors(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert {"ApiKeyAuth", "AdminKeyAuth"} <= set(spec["components"]["securitySchemes"])
    expected = {
        ("/api/v1/tax-profile/{inn}", "get"): {"400", "401", "403", "404"},
        ("/api/v1/financials/{inn}", "get"): {"400", "404", "422"},
        ("/api/v1/sme-status/{inn}", "get"): {"400", "401"},
        ("/api/v1/self-employed/status", "post"): {"400", "422"},
        ("/api/v1/account-blocks/{inn}", "get"): {"400", "422"},
        ("/api/v1/contracts", "get"): {"400", "422"},
    }
    for (path, method), codes in expected.items():
        op = spec["paths"][path][method]
        assert {"ApiKeyAuth": []} in op["security"], path
        assert codes <= set(op["responses"]), path
    params = {p["name"] for p in spec["paths"]["/api/v1/contracts"]["get"]["parameters"]}
    assert params == {"supplierInn", "status"}
