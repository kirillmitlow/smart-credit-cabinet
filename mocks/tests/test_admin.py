"""T-105 (интеграция): общий админ-API данных на роли-заглушке с реальной базой."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.common.admin import (
    AdminHandler,
    ScenarioCount,
    SubjectSummary,
    SubjectView,
    make_admin_router,
    merge_patch,
)
from app.common.db import Origin
from app.common.problems import ProblemException
from app.common.schemas import CamelModel
from app.main import create_app
from tests.conftest import ADMIN_KEY, API_KEY, database_url, make_settings

pytestmark = pytest.mark.integration

meta = sa.MetaData()
subjects = sa.Table(
    "stub_subjects",
    meta,
    sa.Column("inn", sa.String(12), primary_key=True),
    sa.Column("data", JSONB, nullable=False),
    sa.Column("origin", sa.String(16), nullable=False),
    sa.Column("scenario_code", sa.String(64)),
)
runtime = sa.Table(
    "stub_runtime",
    meta,
    sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
    sa.Column("inn", sa.String(12), nullable=False),
    sa.Column("scenario_code", sa.String(64)),
    sa.Column("payload", JSONB, nullable=False),
)


class Status(CamelModel):
    code: str
    debt_rub: int = 0


class StubBody(CamelModel):
    name: str
    status: Status
    active_loans: list[int] = []


class StubHandler(AdminHandler[StubBody]):
    body_model = StubBody

    def check(self, inn: str, body: StubBody) -> None:
        if len(inn) == 12 and body.name.startswith("ООО"):
            raise ProblemException(422, "VALIDATION_ERROR", "У ИП не может быть формы ООО")

    async def put(
        self, session: AsyncSession, inn: str, body: StubBody, scenario_code: str | None
    ) -> None:
        await session.execute(sa.delete(subjects).where(subjects.c.inn == inn))
        await session.execute(
            sa.insert(subjects).values(
                inn=inn,
                data=body.model_dump(mode="json", by_alias=True),
                origin=Origin.SCENARIO if scenario_code else Origin.RUNTIME,
                scenario_code=scenario_code,
            )
        )

    async def get_body(self, session: AsyncSession, inn: str) -> StubBody | None:
        data = await session.scalar(sa.select(subjects.c.data).where(subjects.c.inn == inn))
        return None if data is None else StubBody.model_validate(data)

    async def view(self, session: AsyncSession, inn: str) -> SubjectView | None:
        row = (await session.execute(sa.select(subjects).where(subjects.c.inn == inn))).first()
        if row is None:
            return None
        events = (
            await session.scalars(sa.select(runtime.c.payload).where(runtime.c.inn == inn))
        ).all()
        return SubjectView(
            inn=inn,
            scenario_code=row.scenario_code,
            origin=row.origin,
            data=row.data,
            runtime={"events": list(events)},
        )

    async def list_subjects(
        self,
        session: AsyncSession,
        scenario: str | None,
        origin: Origin | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SubjectSummary], int]:
        query = sa.select(subjects)
        if scenario:
            query = query.where(subjects.c.scenario_code == scenario)
        if origin:
            query = query.where(subjects.c.origin == origin.value)
        total = await session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))
        rows = (
            await session.execute(query.order_by(subjects.c.inn).limit(limit).offset(offset))
        ).all()
        items = [
            SubjectSummary(
                inn=r.inn, scenario_code=r.scenario_code, origin=r.origin, title=r.data["name"]
            )
            for r in rows
        ]
        return items, int(total or 0)

    async def delete(self, session: AsyncSession, inn: str) -> bool:
        await session.execute(sa.delete(runtime).where(runtime.c.inn == inn))
        result = await session.execute(sa.delete(subjects).where(subjects.c.inn == inn))
        return bool(result.rowcount)

    async def scenarios(self, session: AsyncSession) -> list[ScenarioCount]:
        rows = await session.execute(
            sa.select(subjects.c.scenario_code, sa.func.count())
            .where(subjects.c.scenario_code.is_not(None))
            .group_by(subjects.c.scenario_code)
            .order_by(subjects.c.scenario_code)
        )
        return [ScenarioCount(scenario_code=code, subjects=n) for code, n in rows]

    async def delete_scenario(self, session: AsyncSession, code: str) -> int:
        await session.execute(sa.delete(runtime).where(runtime.c.scenario_code == code))
        result = await session.execute(sa.delete(subjects).where(subjects.c.scenario_code == code))
        return int(result.rowcount or 0)

    async def wipe(self, session: AsyncSession) -> None:
        await session.execute(sa.delete(runtime))
        await session.execute(sa.delete(subjects))


@pytest.fixture(scope="module")
def admin_url(postgres_url: str) -> str:
    return database_url(postgres_url, "mock_admin_test")


@pytest.fixture
async def app(admin_url: str) -> AsyncIterator[FastAPI]:
    engine = create_async_engine(admin_url)
    async with engine.begin() as conn:
        await conn.run_sync(meta.drop_all)
        await conn.run_sync(meta.create_all)
    await engine.dispose()
    app = create_app(make_settings(database_url=admin_url))
    app.include_router(make_admin_router(StubHandler()))
    yield app
    await app.state.database.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Admin-Key": ADMIN_KEY}
    ) as c:
        yield c


SOKOLOVA = "001234567887"
ROMASHKA = "0015557771"


def body(
    name: str = "ИП Соколова", code: str = "ACTIVE", loans: list[int] | None = None
) -> dict[str, Any]:
    return {"name": name, "status": {"code": code, "debtRub": 0}, "activeLoans": loans or []}


async def put(
    client: httpx.AsyncClient, inn: str, data: dict[str, Any], scenario: str | None = "sokolova"
) -> httpx.Response:
    headers = {"X-Scenario-Code": scenario} if scenario else {}
    return await client.put(f"/admin/subjects/{inn}", json=data, headers=headers)


async def add_runtime(app: FastAPI, inn: str, scenario: str | None) -> None:
    async with app.state.database.engine.begin() as conn:
        await conn.execute(
            sa.insert(runtime).values(inn=inn, scenario_code=scenario, payload={"kind": "inquiry"})
        )


async def test_put_then_get_returns_full_view(app: FastAPI, client: httpx.AsyncClient) -> None:
    created = await put(client, SOKOLOVA, body())
    assert created.status_code == 201
    replaced = await put(client, SOKOLOVA, body(name="ИП Соколова А. С."))
    assert replaced.status_code == 200
    await add_runtime(app, SOKOLOVA, "sokolova")
    view = (await client.get(f"/admin/subjects/{SOKOLOVA}")).json()
    assert view["scenarioCode"] == "sokolova"
    assert view["origin"] == "SCENARIO"
    assert view["data"]["name"] == "ИП Соколова А. С."
    assert view["runtime"] == {"events": [{"kind": "inquiry"}]}


async def test_patch_merges_objects_and_replaces_arrays(client: httpx.AsyncClient) -> None:
    await put(client, SOKOLOVA, body(loans=[1, 2, 3]))
    response = await client.patch(
        f"/admin/subjects/{SOKOLOVA}",
        json={"status": {"code": "BANKRUPT"}, "activeLoans": [9]},
        headers={"Content-Type": "application/merge-patch+json"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == {"code": "BANKRUPT", "debtRub": 0}
    assert data["activeLoans"] == [9]
    assert response.json()["scenarioCode"] == "sokolova"


async def test_patch_that_breaks_schema_is_422(client: httpx.AsyncClient) -> None:
    await put(client, SOKOLOVA, body())
    response = await client.patch(f"/admin/subjects/{SOKOLOVA}", json={"status": None})
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["status"]


async def test_role_check_gives_clear_422(client: httpx.AsyncClient) -> None:
    response = await put(client, SOKOLOVA, body(name="ООО Ромашка"))
    assert response.status_code == 422
    assert "ИП" in response.json()["detail"]


async def test_missing_subject_is_404_and_bad_inn_400(client: httpx.AsyncClient) -> None:
    assert (await client.patch(f"/admin/subjects/{ROMASHKA}", json={})).json()[
        "code"
    ] == "SUBJECT_NOT_FOUND"
    assert (await client.delete(f"/admin/subjects/{ROMASHKA}")).status_code == 404
    assert (await client.get("/admin/subjects/0015557772")).json()["code"] == "INN_INVALID"


async def test_list_filters_and_pages(client: httpx.AsyncClient) -> None:
    await put(client, SOKOLOVA, body())
    await put(client, ROMASHKA, body(name="ООО Ромашка"), scenario="romashka")
    await put(client, "0017654322", body(name="ООО Вектор"), scenario=None)
    everything = (await client.get("/admin/subjects")).json()
    assert everything["total"] == 3
    only = (await client.get("/admin/subjects", params={"scenario": "romashka"})).json()
    assert [i["inn"] for i in only["items"]] == [ROMASHKA]
    runtime_only = (await client.get("/admin/subjects", params={"origin": "RUNTIME"})).json()
    assert [i["inn"] for i in runtime_only["items"]] == ["0017654322"]
    page = (await client.get("/admin/subjects", params={"limit": 1, "offset": 1})).json()
    assert len(page["items"]) == 1
    assert page["total"] == 3


async def test_delete_scenario_removes_runtime_and_spares_others(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await put(client, SOKOLOVA, body())
    await put(client, ROMASHKA, body(name="ООО Ромашка"), scenario="romashka")
    await add_runtime(app, SOKOLOVA, "sokolova")
    await add_runtime(app, ROMASHKA, "romashka")
    counts = (await client.get("/admin/scenarios")).json()
    assert counts == [
        {"scenarioCode": "romashka", "subjects": 1},
        {"scenarioCode": "sokolova", "subjects": 1},
    ]
    assert (await client.delete("/admin/scenarios/sokolova")).json() == {"deleted": 1}
    assert (await client.get(f"/admin/subjects/{SOKOLOVA}")).status_code == 404
    left = (await client.get(f"/admin/subjects/{ROMASHKA}")).json()
    assert left["runtime"]["events"] == [{"kind": "inquiry"}]


async def test_delete_subject_and_wipe(client: httpx.AsyncClient) -> None:
    await put(client, SOKOLOVA, body())
    await put(client, ROMASHKA, body(name="ООО Ромашка"))
    assert (await client.delete(f"/admin/subjects/{SOKOLOVA}")).status_code == 204
    assert (await client.post("/admin/wipe")).status_code == 204
    assert (await client.get("/admin/subjects")).json()["total"] == 0


async def test_admin_requires_admin_key(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        assert (await c.get("/admin/subjects")).status_code == 401
        consumer = await c.get("/admin/subjects", headers={"X-Api-Key": API_KEY})
        assert consumer.status_code == 403


async def test_openapi_lists_eight_admin_operations_with_admin_scheme(
    client: httpx.AsyncClient,
) -> None:
    spec = (await client.get("/openapi.json")).json()
    ops = [
        op
        for path, item in spec["paths"].items()
        if path.startswith("/admin/") and "chaos" not in path
        for op in item.values()
    ]
    assert len(ops) == 8
    assert all({"AdminKeyAuth": []} in op["security"] for op in ops)


def test_merge_patch_rfc7396_examples() -> None:
    assert merge_patch({"a": "b"}, {"a": "c"}) == {"a": "c"}
    assert merge_patch({"a": "b"}, {"b": "c"}) == {"a": "b", "b": "c"}
    assert merge_patch({"a": "b"}, {"a": None}) == {}
    assert merge_patch({"a": [{"b": "c"}]}, {"a": [1]}) == {"a": [1]}
    assert merge_patch({"e": None}, {"a": 1}) == {"e": None, "a": 1}
    assert merge_patch([1, 2], {"a": "b", "c": None}) == {"a": "b"}
    assert merge_patch({"a": {"bb": {"ccc": None}}}, {"a": {"bb": {"ccc": None}}}) == {
        "a": {"bb": {}}
    }
