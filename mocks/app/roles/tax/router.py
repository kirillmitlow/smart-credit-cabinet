"""Бизнес-API mock-tax: ФНС (ПБ, ГИР БО, РМСП, НПД, блокировки) и ЕИС (разделы 5.1–5.6)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.common.admin import make_admin_router
from app.common.auth import require_api_key
from app.common.db import Session
from app.common.problems import InnPath, ProblemException, valid_inn
from app.common.schemas import build_meta, problem_responses
from app.roles.tax import schemas as sc
from app.roles.tax import service
from app.roles.tax.admin import TaxHandler

ERRORS = problem_responses(400, 401, 403, 429, 503)

router = APIRouter(
    prefix="/api/v1",
    tags=["mock-tax"],
    dependencies=[Depends(require_api_key)],
)
admin_router = make_admin_router(TaxHandler())


def _today(request: Request) -> date:
    today: date = request.app.state.clock.today()
    return today


@router.get(
    "/tax-profile/{inn}",
    summary="Налоговый профиль («Прозрачный бизнес»)",
    description=(
        "Режимы налогообложения, долги, доходы, численность, флаги риска. "
        "`404 ENTITY_NOT_FOUND`, если такого налогоплательщика-бизнеса нет."
    ),
    operation_id="getTaxProfile",
    response_model=sc.TaxProfileResponse,
    responses={**ERRORS, **problem_responses(404)},
)
async def get_tax_profile(
    inn: InnPath, request: Request, session: Session
) -> sc.TaxProfileResponse:
    valid_inn(inn)
    card = await service.load_tax_profile(session, inn)
    if card is None:
        raise ProblemException(404, "ENTITY_NOT_FOUND", f"Налогоплательщика {inn} нет в базе")
    meta = build_meta(request, "FNS_TRANSPARENT_BUSINESS", service.first_of_month(_today(request)))
    return sc.TaxProfileResponse(meta=meta, **dict(card))


@router.get(
    "/financials/{inn}",
    summary="Бухгалтерская отчётность (ГИР БО)",
    description=(
        "Десять строк баланса и отчёта о финрезультатах плюс сводка. `year` не указан — последний "
        "доступный год. `404 STATEMENTS_NOT_FOUND`: у ИП (любой верный 12-значный ИНН), у "
        "самозанятого, у компании моложе года и за неподанный год."
    ),
    operation_id="getFinancials",
    response_model=sc.FinancialsResponse,
    responses={**ERRORS, **problem_responses(404, 422)},
)
async def get_financials(
    inn: InnPath,
    request: Request,
    session: Session,
    year: Annotated[int | None, Query(ge=1990, le=2100, description="Отчётный год")] = None,
) -> sc.FinancialsResponse:
    valid_inn(inn)
    card = None if len(inn) == 12 else await service.load_financials(session, inn, year)
    if card is None:
        what = f"за {year} год" if year is not None else "вообще"
        raise ProblemException(
            404, "STATEMENTS_NOT_FOUND", f"Отчётности по ИНН {inn} {what} в ГИР БО нет"
        )
    meta = build_meta(request, "FNS_GIR_BO", card.submitted_at)
    return sc.FinancialsResponse(meta=meta, **dict(card))


@router.get(
    "/sme-status/{inn}",
    summary="Единый реестр МСП",
    description="Нет в реестре — это `200` с `inRegistry: false`, а не `404`.",
    operation_id="getSmeStatus",
    response_model=sc.SmeStatusResponse,
    responses=ERRORS,
)
async def get_sme_status(inn: InnPath, request: Request, session: Session) -> sc.SmeStatusResponse:
    valid_inn(inn)
    meta = build_meta(request, "FNS_RMSP", service.rmsp_actual_at(_today(request)))
    row = await service.sme_status(session, inn)
    if row is None:
        return sc.SmeStatusResponse(
            meta=meta,
            inn=inn,
            in_registry=False,
            category=None,
            included_at=None,
            is_newly_created=None,
            is_social_enterprise=None,
        )
    return sc.SmeStatusResponse(
        meta=meta,
        inn=inn,
        in_registry=True,
        category=row.category,
        included_at=row.included_at,
        is_newly_created=row.is_newly_created,
        is_social_enterprise=row.is_social_enterprise,
    )


@router.post(
    "/self-employed/status",
    summary="Статус плательщика НПД (самозанятый)",
    description=(
        "Повторяет контракт открытого API ФНС один в один, поэтому `meta` в теле нет: признак "
        "симуляции — заголовок `X-Mock-Simulated: true`."
    ),
    operation_id="getSelfEmployedStatus",
    response_model=sc.NpdResponse,
    responses={**ERRORS, **problem_responses(422)},
)
async def post_self_employed_status(
    body: sc.NpdRequest, response: Response, session: Session
) -> sc.NpdResponse:
    inn = valid_inn(body.inn)
    response.headers["X-Mock-Simulated"] = "true"
    status = await service.is_self_employed(session, inn, body.request_date)
    verdict = "является" if status else "не является"
    return sc.NpdResponse(
        status=status, message=f"{inn} {verdict} плательщиком налога на профессиональный доход"
    )


@router.get(
    "/account-blocks/{inn}",
    summary="Решения о приостановлении операций по счетам (сервис «БИ»)",
    description=(
        "Без `bik` — действующие решения по всем банкам; с `bik` — только по этому банку. "
        "Нет блокировок — `200` с пустым списком. Снятые решения не показываются."
    ),
    operation_id="getAccountBlocks",
    response_model=sc.AccountBlocksResponse,
    responses={**ERRORS, **problem_responses(422)},
)
async def get_account_blocks(
    inn: InnPath,
    request: Request,
    session: Session,
    bik: Annotated[
        str | None, Query(pattern=r"^\d{9}$", description="БИК банка, например 040000999")
    ] = None,
) -> sc.AccountBlocksResponse:
    valid_inn(inn)
    return sc.AccountBlocksResponse(
        meta=build_meta(request, "FNS_BLOCKS", _today(request)),
        inn=inn,
        checked_at=request.app.state.clock.now().replace(microsecond=0),
        decisions=await service.active_blocks(session, inn, bik),
    )


@router.get(
    "/contracts",
    summary="Госконтракты поставщика (ЕИС)",
    description=(
        "Контрактов нет — `200` с пустым списком. От новых к старым. "
        "`422`: нет `supplierInn` или неизвестный `status`."
    ),
    operation_id="getContracts",
    response_model=sc.ContractsResponse,
    responses={**ERRORS, **problem_responses(422)},
)
async def get_contracts(
    request: Request,
    session: Session,
    supplier_inn: Annotated[
        str, Query(alias="supplierInn", description="ИНН поставщика, 10 или 12 цифр")
    ],
    status: Annotated[sc.ContractStatus | None, Query(description="Фильтр по статусу")] = None,
) -> sc.ContractsResponse:
    valid_inn(supplier_inn)
    return sc.ContractsResponse(
        meta=build_meta(request, "EIS", service.yesterday(_today(request))),
        supplier_inn=supplier_inn,
        contracts=await service.contracts_of(session, supplier_inn, status),
    )
