"""Ручки «Что нужно от вас» для клиента (T-351, 20-03, 50-07). Роутер тонкий (R6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.modules.applications import client_tasks, service
from app.modules.applications.models import Application, Task
from app.shared import db
from app.shared.errors import not_found

router = APIRouter(tags=["задачи клиенту"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TaskOut(Camel):
    id: UUID
    application_id: UUID
    round: int
    kind: str
    title: str
    why_text: str
    details: dict[str, Any]
    assignee_user_id: UUID | None
    assignee_person_inn: str | None
    status: str = Field(description="OPEN | ANSWERED | EXPIRED | CANCELLED")
    expires_at: datetime | None
    draft_answer: str | None = Field(
        description="Черновик ответа, пока задача открыта; банк его не видит"
    )
    answer: str | None = Field(description="Отправленный ответ")
    can_answer: bool
    document_ready: bool = Field(
        default=True,
        description="Все требуемые файлы проверены; поступления подтверждены, если нужна выручка",
    )
    created_at: datetime
    answered_at: datetime | None


class TaskList(Camel):
    items: list[TaskOut]
    current_round: int
    rounds_limit: int
    can_submit: bool = Field(
        description="Раунд открыт, на все задачи есть ответ и обязательные документы готовы"
    )


class AnswerBody(Camel):
    text: str = Field(min_length=1, max_length=4000)
    submit_round: bool = Field(
        default=False, description="Сразу отправить раунд, если это был последний ответ"
    )


def _out(
    principal: auth.Principal, application: Application, task: Task, document_ready: bool
) -> TaskOut:
    text = (task.answer or {}).get("text")
    sent = task.status == "ANSWERED"
    return TaskOut(
        id=task.id,
        application_id=task.application_id,
        round=task.round,
        kind=task.kind,
        title=task.title,
        why_text=task.why_text,
        details=task.details,
        assignee_user_id=task.assignee_user_id,
        assignee_person_inn=task.assignee_person_inn,
        status=task.status,
        expires_at=task.expires_at,
        draft_answer=None if sent else text,
        answer=text if sent else None,
        document_ready=document_ready,
        can_answer=task.status == "OPEN" and client_tasks.can_answer(principal, application, task),
        created_at=task.created_at,
        answered_at=task.answered_at,
    )


def _list_out(
    session: Session, principal: auth.Principal, application: Application, tasks: list[Task]
) -> TaskList:
    ready = client_tasks.document_readiness(session, principal, application, tasks)
    member = principal.membership(application.company_id)
    current = max((t.round for t in tasks), default=0)
    latest_open = [t for t in tasks if t.round == current and t.status == "OPEN"]
    return TaskList(
        items=[_out(principal, application, t, ready[t.id]) for t in tasks],
        current_round=current,
        rounds_limit=client_tasks.MAX_ROUNDS,
        can_submit=member is not None
        and member.role in {"DIRECTOR", "ACCOUNTANT"}
        and bool(latest_open)
        and all(t.answer is not None and ready[t.id] for t in latest_open),
    )


def _list(principal: auth.Principal, application_id: UUID) -> TaskList:
    with db.transaction() as session:
        principal = service.task_principal(session, principal)
        application, tasks = client_tasks.list_tasks(session, principal, application_id)
        return _list_out(session, principal, application, tasks)


@router.get(
    "/applications/{application_id}/tasks",
    operation_id="listApplicationTasks",
    summary="Что нужно от вас: задачи заявки",
    response_model=TaskList,
    response_model_by_alias=True,
)
async def list_tasks(application_id: UUID, principal: auth.ClientPrincipal) -> TaskList:
    return await run_in_threadpool(_list, principal, application_id)


def _answer(principal: auth.Principal, task_id: UUID, body: AnswerBody) -> TaskOut:
    with db.transaction() as session:
        principal = service.task_principal(session, principal)
        task = client_tasks.save_answer(session, principal, task_id, body.text)
        application = session.get(Application, task.application_id)
        if application is None:
            raise not_found("Задача")
        if body.submit_round:
            client_tasks.submit_round(session, principal, task.application_id)
            session.refresh(task)
        return _out(
            principal,
            application,
            task,
            client_tasks.document_readiness(session, principal, application, [task])[task.id],
        )


@router.post(
    "/tasks/{task_id}/answer",
    operation_id="answerTask",
    summary="Ответить на задачу текстом (черновик; банк увидит после отправки раунда)",
    response_model=TaskOut,
    response_model_by_alias=True,
)
async def answer_task(task_id: UUID, body: AnswerBody, principal: auth.ClientPrincipal) -> TaskOut:
    return await run_in_threadpool(_answer, principal, task_id, body)


def _submit(principal: auth.Principal, application_id: UUID) -> TaskList:
    with db.transaction() as session:
        principal = service.task_principal(session, principal)
        application, _ = client_tasks.submit_round(session, principal, application_id)
        _, tasks = client_tasks.list_tasks(session, principal, application_id)
        return _list_out(session, principal, application, tasks)


@router.post(
    "/applications/{application_id}/tasks/submit",
    operation_id="submitTaskRound",
    summary="Отправить ответ банку: все задачи раунда разом, заявка уходит на проверку",
    response_model=TaskList,
    response_model_by_alias=True,
)
async def submit_round(application_id: UUID, principal: auth.ClientPrincipal) -> TaskList:
    return await run_in_threadpool(_submit, principal, application_id)
