"""T-363: задачи, отправленные ответы, новый запуск и свежий БКИ через HTTP банка."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.modules import applications, audit, auth, pipeline
from app.modules.applications.models import Task
from app.modules.pipeline.models import PipelineRun
from app.shared import db, operations, tasks
from app.shared.models import IdempotencyKey
from tests.fixtures import pipeline_world as pw
from tests.integration.test_backoffice_decision import set_level
from tests.integration.test_backoffice_queue import bank as bank
from tests.integration.test_backoffice_queue import seed
from tests.integration.test_pipeline import consents_for, make_application

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def sent(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    with db.transaction() as session:
        session.execute(text("TRUNCATE idempotency_keys"))
    deliveries: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: deliveries.append((name, kw)))
    yield deliveries
    pipeline.set_consents_provider(None)


def info(version: int = 3, **changes: Any) -> dict[str, Any]:
    return {
        "expectedVersion": version,
        "reasonCode": "UW_NEW_INFO",
        "items": [
            {
                "kind": "EXPLANATION",
                "title": "Поясните закупку",
                "whyText": "Для оценки расходов",
                "what": "Сроки поставки",
                "where": "В договоре",
            }
        ],
        **changes,
    }


async def post(
    bank: httpx.AsyncClient, app_id: UUID, action: str, body: dict[str, Any], key: str = "one"
) -> httpx.Response:
    return await bank.post(
        f"/backoffice/applications/{app_id}/{action}",
        json=body,
        headers={"Idempotency-Key": key},
    )


def state(app_id: UUID) -> tuple[str, int]:
    with db.transaction() as session:
        app = session.get(applications.Application, app_id)
        assert app is not None
        return app.status, app.version


def client_cookie(bank: httpx.AsyncClient, app_id: UUID) -> None:
    with db.transaction() as session:
        app = session.get(applications.Application, app_id)
        assert app is not None
        user_id, company_id = app.created_by, app.company_id
    bank.cookies.set(
        "sid_client",
        auth.sessions.create(
            auth.Principal(
                user_id=user_id,
                role="CLIENT",
                zone=auth.Zone.CLIENT,
                display_name="Клиент",
                memberships=(auth.Membership(company_id, "DIRECTOR"),),
                active_company_id=company_id,
            )
        ),
    )


async def test_request_round_replays_and_card_never_exposes_draft(
    bank: httpx.AsyncClient, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    app_id, other = seed("СтанкоПром"), seed("Сосед")
    await set_level(bank, "L1")
    first = await post(bank, app_id, "request-info", info())
    assert first.status_code == 200, first.text
    assert (first.json()["status"], first.json()["round"], first.json()["version"]) == (
        "NEEDS_INFO",
        1,
        4,
    )
    task_id = first.json()["taskIds"][0]
    replay = await post(bank, app_id, "request-info", info())
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    client_cookie(bank, app_id)
    response = await bank.post(
        f"/tasks/{task_id}/answer", json={"text": "Ответ клиента для отправки банку"}
    )
    assert response.status_code == 200, response.text
    card = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    assert card["clientTasks"][0]["answer"] is None
    assert card["clientTasks"][0]["answeredBy"] is None
    assert card["clientTasks"][0]["answeredAt"] is None
    assert "Ответ клиента для отправки банку" not in str(card)
    assert card["latestAnsweredRound"] is None
    assert card["clientTasks"][0]["what"] == "Сроки поставки"
    assert (await bank.get(f"/backoffice/applications/{other}")).json()["clientTasks"] == []
    submitted = await bank.post(f"/applications/{app_id}/tasks/submit")
    assert submitted.status_code == 200, submitted.text
    assert state(app_id) == ("CHECKING", 5)
    card = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    assert card["clientTasks"][0]["answer"] == "Ответ клиента для отправки банку"
    assert card["latestAnsweredRound"] == 1
    assert card["clientTasks"][0]["answeredAt"] is not None
    assert len(sent) == 1
    assert sent[0][0] == "pipeline.run"
    with db.transaction() as session:
        assert len(session.scalars(select(Task).where(Task.application_id == app_id)).all()) == 1
        assert (
            session.scalars(
                select(audit.AuditRecord).where(
                    audit.AuditRecord.action == "UNDERWRITER_REQUEST_INFO",
                    audit.AuditRecord.object_id == str(app_id),
                )
            )
            .one()
            .details["round"]
            == 1
        )


@pytest.mark.parametrize("action", ["request-info", "recheck"])
async def test_stale_missing_role_and_missing_application(
    bank: httpx.AsyncClient, action: str
) -> None:
    app_id = seed("СтанкоПром")
    body = info(2) if action == "request-info" else {"expectedVersion": 2}
    stale = await post(bank, app_id, action, body)
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    assert (await post(bank, uuid4(), action, body)).status_code == 404
    bank.cookies.clear()
    assert (await post(bank, app_id, action, body)).status_code == 401


async def test_request_requires_reason_and_real_assignee(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    for body in (
        info(reasonCode="BAD"),
        info(items=[]),
        info(items=[{"kind": "EXPLANATION", "title": " ", "whyText": "Причина"}]),
        info(
            items=[
                {
                    "kind": "EXPLANATION",
                    "title": "Ответ",
                    "whyText": "Причина",
                    "assigneeUserId": str(uuid4()),
                }
            ]
        ),
        info(
            items=[
                {
                    "kind": "EXPLANATION",
                    "title": "Ответ",
                    "whyText": "Причина",
                    "assigneePersonInn": "770100000001",
                }
            ]
        ),
    ):
        response = await post(bank, app_id, "request-info", body)
        assert response.status_code == 422, response.text
    assert state(app_id) == ("MANUAL_REVIEW", 3)


async def test_fourth_round_is_forbidden_with_no_side_effect(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    with db.transaction() as session:
        for n in range(1, 4):
            session.add(
                Task(
                    application_id=app_id,
                    round=n,
                    kind="EXPLANATION",
                    title="Ответ",
                    why_text="Причина",
                    status="ANSWERED",
                    created_by_actor="UNDERWRITER",
                )
            )
    response = await post(bank, app_id, "request-info", info())
    assert response.status_code == 409
    assert response.json()["code"] == "ROUNDS_LIMIT_REACHED"
    assert state(app_id) == ("MANUAL_REVIEW", 3)


async def test_recheck_enqueues_once_after_commit_and_replays(
    bank: httpx.AsyncClient, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    app_id = seed("СтанкоПром")
    await set_level(bank, "L1")
    first = await post(bank, app_id, "recheck", {"expectedVersion": 3})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "CHECKING"
    assert state(app_id) == ("CHECKING", 4)
    replay = await post(bank, app_id, "recheck", {"expectedVersion": 3})
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert len(sent) == 1
    repeated = await post(bank, app_id, "recheck", {"expectedVersion": 4}, key="two")
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "RECHECK_ALREADY_RUNNING"
    with db.transaction() as session:
        assert (
            len(
                session.scalars(
                    select(PipelineRun).where(PipelineRun.application_id == app_id)
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize("action", ["request-info", "recheck"])
async def test_audit_failure_rolls_back_tasks_run_transition_and_key(
    bank: httpx.AsyncClient,
    action: str,
    monkeypatch: pytest.MonkeyPatch,
    sent: list[tuple[str, dict[str, Any]]],
) -> None:
    app_id = seed("СтанкоПром")

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError, match="audit failed"):
        await post(
            bank, app_id, action, info() if action == "request-info" else {"expectedVersion": 3}
        )
    assert state(app_id) == ("MANUAL_REVIEW", 3)
    assert sent == []
    with db.transaction() as session:
        assert session.scalars(select(Task)).all() == []
        assert session.scalars(select(IdempotencyKey)).all() == []
        assert len(session.scalars(select(PipelineRun)).all()) == 1


@pytest.mark.parametrize("action", ["request-info", "recheck"])
async def test_persona_reset_excludes_bank_commands(bank: httpx.AsyncClient, action: str) -> None:
    app_id = seed("СтанкоПром")
    scope = applications.operation_scope(app_id)
    assert scope is not None
    with operations.hold(lambda: scope, exclusive=True):
        result = await post(
            bank, app_id, action, info() if action == "request-info" else {"expectedVersion": 3}
        )
    assert result.status_code == 409
    assert result.json()["code"] == "DEMO_RESET_IN_PROGRESS"
    assert state(app_id) == ("MANUAL_REVIEW", 3)


@pytest.mark.parametrize("failure", ["registry:company", "credit_bureau:report"])
async def test_source_recovery_via_http_and_bureau_snapshot_reuse(
    bank: httpx.AsyncClient,
    failure: str,
) -> None:
    world = pw.sokolova_world()
    pipeline.set_consents_provider(consents_for((pw.SOKOLOVA_INN, "COMPANY")))
    case = make_application(
        db.get_database(),
        world,
        inn=pw.SOKOLOVA_INN,
        kind="IP",
        product="EXPRESS",
        amount=500_000,
        term=12,
    )
    world.down.add(failure)
    pipeline.run_pipeline(case.application_id, integrations=case.integrations)
    assert state(case.application_id)[0] == "MANUAL_REVIEW"
    before = world.count("credit_bureau:report")
    world.down.clear()
    response = await post(
        bank, case.application_id, "recheck", {"expectedVersion": state(case.application_id)[1]}
    )
    assert response.status_code == 200, response.text
    pipeline.run_pipeline(case.application_id, integrations=case.integrations)
    assert state(case.application_id)[0] == "APPROVED"
    assert world.count("credit_bureau:report") == before + (failure == "credit_bureau:report")


async def test_stankoprom_request_answer_recheck_manual_approval_without_second_bki(
    bank: httpx.AsyncClient,
) -> None:
    """Оракул30-17: настоящий конвейер, HTTP банка/клиента, внешние источники подставные."""
    inn, director = "0017654322", "001310000115"
    financials = pw.financials(inn, 420_000_000, 30_700_000, 1_900_000)
    for line, previous in (("2110", 388_000_000), ("2400", 27_400_000), ("2330", 3_100_000)):
        financials["lines"][line]["previous"] = previous
    world = pw.World(
        registry={
            inn: {
                "type": "LEGAL_ENTITY",
                "inn": inn,
                "ogrn": "1170000000001",
                "shortName": "ООО Станкопром",
                "registrationDate": "2017-03-14",
                "status": {"code": "ACTIVE"},
                "okvedMain": {"code": "25.62"},
                "director": {"fullName": "Кузнецов Игорь Петрович", "inn": director},
                "founders": [
                    {
                        "type": "PERSON",
                        "fullName": "Кузнецов Игорь Петрович",
                        "inn": director,
                        "sharePercent": 100,
                    }
                ],
            }
        },
        tax={inn: pw.tax_profile(inn, "OSNO")},
        financials={inn: financials},
        customer={inn: None},
        turnover={inn: None},
        loans={inn: None},
        screening={inn: pw.screening((inn, "COMPANY"), (director, "DIRECTOR"))},
        bki={
            inn: pw.report(
                inn,
                "LEGAL_ENTITY",
                history_months=84,
                closed=2,
                obligations=[
                    pw.obligation("sp1", "LOAN", "CLOSED"),
                    pw.obligation("sp2", "LOAN", "CLOSED"),
                ],
            ),
            director: pw.report(
                director,
                "PERSON",
                history_months=96,
                active=1,
                closed=1,
                debt=90_000,
                payments=4_500,
                obligations=[
                    pw.obligation("card", "CREDIT_CARD", payment=4_500, balance=90_000),
                    pw.obligation("loan", "LOAN", "CLOSED"),
                ],
            ),
        },
    )
    pipeline.set_consents_provider(consents_for((inn, "COMPANY"), (director, "DIRECTOR")))
    case = make_application(
        db.get_database(),
        world,
        inn=inn,
        kind="LEGAL",
        product="INVESTMENT",
        amount=15_000_000,
        term=60,
        draft={"collateral": {"description": "покупаемая линия", "valueRub": 25_000_000}},
    )
    app_id = case.application_id
    pipeline.run_pipeline(app_id, integrations=case.integrations)
    assert state(app_id)[0] == "MANUAL_REVIEW"
    bki_calls = world.count("credit_bureau:report")
    assert bki_calls == 2
    response = await post(bank, app_id, "request-info", info(state(app_id)[1]))
    assert response.status_code == 200, response.text
    client_cookie(bank, app_id)
    task_id = response.json()["taskIds"][0]
    answer = await bank.post(
        f"/tasks/{task_id}/answer",
        json={"text": "Поставщик подтвердил сроки поставки линии", "submitRound": True},
    )
    assert answer.status_code == 200, answer.text
    assert state(app_id)[0] == "CHECKING"
    pipeline.run_pipeline(app_id, integrations=case.integrations)
    assert state(app_id)[0] == "MANUAL_REVIEW"
    assert world.count("credit_bureau:report") == bki_calls
    card = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    assert card["latestAnsweredRound"] == 1
    decision = await post(
        bank,
        app_id,
        "decision",
        {
            "expectedVersion": state(app_id)[1],
            "engineDecisionId": card["engineDecisionId"],
            "outcome": "APPROVED",
            "terms": {"productCode": "INVESTMENT", "amountRub": 15_000_000, "termMonths": 60},
        },
    )
    assert decision.status_code == 200, decision.text
    assert state(app_id)[0] == "APPROVED"
