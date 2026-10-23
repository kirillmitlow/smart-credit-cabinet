"""Вход клиента по ИНН и одноразовому коду (T-212, D-062, 10-03 «Вход»).

Ручки живут в companies, а не в auth: шаг «ИНН → люди компании» опирается на участников
компании, а companies стоит в графе модулей выше auth (50-04).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from app.modules import audit, auth
from app.modules.companies import service, sync
from app.modules.companies.models import Company, CompanyMember
from app.modules.integrations import scenarios
from app.shared import db
from app.shared.errors import AppError
from app.shared.settings import get_settings

router = APIRouter(tags=["вход"])
LOGIN = "LOGIN"


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CompanyBrief(Camel):
    id: UUID
    inn: str
    name: str
    status: str | None
    can_apply: bool


class PersonOption(Camel):
    user_id: UUID
    display_name: str
    role: str


class CompanyChoice(Camel):
    company: CompanyBrief
    role: str


class RolesResponse(Camel):
    kind: Literal["COMPANY", "PERSON", "NOT_ELIGIBLE"]
    company: CompanyBrief | None = None
    people: list[PersonOption] = []
    companies: list[CompanyChoice] = []
    reason_code: str | None = None


class CodeRequest(Camel):
    user_id: UUID
    company_id: UUID | None = None


class CodeIssued(Camel):
    request_id: str
    expires_in_seconds: int
    demo_code: str | None = Field(default=None, description="Только в демо-режиме: код вместо SMS")


class CodeCheck(Camel):
    request_id: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^\d{6}$")


class ActiveCompany(Camel):
    company_id: UUID


class MeResponse(Camel):
    user_id: UUID
    display_name: str
    role: str
    active_company_id: UUID | None
    companies: list[CompanyChoice]


class PublicConfig(Camel):
    demo_mode: bool
    product_name: str
    version: str
    nlu_available: bool
    demo_code_required: bool = False
    docs_links: dict[str, str] = Field(default_factory=dict)


def _brief(company: Company) -> CompanyBrief:
    return CompanyBrief(
        id=company.id,
        inn=company.inn,
        name=company.name,
        status=company.status,
        can_apply=company.status in (None, "ACTIVE"),
    )


def _lookup(inn: str) -> RolesResponse | None:
    with db.transaction() as session:
        company = service.by_inn(session, inn)
        if company is not None:
            if company.kind == "SELF_EMPLOYED":
                return RolesResponse(
                    kind="NOT_ELIGIBLE", company=_brief(company), reason_code="SELF_EMPLOYED"
                )
            people = [
                PersonOption(user_id=u.id, display_name=u.display_name, role=m.role)
                for m, u in service.members(session, company.id)
            ]
            return RolesResponse(kind="COMPANY", company=_brief(company), people=people)
        users = auth.by_person_inn(session, inn) if len(inn) == 12 else []
        choices = [
            CompanyChoice(company=_brief(c), role=m.role)
            for user in users
            for m, c in service.memberships_of(session, user.id)
        ]
        if users and choices:
            people = [
                PersonOption(user_id=u.id, display_name=u.display_name, role="PERSON")
                for u in users
            ]
            return RolesResponse(kind="PERSON", people=people, companies=choices)
    return None


def _sync() -> None:
    try:
        sync.refresh_directory()
    except scenarios.ScenariosUnavailableError as exc:
        raise AppError(503, "DIRECTORY_UNAVAILABLE", "Справочник демо-компаний недоступен") from exc


@router.get(
    "/auth/roles/{inn}",
    operation_id="getLoginRoles",
    summary="Кто может войти по ИНН: люди компании или компании человека (сессию не создаёт)",
    response_model=RolesResponse,
    response_model_by_alias=True,
)
async def roles(inn: Annotated[str, Path(pattern=r"^\d{10}$|^\d{12}$")]) -> RolesResponse:
    if not service.inn_is_valid(inn):
        raise AppError(422, "INN_INVALID", "Неверная контрольная сумма ИНН")
    found = await run_in_threadpool(_lookup, inn)
    if found is None:
        await run_in_threadpool(_sync)  # компания могла появиться в сценариях после старта
        found = await run_in_threadpool(_lookup, inn)
    if found is None:
        raise AppError(404, "INN_NOT_FOUND", "По этому ИНН нет демо-компании или человека")
    return found


def _issue(body: CodeRequest) -> CodeIssued:
    with db.transaction() as session:
        user = auth.get(session, body.user_id)
        if user is None or user.status != "ACTIVE":
            raise AppError(404, "NOT_FOUND", "Пользователь не найден")
        if body.company_id is not None and not any(
            m.company_id == body.company_id for m, _ in service.memberships_of(session, user.id)
        ):
            raise AppError(404, "NOT_FOUND", "Компания не найдена")
        subject = f"{user.id}|{body.company_id or ''}"
        issued = auth.codes.issue(
            user.person_inn or str(user.id), LOGIN, subject, company_id=body.company_id
        )
    demo = get_settings().demo_mode
    return CodeIssued(
        request_id=issued.request_id,
        expires_in_seconds=issued.expires_in,
        demo_code=issued.code if demo else None,
    )


@router.post(
    "/auth/request-code",
    operation_id="requestLoginCode",
    summary="Выпустить одноразовый код (в демо он показывается на экране вместо SMS)",
    response_model=CodeIssued,
    response_model_by_alias=True,
)
async def request_code(body: CodeRequest) -> CodeIssued:
    return await run_in_threadpool(_issue, body)


def _cookie(response: Response, zone: auth.Zone, sid: str) -> None:
    response.set_cookie(
        auth.sessions.COOKIE[zone],
        sid,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


def _login(body: CodeCheck, old_sid: str | None) -> tuple[str, MeResponse]:
    try:
        verified = auth.codes.verify(body.request_id, body.code, purpose=LOGIN)
    except AppError as exc:
        with db.transaction() as session:
            audit.record(session, "LOGIN_FAILED", details={"code": exc.code})
        raise
    user_part, _, company_part = verified.subject.partition("|")
    with db.transaction() as session:
        user = auth.get(session, UUID(user_part))
        if user is None or user.status != "ACTIVE":
            raise AppError(401, "UNAUTHENTICATED", "Пользователь недоступен")
        rows = service.memberships_of(session, user.id)
        active = UUID(company_part) if company_part else (rows[0][1].id if len(rows) == 1 else None)
        principal = auth.Principal(
            user_id=user.id,
            role=user.role,
            zone=auth.Zone.CLIENT,
            display_name=user.display_name,
            person_inn=user.person_inn,
            memberships=service.to_memberships(rows),
            active_company_id=active,
        )
        sid = auth.sessions.create(principal, replace_sid=old_sid)
        audit.record(session, "LOGIN", actor_id=user.id, actor_role=user.role, company_id=active)
        me = _me(principal, rows)
    return sid, me


def _me(principal: auth.Principal, rows: list[tuple[CompanyMember, Company]]) -> MeResponse:
    return MeResponse(
        user_id=principal.user_id,
        display_name=principal.display_name,
        role=principal.role,
        active_company_id=principal.active_company_id,
        companies=[CompanyChoice(company=_brief(c), role=m.role) for m, c in rows],
    )


@router.post(
    "/auth/verify-code",
    operation_id="verifyLoginCode",
    summary="Проверить код и открыть сессию клиента",
    response_model=MeResponse,
    response_model_by_alias=True,
)
async def verify_code(
    body: CodeCheck,
    response: Response,
    sid_client: Annotated[str | None, Cookie()] = None,
) -> MeResponse:
    sid, me = await run_in_threadpool(_login, body, sid_client)
    _cookie(response, auth.Zone.CLIENT, sid)
    return me


@router.post("/auth/logout", operation_id="logout", summary="Выйти", status_code=204)
async def logout(
    request: Request, response: Response, sid_client: Annotated[str | None, Cookie()] = None
) -> Response:
    if sid_client:
        await run_in_threadpool(auth.sessions.destroy, auth.Zone.CLIENT, sid_client)
    result = Response(status_code=204)
    result.delete_cookie(auth.sessions.COOKIE[auth.Zone.CLIENT], path="/")
    return result


def _me_for(principal: auth.Principal) -> MeResponse:
    with db.transaction() as session:
        return _me(principal, service.memberships_of(session, principal.user_id))


@router.get(
    "/me",
    operation_id="getMe",
    summary="Кто я и мои компании",
    response_model=MeResponse,
    response_model_by_alias=True,
)
async def me(principal: auth.ClientPrincipal) -> MeResponse:
    return await run_in_threadpool(_me_for, principal)


@router.put(
    "/me/active-company",
    operation_id="setActiveCompany",
    summary="Выбрать активную компанию",
    response_model=MeResponse,
    response_model_by_alias=True,
)
async def set_active_company(body: ActiveCompany, principal: auth.ClientPrincipal) -> MeResponse:
    if not principal.can_access(body.company_id):
        raise AppError(404, "NOT_FOUND", "Компания не найдена")
    updated = auth.Principal(**{**principal.__dict__, "active_company_id": body.company_id})
    await run_in_threadpool(auth.sessions.update, updated)
    return await run_in_threadpool(_me_for, updated)


@router.get(
    "/public-config",
    operation_id="getPublicConfig",
    summary="Настройки для интерфейса без входа",
    response_model=PublicConfig,
    response_model_by_alias=True,
)
async def public_config() -> PublicConfig:
    settings = get_settings()
    return PublicConfig(
        demo_mode=settings.demo_mode,
        product_name="Умный кредитный кабинет",
        version="0.1.0",
        nlu_available=settings.nlu_enabled,
        demo_code_required=settings.demo_mode and settings.app_env.value == "cloud",
        docs_links=settings.docs_links if settings.demo_mode else {},
    )
