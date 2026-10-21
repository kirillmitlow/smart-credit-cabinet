"""T-125: публичный preview объединяет системы без записи в базу."""

from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest

from app.main import create_app
from tests.conftest import ADMIN_KEY, database_url, make_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def scenarios_url(postgres_url: str) -> str:
    return database_url(postgres_url, "preview_full_test")


@pytest.fixture
async def client(scenarios_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        make_settings(
            mock_role="scenarios",
            database_url=scenarios_url,
            app_today=date(2026, 10, 25),
            bank_bik="040000111",
        )
    )
    await app.state.database.migrate()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://mock",
            headers={"X-Admin-Key": ADMIN_KEY},
        ) as client:
            yield client
    finally:
        await app.state.database.dispose()


async def test_preview_shares_people_cases_bik_and_loan_events_without_saving(
    client: httpx.AsyncClient,
) -> None:
    before = (await client.get("/api/v1/scenarios")).json()
    body = {
        "code": "preview-combined",
        "title": "БКИ, банкротство учредителя, блокировка и комплаенс",
        "preset": "LLC_HEALTHY",
        "people": {
            "director": {"ref": "boss"},
            "founders": [
                {"ref": "owner", "sharePercent": 60},
                {"ref": "minority", "sharePercent": 40},
            ],
        },
        "bank": {"isCustomer": True},
        "tax": {"accountBlocked": True},
        "bki": {"company": {"currentOverdueDays": 40}},
        "bankruptcies": [
            {
                "subject": "founder:minority",
                "stage": "COMPLETED",
                "startedYearsAgo": 4,
                "completedYearsAgo": 2,
            }
        ],
        "compliance": {"amlListed": "DIRECTOR"},
        "contracts": [
            {"customer": {"name": "Демо-заказчик"}, "subject": "Товар", "priceRub": 12000000}
        ],
    }
    response = await client.post("/api/v1/scenarios/preview", json=body)
    assert response.status_code == 200, response.text
    assert response.content == (await client.post("/api/v1/scenarios/preview", json=body)).content
    data = response.json()
    refs = data["identity"]["subjectRefs"]
    company = next(x["body"] for x in data["bki"] if x["inn"] == refs["company"])
    assert company["obligations"][0]["overduePeriods"]
    founder = next(x["body"] for x in data["bki"] if x["inn"] == refs["founder:minority"])
    case = data["registry"]["bankruptcies"][0]
    assert case["subjectInn"] == refs["founder:minority"]
    assert all(founder["bankruptcies"][0][key] == case[key] for key in founder["bankruptcies"][0])
    assert data["tax"]["accountBlocks"][0]["bik"] == "040000111"
    assert data["bankCore"]["accounts"][0]["status"] == "BLOCKED"
    assert data["tax"]["contracts"][0]["priceRub"] == 12000000
    director = next(x["body"] for x in data["bankSubjects"] if x["inn"] == refs["director"])
    assert director["compliance"]["aml"]
    assert (await client.get("/api/v1/scenarios")).json() == before


async def test_inconsistent_cross_system_parameters_return_422(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/scenarios/preview",
        json={
            "title": "Блокировка без клиента",
            "preset": "LLC_HEALTHY",
            "tax": {"accountBlocked": True},
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "tax.accountBlocked" in response.json()["detail"]


async def test_validation_runs_before_create_and_patch_and_preserves_stored_data(
    client: httpx.AsyncClient,
) -> None:
    good = {
        "code": "validation-before-save",
        "title": "Правильная компания",
        "company": {"form": "LLC", "ageMonths": 120},
        "finance": {"avgMonthlyRevenueRub": 1000000, "hasStatements": True, "noisePercent": 0},
    }
    bad_raw = {"tax": {"taxProfile": {"incomeExpenses": {"incomeRub": 1}}}}
    before = (await client.get("/api/v1/scenarios")).json()
    for path in ("/api/v1/scenarios/preview", "/api/v1/scenarios"):
        response = await client.post(path, json={**good, "raw": bad_raw})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert "PB_REVENUE" in response.json()["detail"]
    assert (await client.get("/api/v1/scenarios")).json() == before
    created = await client.post("/api/v1/scenarios", json=good)
    assert created.status_code == 201, created.text
    changed = await client.patch(
        "/api/v1/scenarios/validation-before-save",
        json={"title": "Не должно сохраниться", "raw": bad_raw},
    )
    assert changed.status_code == 422
    stored = (await client.get("/api/v1/scenarios/validation-before-save")).json()
    assert stored == created.json()
