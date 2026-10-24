"""Ручки заявки для клиента (50-07). Роутер тонкий: разобрать → сервис → ответ (R6)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.modules.applications import service
from app.modules.applications.models import Application
from app.shared import db

router = APIRouter(prefix="/applications", tags=["заявки"])

ProductCode = Annotated[
    str, Field(pattern=r"^(EXPRESS|WORKING_CAPITAL|CONTRACT|CREDIT_LINE|OVERDRAFT|INVESTMENT)$")
]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ApplicationFields(Camel):
    product_code: ProductCode | None = None
    amount_rub: int | None = Field(default=None, gt=0, le=1_000_000_000)
    term_months: int | None = Field(default=None, ge=1, le=120)
    purpose_code: str | None = Field(default=None, max_length=32)


class DraftPatch(ApplicationFields):
    version: int = Field(ge=1)
    answers: dict[str, Any] = Field(
        default_factory=dict, description="Ответы мастера и анкеты по шагам"
    )


class ApplicationOut(Camel):
    """Клиентская модель: без баллов, DSCR и снимков источников."""

    id: UUID
    company_id: UUID
    number: str
    status: str
    product_code: str | None
    amount_rub: int | None
    term_months: int | None
    purpose_code: str | None
    draft: dict[str, Any]
    version: int
    created_at: datetime
    submitted_at: datetime | None
    allowed_actions: list[str]


class ApplicationPage(Camel):
    items: list[ApplicationOut]
    next_cursor: str | None


def _out(application: Application, principal: auth.Principal) -> ApplicationOut:
    return ApplicationOut(
        id=application.id,
        company_id=application.company_id,
        number=application.number,
        status=application.status,
        product_code=application.product_code,
        amount_rub=application.amount_rub,
        term_months=application.term_months,
        purpose_code=application.purpose_code,
        draft=application.draft,
        version=application.version,
        created_at=application.created_at,
        submitted_at=application.submitted_at,
        allowed_actions=service.allowed_actions(application, principal),
    )


def _create(principal: auth.Principal, body: ApplicationFields) -> ApplicationOut:
    with db.transaction() as session:
        principal = service.company_principal(session, principal)
        application = service.create(session, principal, body.model_dump(exclude_none=True))
        return _out(application, principal)


@router.post(
    "",
    operation_id="createApplication",
    summary="Создать черновик заявки",
    status_code=201,
    response_model=ApplicationOut,
    response_model_by_alias=True,
)
async def create(body: ApplicationFields, principal: auth.ClientPrincipal) -> ApplicationOut:
    return await run_in_threadpool(_create, principal, body)


def _list(principal: auth.Principal, limit: int, cursor: str | None) -> ApplicationPage:
    with db.transaction() as session:
        principal = service.company_principal(session, principal)
        rows, next_cursor = service.list_for(session, principal, limit, cursor)
        return ApplicationPage(items=[_out(a, principal) for a in rows], next_cursor=next_cursor)


@router.get(
    "",
    operation_id="listApplications",
    summary="Мои заявки, новые сверху",
    response_model=ApplicationPage,
    response_model_by_alias=True,
)
async def list_applications(
    principal: auth.ClientPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=40)] = None,
) -> ApplicationPage:
    return await run_in_threadpool(_list, principal, limit, cursor)


def _get(principal: auth.Principal, application_id: UUID) -> ApplicationOut:
    with db.transaction() as session:
        principal = service.company_principal(session, principal)
        return _out(service.get_for(session, principal, application_id), principal)


@router.get(
    "/{application_id}",
    operation_id="getApplication",
    summary="Заявка",
    response_model=ApplicationOut,
    response_model_by_alias=True,
)
async def get_application(application_id: UUID, principal: auth.ClientPrincipal) -> ApplicationOut:
    return await run_in_threadpool(_get, principal, application_id)


def _patch(principal: auth.Principal, application_id: UUID, body: DraftPatch) -> ApplicationOut:
    with db.transaction() as session:
        principal = service.company_principal(session, principal)
        application = service.get_for(session, principal, application_id)
        fields = body.model_dump(exclude_none=True, exclude={"version", "answers"})
        application = service.update_draft(session, application, body.version, fields, body.answers)
        return _out(application, principal)


@router.patch(
    "/{application_id}/draft",
    operation_id="patchApplicationDraft",
    summary="Автосохранение черновика",
    response_model=ApplicationOut,
    response_model_by_alias=True,
)
async def patch_draft(
    application_id: UUID, body: DraftPatch, principal: auth.ClientPrincipal
) -> ApplicationOut:
    return await run_in_threadpool(_patch, principal, application_id, body)


def _submit(principal: auth.Principal, application_id: UUID) -> ApplicationOut:
    with db.transaction() as session:
        principal = service.company_principal(session, principal)
        application = service.get_for(session, principal, application_id)
        return _out(service.submit(session, principal, application), principal)


@router.post(
    "/{application_id}/submit",
    operation_id="submitApplication",
    summary="Отправить заявку",
    response_model=ApplicationOut,
    response_model_by_alias=True,
)
async def submit(application_id: UUID, principal: auth.ClientPrincipal) -> ApplicationOut:
    return await run_in_threadpool(_submit, principal, application_id)


def _withdraw(principal: auth.Principal, application_id: UUID) -> ApplicationOut:
    with db.transaction() as session:
        application = service.get_for(session, principal, application_id)
        return _out(service.withdraw(session, principal, application), principal)


@router.post(
    "/{application_id}/withdraw",
    operation_id="withdrawApplication",
    summary="Отозвать заявку",
    response_model=ApplicationOut,
    response_model_by_alias=True,
)
async def withdraw(application_id: UUID, principal: auth.ClientPrincipal) -> ApplicationOut:
    return await run_in_threadpool(_withdraw, principal, application_id)
