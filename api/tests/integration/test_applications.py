"""T-250…T-254: заявка — доступ только своей компании, черновик с версией, отправка, гонки, журнал."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.main import create_app
from app.modules import auth
from app.modules.applications import Application, Status, transition
from app.modules.applications.states import Actor
from app.modules.companies.models import Company, CompanyMember
from app.shared import db, tasks
from app.shared.errors import AppError
from app.shared.settings import Settings
from tests.integration.support import grant_company_bki

pytestmark = pytest.mark.integration


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: sent.append((name, kw)))
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    database = db.get_database()
    db.migrate(database.engine)
    with database.transaction() as s:
        s.execute(text("TRUNCATE applications, company_members, companies, users CASCADE"))
    principals = {}
    with database.transaction() as s:
        for inn, name in (("001234567887", "ИП Соколова"), ("0017654322", "СтанкоПром")):
            company = Company(inn=inn, kind="LEGAL", name=name, status="ACTIVE")
            s.add(company)
            s.flush()
            user = auth.upsert_client(
                s, login_ref=f"t:{inn}", display_name=name, person_inn=None, scenario_code=None
            )
            s.add(
                CompanyMember(
                    company_id=company.id,
                    user_id=user.id,
                    role="DIRECTOR",
                    can_sign=True,
                    poa_permissions=[],
                    status="ACTIVE",
                )
            )
            principals[inn] = auth.Principal(
                user_id=user.id,
                role="CLIENT",
                zone=auth.Zone.CLIENT,
                display_name=name,
                memberships=(auth.Membership(company.id, "DIRECTOR"),),
                active_company_id=company.id,
            )
    yield {"app": app, "principals": principals, "sent": sent}
    database.dispose()


async def client_for(stand: dict[str, Any], inn: str) -> httpx.AsyncClient:
    sid = auth.sessions.create(stand["principals"][inn])
    transport = httpx.ASGITransport(app=stand["app"])
    return httpx.AsyncClient(
        transport=transport, base_url="http://api", cookies={"sid_client": sid}
    )


@pytest.fixture
async def sokolova(stand: dict[str, Any]) -> AsyncIterator[httpx.AsyncClient]:
    async with await client_for(stand, "001234567887") as c:
        yield c


@pytest.fixture
async def stranger(stand: dict[str, Any]) -> AsyncIterator[httpx.AsyncClient]:
    async with await client_for(stand, "0017654322") as c:
        yield c


async def submit(client: httpx.AsyncClient, application_id: str) -> httpx.Response:
    """Согласия здесь не предмет проверки: выдаём обязательные напрямую (их тесты — в test_consents)."""
    grant_company_bki(application_id)
    return await client.post(f"/applications/{application_id}/submit")


TERMS = {"productCode": "EXPRESS", "amountRub": 500000, "termMonths": 12}


async def test_create_list_and_foreign_company_is_404(
    sokolova: httpx.AsyncClient, stranger: httpx.AsyncClient
) -> None:
    created = await sokolova.post("/applications", json=TERMS)
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "DRAFT"
    assert body["number"].startswith("АЗ-")
    assert body["allowedActions"] == ["EDIT_DRAFT", "SUBMIT", "DELETE_DRAFT"]
    assert not {"score", "dscr", "snapshots"} & set(body)
    page = (await sokolova.get("/applications")).json()
    assert page["items"][0]["id"] == body["id"]
    assert (await stranger.get(f"/applications/{body['id']}")).status_code == 404
    assert (await stranger.get("/applications")).json()["items"] == []


async def test_draft_version_conflict(sokolova: httpx.AsyncClient) -> None:
    app_id = (await sokolova.post("/applications", json={})).json()["id"]
    first = await sokolova.patch(
        f"/applications/{app_id}/draft", json={"version": 1, "amountRub": 400000}
    )
    assert first.json()["version"] == 2
    stale = await sokolova.patch(
        f"/applications/{app_id}/draft", json={"version": 1, "termMonths": 6}
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    bad = await sokolova.patch(
        f"/applications/{app_id}/draft", json={"version": 2, "termMonths": 500}
    )
    assert bad.status_code == 422


async def test_submit_creates_version_event_and_task_once(
    sokolova: httpx.AsyncClient, stand: dict[str, Any]
) -> None:
    app_id = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    submitted = await submit(sokolova, app_id)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"
    again = await submit(sokolova, app_id)
    assert again.status_code == 409
    assert again.json()["code"] == "INVALID_TRANSITION"
    assert stand["sent"] == [("pipeline.run", {"application_id": app_id})]
    with db.transaction() as s:
        events = s.execute(
            text("SELECT kind, from_status, to_status FROM application_events")
        ).all()
        versions = s.execute(text("SELECT reason FROM application_versions")).all()
    assert [tuple(e) for e in events] == [("TRANSITION", "DRAFT", "SUBMITTED")]
    assert [v[0] for v in versions] == ["SUBMIT"]


@pytest.mark.parametrize("value", [True, -1, 0, "25000000", 1_000_000_001])
async def test_invalid_collateral_does_not_change_draft(
    sokolova: httpx.AsyncClient, value: Any
) -> None:
    application = (await sokolova.post("/applications", json={})).json()
    response = await sokolova.patch(
        f"/applications/{application['id']}/draft",
        json={
            "version": application["version"],
            "answers": {"collateral": {"description": "Линия оборудования", "valueRub": value}},
        },
    )
    assert (response.status_code, response.json()["code"]) == (422, "INVALID_COLLATERAL")
    current = (await sokolova.get(f"/applications/{application['id']}")).json()
    assert current["version"] == application["version"]
    assert "collateral" not in current["draft"]


async def test_submit_without_terms_is_422(sokolova: httpx.AsyncClient) -> None:
    app_id = (await sokolova.post("/applications", json={"productCode": "EXPRESS"})).json()["id"]
    response = await submit(sokolova, app_id)
    assert response.status_code == 422
    assert {e["loc"][1] for e in response.json()["errors"]} == {"amount_rub", "term_months"}


async def test_second_application_in_progress_is_duplicate(sokolova: httpx.AsyncClient) -> None:
    first = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    await submit(sokolova, first)
    second = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    response = await submit(sokolova, second)
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_APPLICATION"
    assert (await sokolova.get(f"/applications/{second}")).json()["status"] == "DRAFT"
    withdrawn = await sokolova.post(f"/applications/{first}/withdraw")
    assert withdrawn.json()["status"] == "WITHDRAWN"
    assert (await submit(sokolova, second)).status_code == 200


async def test_concurrent_transitions_one_wins(sokolova: httpx.AsyncClient) -> None:
    app_id = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    await submit(sokolova, app_id)
    results: list[str] = []
    barrier = threading.Barrier(2)

    def move() -> None:
        with db.transaction() as s:
            application = s.get(Application, __import__("uuid").UUID(app_id))
            assert application is not None
            barrier.wait()
            try:
                transition(s, application, Status.CHECKING, actor=Actor.SYSTEM)
                results.append("ok")
            except AppError as exc:
                results.append(exc.code)

    threads = [threading.Thread(target=move) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["INVALID_TRANSITION", "ok"]
    with db.transaction() as s:
        row = s.execute(
            text("SELECT status, version FROM applications WHERE id = :i"), {"i": app_id}
        ).one()
    assert tuple(row) == ("CHECKING", 3)


async def test_journal_cannot_be_changed(sokolova: httpx.AsyncClient) -> None:
    app_id = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    await submit(sokolova, app_id)
    for statement in (
        "UPDATE application_events SET kind = 'NOTE'",
        "DELETE FROM application_events",
    ):
        with pytest.raises(Exception, match="неизменяем"), db.transaction() as s:
            s.execute(text(statement))
