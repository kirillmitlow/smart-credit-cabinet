"""T-125: развёрнутые тела проходят запись и бизнес-чтение четырёх настоящих моков."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from app.common.clock import Clock
from app.main import create_app
from tests.conftest import ADMIN_KEY, API_KEY, database_url, make_settings
from tests.test_scenarios_other import TODAY, checked, scenario

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def role_urls(postgres_url: str) -> dict[str, str]:
    return {
        role: database_url(postgres_url, f"other_{role}_test")
        for role in (
            "registry",
            "tax",
            "bank_core",
            "bki",
        )
    }


@pytest.fixture
async def role_clients(role_urls: dict[str, str]) -> AsyncIterator[dict[str, httpx.AsyncClient]]:
    apps: list[FastAPI] = []
    clients: dict[str, httpx.AsyncClient] = {}
    try:
        async with AsyncExitStack() as stack:
            for role, url in role_urls.items():
                app = create_app(make_settings(mock_role=role, database_url=url, app_today=TODAY))
                apps.append(app)
                await app.state.database.migrate()
                app.state.clock = Clock(
                    TODAY, real_now=lambda: datetime(2026, 10, 21, 12, tzinfo=UTC)
                )
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                        base_url="http://mock",
                        headers={"X-Api-Key": API_KEY, "X-Admin-Key": ADMIN_KEY},
                    )
                )
                assert (await client.post("/admin/wipe")).status_code == 204
                clients[role] = client
            yield clients
    finally:
        for app in apps:
            await app.state.database.dispose()


async def test_generated_cases_contract_block_and_aml_survive_mock_business_reads(
    role_clients: dict[str, httpx.AsyncClient],
) -> None:
    spec = scenario(
        bank={"isCustomer": True},
        tax={"accountBlocked": True, "taxDebtRub": 123456},
        bankruptcies=[
            {
                "subject": "founder:minority",
                "stage": "COMPLETED",
                "startedYearsAgo": 4,
                "completedYearsAgo": 2,
            }
        ],
        contracts=[
            {
                "customer": {"name": "Демо-госзаказчик"},
                "subject": "Медтовары",
                "priceRub": 12000000,
                "paymentIn": "+3M",
            }
        ],
        compliance={"amlListed": "DIRECTOR"},
    )
    result = checked(spec)
    inn = result["identity"]["inn"]
    headers = {"X-Scenario-Code": spec.code}
    for role, key in (("registry", "registry"), ("tax", "tax"), ("bank_core", "bankCore")):
        response = await role_clients[role].put(
            f"/admin/subjects/{inn}", json=result[key], headers=headers
        )
        assert response.status_code == 201, response.text
    for role, entries in (("bki", result["bki"]), ("bank_core", result["bankSubjects"])):
        for entry in entries:
            response = await role_clients[role].put(
                f"/admin/subjects/{entry['inn']}",
                json=entry["body"],
                headers=headers,
            )
            assert response.status_code == 201, response.text
    person = result["identity"]["subjectRefs"]["founder:minority"]
    registry_response = await role_clients["registry"].get(f"/api/v1/bankruptcies/{person}")
    assert registry_response.status_code == 200
    registry_case = registry_response.json()["bankruptcies"][0]
    subject = next(x["body"]["subject"] for x in result["bki"] if x["inn"] == person)
    report = await role_clients["bki"].post(
        "/api/v1/credit-reports",
        json={
            "subject": subject,
            "purpose": "LOAN_APPLICATION",
            "consent": {
                "consentId": "other-consent",
                "subjectInn": person,
                "signedAt": "2026-10-21T12:00:00Z",
                "validUntil": "2026-11-21",
                "purpose": "LOAN_APPLICATION",
            },
        },
    )
    assert report.status_code == 200, report.text
    bki_case = report.json()["bankruptcies"][0]
    assert all(bki_case[k] == registry_case[k] for k in bki_case)
    contracts = await role_clients["tax"].get("/api/v1/contracts", params={"supplierInn": inn})
    assert contracts.status_code == 200
    assert contracts.json()["contracts"][0]["paymentDeadline"] == "2027-01-21"
    blocks = await role_clients["tax"].get(
        f"/api/v1/account-blocks/{inn}", params={"bik": "040000999"}
    )
    assert blocks.status_code == 200
    assert len(blocks.json()["decisions"]) == 1
    customer = await role_clients["bank_core"].get(f"/api/v1/customers/{inn}")
    assert customer.status_code == 200
    assert customer.json()["accounts"][0]["status"] == "BLOCKED"
    director = result["identity"]["subjectRefs"]["director"]
    screening = await role_clients["bank_core"].post(
        "/api/v1/compliance/screening",
        json={
            "subjects": [
                {"inn": inn, "role": "COMPANY"},
                *[
                    {
                        "inn": person["inn"],
                        "role": "DIRECTOR" if person["inn"] == director else "FOUNDER",
                    }
                    for person in result["identity"]["persons"]
                ],
            ]
        },
    )
    assert screening.status_code == 200
    assert screening.json()["overall"] == "HIT"
    hits = {r["inn"]: r["amlList"]["listed"] for r in screening.json()["results"]}
    assert hits[director] is True
    assert hits[inn] is False
    assert all(not listed for subject, listed in hits.items() if subject != director)
    assert set(hits) == {inn, *(p["inn"] for p in result["identity"]["persons"])}
