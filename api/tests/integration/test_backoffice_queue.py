"""T-360: реальный PostgreSQL, снимки настоящего ядра и банковская авторизация."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from app.main import create_app
from app.modules import auth, pipeline
from app.modules.applications import Application, ApplicationEvent, ApplicationVersion
from app.modules.companies.models import Company
from app.modules.decisioning import DecisionInput, decide
from app.modules.pipeline.models import PipelineRun
from app.modules.pipeline.persist import build_decision
from app.shared import clock, db
from app.shared.cache import get_redis
from app.shared.settings import Settings
from tests.fixtures import core_personas as cases

pytestmark = pytest.mark.integration


@pytest.fixture
async def bank(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, demo_mode=True))
    db.migrate(db.get_database().engine)
    with db.transaction() as session:
        session.execute(text("TRUNCATE applications, companies, users, policy_versions CASCADE"))
    get_redis().flushdb()
    fixed_now = clock.now()
    clock.set_clock(clock.Clock(real_now=lambda: fixed_now))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        assert (await client.post("/auth/bank-demo-login")).status_code == 200
        yield client
    db.get_database().dispose()
    clock.set_clock(clock.Clock())


def seed(
    name: str,
    inp: DecisionInput | None = None,
    *,
    status: str | None = None,
    hours: int = 1,
    version_reason: str = "SUBMIT",
    manual_history: bool = True,
    event_reason: str | None = None,
    without_decision: bool = False,
) -> UUID:
    inp = inp or cases.stankoprom()
    with db.transaction() as session:
        company = Company(
            inn=f"{uuid4().int % 10**10:010d}", kind="LEGAL", name=name, is_bank_customer=False
        )
        session.add(company)
        session.flush()
        user = auth.upsert_client(
            session,
            login_ref=str(uuid4()),
            display_name="Клиент",
            person_inn=None,
            scenario_code=None,
        )
        at = clock.now() - timedelta(hours=hours)
        result = decide(inp)
        outcome = "REJECTED" if result.outcome.value == "NOT_ELIGIBLE" else result.outcome.value
        app = Application(
            number=f"АЗ-{uuid4().hex[:12]}",
            company_id=company.id,
            created_by=user.id,
            status=status or outcome,
            product_code=inp.application.product.value,
            amount_rub=inp.application.amount_rub,
            term_months=inp.application.term_months,
            version=3,
            flags=[],
            created_at=at - timedelta(days=10),
            submitted_at=at,
        )
        session.add(app)
        session.flush()
        version = ApplicationVersion(
            application_id=app.id, number=1, reason=version_reason, data={}, data_hash="h"
        )
        session.add(version)
        session.flush()
        app.current_version_id = version.id
        policy = pipeline.register_current(session)
        run = PipelineRun(
            application_id=app.id, version_id=version.id, run_key=str(uuid4()), trigger="SUBMIT"
        )
        session.add(run)
        session.flush()
        decision = build_decision(
            run,
            inp,
            result,
            policy_version_id=policy.id,
            engine_version="test",
            snapshot_ids=[],
        )
        if not without_decision:
            session.add(decision)
        if manual_history:
            session.add(
                ApplicationEvent(
                    application_id=app.id,
                    at=at,
                    kind="TRANSITION",
                    from_status="CHECKING",
                    to_status="MANUAL_REVIEW",
                    actor_type="SYSTEM",
                    reason_code=event_reason,
                )
            )
        return app.id


async def test_queue_uses_engine_manual_routes_and_never_auto_declines(
    bank: httpx.AsyncClient,
) -> None:
    manual = {
        "stankoprom": cases.stankoprom(),
        "zarya": cases.zarya(),
        "quick-start": cases.quick_start(with_guarantor=True),
        "t-mass": cases.t_mass(),
        "t-overdue-45": cases.t_overdue_45(),
        "t-mismatch": cases.t_mismatch(),
        "t-young-collateral": cases.t_young_collateral(),
    }
    ids = {seed(name, inp) for name, inp in manual.items()}
    seed("Автоотказ", cases.romashka(), manual_history=False)
    seed("Ошибочно оставленный стоп-отказ", cases.romashka(), status="MANUAL_REVIEW")
    seed("Одобрено автоматом", cases.sokolova(), manual_history=False)
    response = await bank.get("/backoffice/queue")
    assert response.status_code == 200
    items = response.json()["items"]
    assert {UUID(x["id"]) for x in items} == ids
    assert {x["company"]["name"] for x in items} == set(manual)
    stanko = next(x for x in items if x["company"]["name"] == "stankoprom")
    assert [r["code"] for r in stanko["manualReasons"]] == [
        "AMOUNT_ABOVE_AUTO_LIMIT",
        "COLLATERAL_REVIEW",
    ]
    assert stanko["manualReasons"][0]["detail"].startswith("Сумма ")
    assert stanko["recommendation"] == {"outcome": "APPROVED", "hint": "REQUEST_SELLER_DOCUMENT"}
    assert stanko["requiredLevel"] == "L1"
    assert stanko["company"]["isBankCustomer"] is False
    assert stanko["documentReceived"] is None
    assert "score" not in stanko
    assert "snapshots" not in stanko


async def test_oldest_status_entry_first_and_keyset_has_no_duplicates(
    bank: httpx.AsyncClient,
) -> None:
    ids = {seed(f"Компания {i}", hours=5 if i < 3 else 2) for i in range(5)}
    first = (await bank.get("/backoffice/queue", params={"limit": 2})).json()
    second = (
        await bank.get("/backoffice/queue", params={"limit": 2, "cursor": first["nextCursor"]})
    ).json()
    third = (
        await bank.get("/backoffice/queue", params={"limit": 2, "cursor": second["nextCursor"]})
    ).json()
    items = first["items"] + second["items"] + third["items"]
    assert len(items) == len(ids) == 5
    assert {UUID(x["id"]) for x in items} == ids
    assert third["nextCursor"] is None
    assert [x["waitingSince"] for x in items] == sorted(x["waitingSince"] for x in items)
    assert all(x["version"] == 3 for x in items)


async def test_filters_status_product_and_cursor_binding(bank: httpx.AsyncClient) -> None:
    seed("Инвестиционный", cases.stankoprom())
    seed("Линия", cases.zarya())
    waiting = seed("Запрос информации", status="NEEDS_INFO")
    seed(
        "Автоматическая нехватка данных",
        cases.stankoprom(),
        status="NEEDS_INFO",
        manual_history=False,
    )
    line = (await bank.get("/backoffice/queue", params={"productCode": "CREDIT_LINE"})).json()
    assert [x["company"]["name"] for x in line["items"]] == ["Линия"]
    info = (await bank.get("/backoffice/queue", params={"status": "NEEDS_INFO"})).json()
    assert [UUID(x["id"]) for x in info["items"]] == [waiting]
    first = (await bank.get("/backoffice/queue", params={"limit": 1})).json()
    wrong_filter = await bank.get(
        "/backoffice/queue", params={"cursor": first["nextCursor"], "status": "NEEDS_INFO"}
    )
    assert wrong_filter.status_code == 422


async def test_latest_engine_is_used_without_join_duplicates(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    with db.transaction() as session:
        policy = pipeline.register_current(session)
        # Новый снимок, без run_id; прежний не редактируется.
        run = PipelineRun(
            id=uuid4(),
            application_id=app_id,
            version_id=uuid4(),
            run_key="unused",
            trigger="SUBMIT",
        )
        inp = cases.stankoprom()
        result = decide(inp)
        decision = build_decision(
            run, inp, result, policy_version_id=policy.id, engine_version="v2", snapshot_ids=[]
        )
        decision.run_id = None
        decision.created_at = clock.now() + timedelta(seconds=10)
        decision.required_level = "L2"
        session.add(decision)
    items = (await bank.get("/backoffice/queue")).json()["items"]
    assert len(items) == 1
    assert items[0]["requiredLevel"] == "L2"


async def test_returned_answer_and_source_failure_are_explicit(bank: httpx.AsyncClient) -> None:
    seed("Ответил", version_reason="INFO_PROVIDED", event_reason="SOURCE_UNAVAILABLE")
    item = (await bank.get("/backoffice/queue")).json()["items"][0]
    assert item["badges"] == ["CLIENT_ANSWERED", "SOURCE_UNAVAILABLE"]
    assert "SOURCE_UNAVAILABLE" in [r["code"] for r in item["manualReasons"]]


async def test_pipeline_error_without_decision_stays_visible(bank: httpx.AsyncClient) -> None:
    seed("Сбой конвейера", without_decision=True, event_reason="PIPELINE_ERROR")
    item = (await bank.get("/backoffice/queue")).json()["items"][0]
    assert item["recommendation"] is None
    assert item["requiredLevel"] is None
    assert item["badges"] == ["PIPELINE_ERROR"]
    assert item["manualReasons"][0]["code"] == "PIPELINE_ERROR"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"status": "whatever"},
        {"productCode": "bad"},
        {"cursor": "not base64"},
        {"cursor": "W10="},
        {"cursor": "bnVsbA=="},
    ],
)
async def test_invalid_filter_or_cursor_is_422(
    bank: httpx.AsyncClient, params: dict[str, Any]
) -> None:
    assert (await bank.get("/backoffice/queue", params=params)).status_code == 422


async def test_bank_guard_does_not_accept_client_cookie(bank: httpx.AsyncClient) -> None:
    sid = bank.cookies["sid_bank"]
    bank.cookies.clear()
    assert (await bank.get("/backoffice/queue")).status_code == 401
    bank.cookies.set("sid_client", sid)
    assert (await bank.get("/backoffice/queue")).status_code == 401
    bank.cookies.clear()
    bank.cookies.set(
        "sid_bank",
        auth.sessions.create(
            auth.Principal(
                user_id=uuid4(),
                role="CLIENT",
                zone=auth.Zone.BANK,
                display_name="Клиент",
            )
        ),
    )
    assert (await bank.get("/backoffice/queue")).status_code == 403


@pytest.mark.parametrize(("role", "level"), [("ADMIN", "L2"), ("UNDERWRITER", "L1")])
async def test_both_bank_roles_and_l1_can_read_queue(
    bank: httpx.AsyncClient, role: str, level: str
) -> None:
    user_id = UUID((await bank.get("/auth/bank-me")).json()["userId"])
    with db.transaction() as session:
        user = session.get(auth.User, user_id)
        assert user is not None
        user.role, user.level = role, level
    seed("СтанкоПром")
    response = await bank.get("/backoffice/queue")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_queue_does_not_mutate_application_or_decision(bank: httpx.AsyncClient) -> None:
    seed("СтанкоПром")

    def counts() -> list[Any]:
        with db.transaction() as session:
            return list(
                session.execute(
                    text(
                        "SELECT status, version, (SELECT count(*) FROM decisions), "
                        "(SELECT count(*) FROM application_events) FROM applications"
                    )
                ).one()
            )

    before = counts()
    assert (await bank.get("/backoffice/queue")).status_code == 200
    assert counts() == before
