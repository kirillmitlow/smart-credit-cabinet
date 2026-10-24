"""T-130: read stored scenario snapshots through HTTP; generation never changes them."""

from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from app.main import create_app
from app.roles.scenarios import service
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.models import Scenario
from tests.conftest import ADMIN_KEY, database_url, make_settings
from tests.test_scenarios_bank_statement import GET, HEADERS, INN, POST, reconcile

pytestmark = pytest.mark.integration
TODAY = date(2026, 10, 21)


@pytest.fixture
def statement_url(postgres_url: str) -> str:
    return database_url(postgres_url, "bank_statement_test")


@pytest.fixture
async def stored_client(statement_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        make_settings(mock_role="scenarios", database_url=statement_url, app_today=TODAY)
    )
    database = app.state.database
    await database.migrate()
    async with database.sessions.begin() as session:
        for spec in builtin_scenarios(TODAY):
            if (
                spec.code in {"garipov", "sokolova"}
                and await session.get(Scenario, spec.code) is None
            ):
                await service.create(session, spec, app.state.clock)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://mock",
            headers={"X-Admin-Key": ADMIN_KEY},
        ) as client:
            yield client
    finally:
        await database.dispose()


async def test_stored_garipov_get_is_repeatable_and_unchanged(
    stored_client: httpx.AsyncClient,
) -> None:
    before = (await stored_client.get("/api/v1/scenarios/garipov")).json()
    response = await stored_client.get(GET)
    assert response.status_code == 200, response.text
    assert response.content == (await stored_client.get(GET, params={"months": 12})).content
    assert set(map(tuple, reconcile(response.content)[0].values())) == {(70000000, 60000000)}
    assert (await stored_client.get("/api/v1/scenarios/garipov")).json() == before


async def test_existing_bank_turnover_matches_exactly(stored_client: httpx.AsyncClient) -> None:
    scenario = (await stored_client.get("/api/v1/scenarios/sokolova")).json()
    response = await stored_client.get(GET.replace("garipov", "sokolova"), params={"months": 6})
    assert response.status_code == 200
    # Snapshot shape is the published scenario view, not the generator's finance helper.
    expected = scenario["expanded"]["bankCore"]["turnover"]
    totals, _ = reconcile(response.content, scenario["inn"])
    for month, amounts in totals.items():
        row = next(x for x in expected if x["month"] == month)
        assert amounts == [row["incomingRub"] * 100, row["outgoingRub"] * 100]


async def test_arbitrary_post_does_not_read_or_write_scenarios(statement_url: str) -> None:
    app = create_app(
        make_settings(mock_role="scenarios", database_url=statement_url, app_today=TODAY)
    )
    await app.state.database.migrate()
    async with app.state.database.sessions() as session:
        before = await session.scalar(select(func.count()).select_from(Scenario))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mock"
        ) as client:
            response = await client.post(
                POST, headers=HEADERS, json={"inn": INN, "avgMonthlyRevenueRub": 700000, "seed": 5}
            )
            assert response.status_code == 200
            reconcile(response.content)
        async with app.state.database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Scenario)) == before
    finally:
        await app.state.database.dispose()
