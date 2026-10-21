"""Бизнес-API mock-registry: ЕГРЮЛ/ЕГРИП и ЕФРСБ (разделы 4.1–4.3)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request

from app.common.admin import make_admin_router
from app.common.auth import require_api_key
from app.common.db import Session
from app.common.problems import InnPath, ProblemException, valid_inn
from app.common.schemas import build_meta, problem_responses
from app.roles.registry import schemas as sc
from app.roles.registry import service
from app.roles.registry.admin import RegistryHandler

ERRORS = problem_responses(400, 401, 403, 429, 503)

router = APIRouter(
    prefix="/api/v1",
    tags=["mock-registry"],
    dependencies=[Depends(require_api_key)],
)
admin_router = make_admin_router(RegistryHandler())


def _today(request: Request) -> date:
    return request.app.state.clock.today()


@router.get(
    "/companies/{inn}",
    summary="Карточка организации (ЕГРЮЛ) или ИП (ЕГРИП)",
    description=(
        "Тип записи определяется по длине ИНН: 10 цифр — ЕГРЮЛ, 12 — ЕГРИП. "
        "У АО список учредителей пуст. Нет в реестре (например, самозанятый) — `404 ENTITY_NOT_FOUND`."
    ),
    operation_id="getCompany",
    response_model=sc.CompanyResponse,
    responses={**ERRORS, **problem_responses(404)},
)
async def get_company(
    inn: InnPath, request: Request, session: Session
) -> sc.LegalEntityResponse | sc.IndividualEntrepreneurResponse:
    valid_inn(inn)
    card = await service.load_card(session, inn)
    if card is None:
        raise ProblemException(404, "ENTITY_NOT_FOUND", f"ИНН {inn} нет в ЕГРЮЛ/ЕГРИП")
    meta = build_meta(
        request,
        "EGRUL" if isinstance(card, sc.LegalEntityCard) else "EGRIP",
        service.data_actual_at(_today(request)),
    )
    if isinstance(card, sc.LegalEntityCard):
        return sc.LegalEntityResponse(meta=meta, **card.model_dump())
    return sc.IndividualEntrepreneurResponse(meta=meta, **card.model_dump())


@router.get(
    "/persons/{inn}/roles",
    summary="Где человек ИП, руководитель или учредитель",
    description=(
        "Принимает только 12-значный ИНН, иначе `400 INN_INVALID`. "
        "Ничего не нашли — `200` с `roles: []`, не `404`."
    ),
    operation_id="getPersonRoles",
    response_model=sc.PersonRolesResponse,
    responses=ERRORS,
)
async def get_person_roles(
    inn: InnPath, request: Request, session: Session
) -> sc.PersonRolesResponse:
    valid_inn(inn)
    if len(inn) != 12:
        raise ProblemException(400, "INN_INVALID", "Роли выдаются по ИНН человека: нужны 12 цифр")
    return sc.PersonRolesResponse(
        meta=build_meta(request, "EGRUL", service.data_actual_at(_today(request))),
        person_inn=inn,
        roles=await service.person_roles(session, inn),
    )


@router.get(
    "/bankruptcies/{inn}",
    summary="Дела о банкротстве (ЕФРСБ) компании или человека",
    description=(
        "ИНН организации (10 цифр) или человека/ИП (12). Нет дел — `200` с пустым списком. "
        "Дела идут от нового к старому, завершённые не пропадают."
    ),
    operation_id="getBankruptcies",
    response_model=sc.BankruptciesResponse,
    responses=ERRORS,
)
async def get_bankruptcies(
    inn: InnPath, request: Request, session: Session
) -> sc.BankruptciesResponse:
    valid_inn(inn)
    return sc.BankruptciesResponse(
        meta=build_meta(request, "FEDRESURS", service.data_actual_at(_today(request))),
        inn=inn,
        bankruptcies=await service.bankruptcies_of(session, inn),
    )
