"""Бизнес-API mock-bank-core (раздел 7): клиенты, обороты, счета, кредиты, выдача, комплаенс.

Роль подключает себя сама: `router` — бизнес-API под /api/v1, `admin_router` — админ-API данных.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from app.common.auth import require_api_key
from app.common.db import Session
from app.common.idempotency import Idempotency, IdempotencyDep
from app.common.inn import IdentifierError, validate_inn
from app.common.problems import ProblemException, valid_inn
from app.common.schemas import build_meta, problem_responses
from app.roles.bank_core import models as m
from app.roles.bank_core import service
from app.roles.bank_core.admin import admin_router
from app.roles.bank_core.schemas import (
    AccountDetailOut,
    CustomerOut,
    DisbursementIn,
    DisbursementOut,
    LoanDetailOut,
    LoansOut,
    OpenAccountIn,
    OpenAccountOut,
    ScreeningIn,
    ScreeningOut,
    TurnoverOut,
)
from app.roles.bank_core.service import account_out, loan_out

__all__ = ["admin_router", "router"]

router = APIRouter(prefix="/api/v1", tags=["bank-core"], dependencies=[Depends(require_api_key)])

Inn = Annotated[str, Depends(valid_inn)]
BUSINESS_ERRORS = problem_responses(400, 401, 403, 422)


def _bik(request: Request) -> str:
    bik: str = request.app.state.settings.bank_bik
    return bik


def _created(model: DisbursementOut | OpenAccountOut) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json", by_alias=True), status_code=201)


@router.get(
    "/customers/{inn}",
    summary="Клиент ли нашего банка",
    operation_id="getCustomer",
    response_model=CustomerOut,
    responses={**BUSINESS_ERRORS, **problem_responses(404)},
)
async def get_customer(request: Request, inn: Inn, session: Session) -> CustomerOut:
    customer = await service.require_customer(session, inn)
    accounts = await service.customer_accounts(session, customer.id)
    return CustomerOut(
        meta=build_meta(request, "BANK_CORE", request.app.state.clock.today()),
        customer_id=service.customer_ref(customer.id),
        inn=customer.inn,
        type=customer.type,
        name=customer.name,
        customer_since=customer.customer_since,
        accounts=[account_out(a) for a in accounts],
    )


@router.get(
    "/customers/{inn}/turnover",
    summary="Месячные обороты по расчётному счёту",
    operation_id="getTurnover",
    response_model=TurnoverOut,
    responses={**BUSINESS_ERRORS, **problem_responses(404)},
)
async def get_turnover(
    request: Request,
    inn: Inn,
    session: Session,
    months: Annotated[int, Query(ge=1, le=24, description="Сколько полных месяцев вернуть")] = 12,
) -> TurnoverOut:
    customer = await service.require_customer(session, inn)
    today = request.app.state.clock.today()
    accounts = await service.customer_accounts(session, customer.id, include_closed=False)
    return TurnoverOut(
        meta=build_meta(request, "BANK_CORE", today),
        inn=customer.inn,
        account_numbers=[a.number for a in accounts],
        months=await service.turnover_months(session, customer, months, today),
    )


@router.get(
    "/customers/{inn}/loans",
    summary="Кредиты нашего банка у клиента",
    operation_id="getCustomerLoans",
    response_model=LoansOut,
    responses={**BUSINESS_ERRORS, **problem_responses(404)},
)
async def get_customer_loans(request: Request, inn: Inn, session: Session) -> LoansOut:
    customer = await service.require_customer(session, inn)
    loans = await service.customer_loans(session, customer.id)
    return LoansOut(
        meta=build_meta(request, "BANK_CORE", request.app.state.clock.today()),
        inn=customer.inn,
        loans=[loan_out(loan) for loan in loans],
    )


@router.post(
    "/customers/{inn}/accounts",
    summary="Открыть расчётный счёт (мгновенно, идемпотентно)",
    operation_id="openAccount",
    status_code=201,
    response_model=OpenAccountOut,
    responses={**BUSINESS_ERRORS, **problem_responses(404, 409)},
)
async def open_account(
    request: Request, inn: Inn, body: OpenAccountIn, idem: IdempotencyDep, session: Session
) -> Response:
    # Путь с {inn} один для всех клиентов, поэтому ИНН входит в область ключа:
    # тот же ключ для другого клиента не должен вернуть чужой счёт
    scoped = Idempotency(
        request.app.state.database,
        request.app.state.clock,
        f"{idem.endpoint}#{inn}",
        idem.key,
        idem.request_hash,
    )

    async def handle() -> Response:
        today = request.app.state.clock.today()
        customer, account = await service.open_account(session, _bik(request), today, inn, body)
        out = OpenAccountOut(
            **account_out(account).model_dump(),
            meta=build_meta(request, "BANK_CORE", today),
            customer_id=service.customer_ref(customer.id),
        )
        await session.commit()
        return _created(out)

    return await scoped.run(handle)


@router.post(
    "/disbursements",
    summary="Выдать кредит (деньги выдаются ровно один раз)",
    operation_id="createDisbursement",
    status_code=201,
    response_model=DisbursementOut,
    responses={**BUSINESS_ERRORS, **problem_responses(404, 409)},
)
async def create_disbursement(
    request: Request, body: DisbursementIn, idem: IdempotencyDep, session: Session
) -> Response:
    try:
        validate_inn(body.customer_inn)
    except IdentifierError as exc:
        raise ProblemException(400, "INN_INVALID", str(exc)) from exc

    async def handle() -> Response:
        clock = request.app.state.clock
        result = await service.disburse(session, _bik(request), clock.now(), body)
        loan = result.loan
        out = DisbursementOut(
            meta=build_meta(request, "BANK_CORE", clock.today()),
            disbursement_id=result.disbursement_id,
            loan_id=service.loan_ref(loan.id),
            loan_account=loan.loan_account,
            settlement_account=loan.settlement_account,
            amount_rub=loan.amount_rub,
            value_date=result.value_date,
            postings=result.postings,
            settlement_balance_rub=result.settlement_balance_rub,
        )
        await session.commit()  # деньги записаны до того, как ответ уйдёт (и до LOST_RESPONSE)
        return _created(out)

    return await idem.run(handle)


@router.get(
    "/loans/{loan_id}",
    summary="Кредит нашего банка",
    operation_id="getLoan",
    response_model=LoanDetailOut,
    responses={**BUSINESS_ERRORS, **problem_responses(404)},
)
async def get_loan(
    request: Request,
    loan_id: Annotated[str, Path(description="Например, loan_000041")],
    session: Session,
) -> LoanDetailOut:
    number = service.parse_loan_ref(loan_id)
    loan = await session.get(m.Loan, number) if number is not None else None
    if loan is None:
        raise ProblemException(404, "LOAN_NOT_FOUND", f"Кредит {loan_id} не найден")
    return LoanDetailOut(
        **loan_out(loan).model_dump(),
        meta=build_meta(request, "BANK_CORE", request.app.state.clock.today()),
    )


@router.get(
    "/accounts/{number}",
    summary="Счёт, остаток и последние проводки",
    operation_id="getAccount",
    response_model=AccountDetailOut,
    responses={**BUSINESS_ERRORS, **problem_responses(404)},
)
async def get_account(
    request: Request,
    number: Annotated[str, Path(pattern=r"^\d{20}$", description="Номер счёта, 20 цифр")],
    session: Session,
) -> AccountDetailOut:
    account = await session.get(m.Account, number)
    if account is None:
        raise ProblemException(404, "ACCOUNT_NOT_FOUND", f"Счёт {number} не найден")
    return AccountDetailOut(
        **account_out(account).model_dump(),
        meta=build_meta(request, "BANK_CORE", request.app.state.clock.today()),
        recent_postings=await service.recent_postings(session, number),
    )


@router.post(
    "/compliance/screening",
    summary="Проверка участников заявки по спискам",
    operation_id="screenSubjects",
    response_model=ScreeningOut,
    responses={**BUSINESS_ERRORS},
)
async def screening(request: Request, body: ScreeningIn, session: Session) -> ScreeningOut:
    for subject in body.subjects:
        try:
            validate_inn(subject.inn)
        except IdentifierError as exc:
            raise ProblemException(400, "INN_INVALID", f"{subject.inn}: {exc}") from exc
    overall, results = await service.screen(session, body.subjects)
    return ScreeningOut(
        meta=build_meta(request, "COMPLIANCE", request.app.state.clock.today()),
        screening_id=service.new_screening_id(),
        overall=overall,
        results=results,
    )
