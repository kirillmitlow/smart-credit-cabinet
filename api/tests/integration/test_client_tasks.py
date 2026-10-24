# ruff: noqa: F811
"""T-350, T-351: раунды задач клиенту, ответ, отправка раунда и перепроверка (20-03)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.modules import applications, auth, pipeline
from app.modules.applications import (
    Actor,
    Application,
    ApplicationEvent,
    InfoRequestReceipt,
    TaskSpec,
    client_tasks,
)
from app.modules.applications.models import Task
from app.modules.companies.models import CompanyMember
from app.modules.pipeline.models import PipelineRun
from app.shared import db, tasks
from app.shared.errors import AppError
from tests.integration.test_pipeline import (  # noqa: F401  (фикстуры)
    Case,
    database,
    sokolova,
    status_of,
)

pytestmark = pytest.mark.integration

GUARANTOR_INN = "770100000001"


@dataclass
class Crew:
    director: auth.Principal
    accountant: auth.Principal
    guarantor: auth.Principal
    outsider: auth.Principal
    company_id: UUID


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    box: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: box.append((name, kw)))
    return box


def principal(user_id: UUID, name: str, inn: str | None, company_id: UUID | None, role: str) -> Any:
    memberships = (auth.Membership(company_id, role),) if company_id is not None else ()
    return auth.Principal(
        user_id=user_id,
        role="CLIENT",
        zone=auth.Zone.CLIENT,
        display_name=name,
        person_inn=inn,
        memberships=memberships,
        active_company_id=company_id,
    )


@pytest.fixture
def crew(database: db.Database, sokolova: Case) -> Crew:
    with database.transaction() as s:
        application = s.get(Application, sokolova.application_id)
        assert application is not None
        company_id = application.company_id
        users: dict[str, tuple[UUID, str | None]] = {}
        for key, role, inn in (
            ("director", "DIRECTOR", "770100000009"),
            ("accountant", "ACCOUNTANT", None),
            ("guarantor", "GUARANTOR", GUARANTOR_INN),
            ("outsider", None, None),
        ):
            user = auth.upsert_client(
                s, login_ref=f"t:crew:{key}", display_name=key, person_inn=inn, scenario_code=None
            )
            users[key] = (user.id, inn)
            if role is not None:
                s.add(CompanyMember(company_id=company_id, user_id=user.id, role=role))
        s.flush()
    return Crew(
        principal(*users["director"][:1], "director", users["director"][1], company_id, "DIRECTOR"),
        principal(*users["accountant"][:1], "accountant", None, company_id, "ACCOUNTANT"),
        principal(*users["guarantor"][:1], "guarantor", GUARANTOR_INN, company_id, "GUARANTOR"),
        principal(*users["outsider"][:1], "outsider", None, None, "DIRECTOR"),
        company_id,
    )


def version_of(database: db.Database, application_id: UUID) -> int:
    with database.transaction() as s:
        application = s.get(Application, application_id)
        assert application is not None
        return application.version


def to_manual_review(database: db.Database, case: Case) -> None:
    case.world.down.add("registry:company")
    pipeline.run_pipeline(case.application_id, integrations=case.integrations)
    assert status_of(database, case.application_id) == "MANUAL_REVIEW"


def spec(title: str = "Пояснение по поставке", **kwargs: Any) -> TaskSpec:
    return TaskSpec(kind="EXPLANATION", title=title, why_text="Нужно для оценки", **kwargs)


def ask(
    database: db.Database, case: Case, items: list[TaskSpec] | None = None
) -> InfoRequestReceipt:
    with database.transaction() as s:
        return applications.request_information(
            s,
            case.application_id,
            expected_version=version_of(database, case.application_id),
            actor=Actor.UNDERWRITER,
            items=items or [spec()],
        )


def tasks_of(database: db.Database, application_id: UUID) -> list[Task]:
    with database.transaction() as s:
        rows = s.scalars(
            select(Task).where(Task.application_id == application_id).order_by(Task.created_at)
        ).all()
        s.expunge_all()
        return list(rows)


def answer(database: db.Database, who: auth.Principal, task_id: UUID, text: str = "Вот") -> None:
    with database.transaction() as s:
        client_tasks.save_answer(s, who, task_id, text)


def submit(database: db.Database, who: auth.Principal, application_id: UUID) -> None:
    with database.transaction() as s:
        client_tasks.submit_round(s, who, application_id)


def code_of(call: Any) -> str:
    with pytest.raises(AppError) as error:
        call()
    return error.value.code


def test_request_creates_tasks_events_and_needs_info_atomically(
    database: db.Database, sokolova: Case, crew: Crew
) -> None:
    to_manual_review(database, sokolova)

    receipt = ask(database, sokolova, [spec("Первая"), spec("Вторая")])

    assert (receipt.round, receipt.status, len(receipt.task_ids)) == (1, "NEEDS_INFO", 2)
    assert status_of(database, sokolova.application_id) == "NEEDS_INFO"
    rows = tasks_of(database, sokolova.application_id)
    assert [(t.round, t.status) for t in rows] == [(1, "OPEN"), (1, "OPEN")]
    with database.transaction() as s:
        codes = [
            e.step_code
            for e in s.scalars(select(ApplicationEvent).where(ApplicationEvent.kind == "TASK"))
        ]
    assert codes == ["TASK_CREATED", "TASK_CREATED"]


def test_invalid_item_rolls_back_everything(database: db.Database, sokolova: Case) -> None:
    to_manual_review(database, sokolova)

    bad = [spec("Ок"), spec("Плохой", assignee_user_id=uuid4())]
    with pytest.raises(AppError) as error:
        ask(database, sokolova, bad)

    assert error.value.code == "VALIDATION_ERROR"
    assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"
    assert tasks_of(database, sokolova.application_id) == []


def test_caller_rollback_leaves_no_tasks_and_no_transition(
    database: db.Database, sokolova: Case
) -> None:
    to_manual_review(database, sokolova)
    version = version_of(database, sokolova.application_id)

    with pytest.raises(RuntimeError):  # noqa: PT012
        with database.transaction() as s:
            applications.request_information(
                s,
                sokolova.application_id,
                expected_version=version,
                actor=Actor.UNDERWRITER,
                items=[spec()],
            )
            raise RuntimeError("откат вызывающего")

    assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"
    assert version_of(database, sokolova.application_id) == version
    assert tasks_of(database, sokolova.application_id) == []


def test_version_conflict_and_open_round(database: db.Database, sokolova: Case) -> None:
    to_manual_review(database, sokolova)
    stale = version_of(database, sokolova.application_id) - 1

    def stale_call() -> None:
        with database.transaction() as s:
            applications.request_information(
                s,
                sokolova.application_id,
                expected_version=stale,
                actor=Actor.UNDERWRITER,
                items=[spec()],
            )

    assert code_of(stale_call) == "VERSION_CONFLICT"
    ask(database, sokolova)
    # статус уже NEEDS_INFO, старый раунд открыт: второй запрос от банка недопустим
    assert code_of(lambda: ask(database, sokolova)) in {"INVALID_TRANSITION", "ROUND_OPEN"}


def test_three_rounds_max_each_answer_restarts_checking(
    database: db.Database, sokolova: Case, crew: Crew, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    to_manual_review(database, sokolova)
    for expected_round in (1, 2, 3):
        receipt = ask(database, sokolova)
        assert receipt.round == expected_round
        answer(database, crew.director, receipt.task_ids[0])
        submit(database, crew.accountant, sokolova.application_id)
        assert status_of(database, sokolova.application_id) == "CHECKING"
        pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
        assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"

    assert code_of(lambda: ask(database, sokolova)) == "ROUNDS_LIMIT_REACHED"
    assert sokolova.world.count("credit_bureau:report") == 1  # БКИ не покупали заново
    assert len([m for m in sent if m[0] == "pipeline.run"]) == 3
    with database.transaction() as s:
        runs = s.scalars(select(PipelineRun)).all()
        assert [r.trigger for r in runs].count("INFO_PROVIDED") == 3


def test_rights_foreign_company_is_404_and_assignees(
    database: db.Database, sokolova: Case, crew: Crew
) -> None:
    to_manual_review(database, sokolova)
    with database.transaction() as s:
        accountant_id = crew.accountant.user_id
    receipt = ask(
        database,
        sokolova,
        [
            spec("Бухгалтеру", assignee_user_id=accountant_id),
            TaskSpec(
                kind="GUARANTOR",
                title="Согласие поручителя",
                why_text="Нужно",
                assignee_person_inn=GUARANTOR_INN,
            ),
            spec("Любому"),
        ],
    )
    for_accountant, for_guarantor, for_any = receipt.task_ids

    def listing(who: auth.Principal) -> None:
        with database.transaction() as s:
            client_tasks.list_tasks(s, who, sokolova.application_id)

    assert code_of(lambda: listing(crew.outsider)) == "NOT_FOUND"
    assert code_of(lambda: answer(database, crew.outsider, for_any)) == "NOT_FOUND"
    assert code_of(lambda: answer(database, crew.guarantor, for_any)) == "NOT_FOUND"  # не видит
    assert code_of(lambda: answer(database, crew.director, for_guarantor)) == "FORBIDDEN"
    answer(database, crew.guarantor, for_guarantor)
    answer(database, crew.director, for_accountant)  # руководитель отвечает за сотрудника
    answer(database, crew.accountant, for_any)
    with database.transaction() as s:
        _, visible = client_tasks.list_tasks(s, crew.guarantor, sokolova.application_id)
        assert [t.id for t in visible] == [for_guarantor]
    # поручитель сам раунд не отправляет
    assert code_of(lambda: submit(database, crew.guarantor, sokolova.application_id)) == "FORBIDDEN"


def test_submit_needs_all_answers_and_runs_once(
    database: db.Database, sokolova: Case, crew: Crew, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    to_manual_review(database, sokolova)
    first, second = ask(database, sokolova, [spec("Раз"), spec("Два")]).task_ids
    answer(database, crew.director, first)

    assert (
        code_of(lambda: submit(database, crew.director, sokolova.application_id))
        == "ROUND_INCOMPLETE"
    )
    assert status_of(database, sokolova.application_id) == "NEEDS_INFO"
    answer(database, crew.director, first, "Правка")  # черновик можно менять
    answer(database, crew.director, second)
    submit(database, crew.director, sokolova.application_id)

    assert status_of(database, sokolova.application_id) == "CHECKING"
    assert sent == [("pipeline.run", {"application_id": str(sokolova.application_id)})]
    assert {t.status for t in tasks_of(database, sokolova.application_id)} == {"ANSWERED"}
    # двойное нажатие и повторный ответ
    assert (
        code_of(lambda: submit(database, crew.director, sokolova.application_id))
        == "ROUND_ALREADY_SENT"
    )
    assert code_of(lambda: answer(database, crew.director, first)) == "TASK_CLOSED"
    assert len(sent) == 1
    with database.transaction() as s:
        assert len(s.scalars(select(PipelineRun)).all()) == 2


def test_submit_rollback_keeps_drafts_and_sends_nothing(
    database: db.Database, sokolova: Case, crew: Crew, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    to_manual_review(database, sokolova)
    (task_id,) = ask(database, sokolova).task_ids
    answer(database, crew.director, task_id)

    with pytest.raises(RuntimeError):  # noqa: PT012
        with database.transaction() as s:
            client_tasks.submit_round(s, crew.director, sokolova.application_id)
            raise RuntimeError("откат")

    assert status_of(database, sokolova.application_id) == "NEEDS_INFO"
    (task,) = tasks_of(database, sokolova.application_id)
    assert task.status == "OPEN"
    assert task.answer is not None
    assert sent == []


def test_withdraw_cancels_open_tasks(database: db.Database, sokolova: Case, crew: Crew) -> None:
    to_manual_review(database, sokolova)
    ask(database, sokolova)

    with database.transaction() as s:
        application = applications.get_for(s, crew.director, sokolova.application_id)
        applications.service.withdraw(s, crew.director, application)

    (task,) = tasks_of(database, sokolova.application_id)
    assert (task.status, task.cancel_reason) == ("CANCELLED", "APPLICATION_WITHDRAWN")


def test_pipeline_creates_revenue_statement_task(database: db.Database, sokolova: Case) -> None:
    sokolova.world.turnover[sokolova.inn] = None
    sokolova.world.financials[sokolova.inn] = None

    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert status_of(database, sokolova.application_id) == "NEEDS_INFO"
    (task,) = tasks_of(database, sokolova.application_id)
    assert (task.kind, task.round, task.status) == ("DOCUMENT", 1, "OPEN")
    assert task.created_by_actor == "SYSTEM"
    assert task.details["reasonCode"] == "REVENUE_UNKNOWN"
