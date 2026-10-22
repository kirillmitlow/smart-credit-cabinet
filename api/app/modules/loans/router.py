"""Ручки «Мои кредиты» для клиента (T-344, 50-07). Роутер тонкий: разобрать → сервис → ответ (R6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.modules.loans import service
from app.modules.loans.models import Loan, PaymentScheduleRow
from app.shared import clock, db

router = APIRouter(prefix="/loans", tags=["кредиты"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LoanPaymentOut(Camel):
    seq: int
    due_date: date
    principal_rub: int
    interest_rub: int
    total_rub: int
    status: str


class LoanOut(Camel):
    id: UUID
    application_id: UUID
    contract_number: str
    product_code: str
    kind: str
    repayment_type: str
    amount_rub: int
    limit_rub: int | None
    outstanding_rub: int
    rate_percent: Decimal
    term_months: int
    payment_rub: int | None
    loan_account: str
    settlement_account: str
    opened_on: date
    status: str
    next_payment: LoanPaymentOut | None


class LoanDetail(LoanOut):
    schedule: list[LoanPaymentOut]


class LoanPage(Camel):
    items: list[LoanOut]
    next_cursor: str | None


def _payment(row: PaymentScheduleRow) -> LoanPaymentOut:
    return LoanPaymentOut(
        seq=row.seq,
        due_date=row.due_date,
        principal_rub=row.principal_rub,
        interest_rub=row.interest_rub,
        total_rub=row.total_rub,
        status=row.status,
    )


def _fields(loan: Loan, schedule: list[PaymentScheduleRow]) -> dict[str, object]:
    upcoming = service.next_payment(schedule, clock.today())
    return {
        "id": loan.id,
        "application_id": loan.application_id,
        "contract_number": loan.contract_number,
        "product_code": loan.product_code,
        "kind": loan.kind,
        "repayment_type": loan.repayment_type,
        "amount_rub": loan.principal_rub,
        "limit_rub": loan.limit_rub,
        "outstanding_rub": loan.outstanding_rub,
        "rate_percent": loan.rate_percent,
        "term_months": loan.term_months,
        "payment_rub": loan.payment_rub,
        "loan_account": loan.loan_account,
        "settlement_account": loan.settlement_account,
        "opened_on": loan.opened_on,
        "status": loan.status,
        "next_payment": _payment(upcoming) if upcoming else None,
    }


def _list(principal: auth.Principal, limit: int, cursor: str | None) -> LoanPage:
    with db.transaction() as session:
        loans, next_cursor = service.list_for(session, principal, limit, cursor)
        items = [LoanOut(**_fields(loan, service.schedule_of(session, loan))) for loan in loans]
        return LoanPage(items=items, next_cursor=next_cursor)


@router.get(
    "",
    operation_id="listLoans",
    summary="Мои кредиты, новые сверху",
    response_model=LoanPage,
    response_model_by_alias=True,
)
async def list_loans(
    principal: auth.ClientPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[UUID | None, Query()] = None,
) -> LoanPage:
    return await run_in_threadpool(_list, principal, limit, str(cursor) if cursor else None)


def _get(principal: auth.Principal, loan_id: UUID) -> LoanDetail:
    with db.transaction() as session:
        loan = service.get_for(session, principal, loan_id)
        schedule = service.schedule_of(session, loan)
        return LoanDetail(**_fields(loan, schedule), schedule=[_payment(r) for r in schedule])


@router.get(
    "/{loan_id}",
    operation_id="getLoan",
    summary="Кредит с графиком и ближайшим платежом",
    response_model=LoanDetail,
    response_model_by_alias=True,
)
async def get_loan(loan_id: UUID, principal: auth.ClientPrincipal) -> LoanDetail:
    return await run_in_threadpool(_get, principal, loan_id)


def _schedule(principal: auth.Principal, loan_id: UUID) -> list[LoanPaymentOut]:
    with db.transaction() as session:
        loan = service.get_for(session, principal, loan_id)
        return [_payment(r) for r in service.schedule_of(session, loan)]


@router.get(
    "/{loan_id}/schedule",
    operation_id="getLoanSchedule",
    summary="График платежей",
    response_model=list[LoanPaymentOut],
    response_model_by_alias=True,
)
async def get_schedule(loan_id: UUID, principal: auth.ClientPrincipal) -> list[LoanPaymentOut]:
    return await run_in_threadpool(_schedule, principal, loan_id)
