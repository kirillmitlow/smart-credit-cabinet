"""«Мои кредиты»: открытие кредита с графиком, чтение для клиента (T-344, 20-05, 30-16).

График считает ядро (`decisioning.build_schedule`/`bullet_schedule`), те же функции, что у оферты:
«показали одно, проверили другое» невозможно. Первый платёж: день выдачи (не позже 28-го) плюс
месяц, с переносом на рабочий день; сумма при переносе не меняется (30-16).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth, companies
from app.modules.decisioning import build_schedule, bullet_schedule
from app.modules.decisioning.loan_math import payment_dates
from app.modules.loans.models import Loan, PaymentScheduleRow
from app.shared.errors import AppError, not_found

_PERCENT = Decimal(100)


@dataclass(frozen=True, slots=True)
class NewLoan:
    """Параметры кредита из подтверждённой выдачи."""

    company_id: UUID
    application_id: UUID
    disbursement_id: UUID
    bank_core_loan_id: str
    contract_number: str
    contract_uid: str
    product_code: str
    kind: str
    repayment_type: str
    amount_rub: int
    limit_rub: int | None
    rate_percent: Decimal
    term_months: int
    loan_account: str
    settlement_account: str
    opened_on: date


def schedule_rows(
    repayment_type: str, amount: int, rate_percent: Decimal, term: int, opened_on: date
) -> list[PaymentScheduleRow]:
    """Строки графика; для линии и овердрафта (REVOLVING) их нет."""
    if repayment_type == "REVOLVING" or amount <= 0:
        return []
    rate = rate_percent / _PERCENT
    rows = (
        bullet_schedule(amount, rate, term)
        if repayment_type == "BULLET"
        else build_schedule(amount, rate, term)
    )
    dates = payment_dates(opened_on, term)
    return [
        PaymentScheduleRow(
            seq=row.number,
            due_date=due,
            principal_rub=row.principal,
            interest_rub=row.interest,
            total_rub=row.payment,
            status="SCHEDULED",
        )
        for row, due in zip(rows, dates, strict=True)
    ]


def open_loan(session: Session, new: NewLoan) -> Loan:
    """Кредит и график одной транзакцией вызывающего. Повтор по той же заявке возвращает прежний."""
    existing = session.scalars(
        select(Loan).where(Loan.application_id == new.application_id)
    ).first()
    if existing is not None:
        return existing
    rows = schedule_rows(
        new.repayment_type, new.amount_rub, new.rate_percent, new.term_months, new.opened_on
    )
    loan = Loan(
        company_id=new.company_id,
        application_id=new.application_id,
        disbursement_id=new.disbursement_id,
        bank_core_loan_id=new.bank_core_loan_id,
        contract_number=new.contract_number,
        contract_uid=new.contract_uid,
        product_code=new.product_code,
        kind=new.kind,
        repayment_type=new.repayment_type,
        principal_rub=new.amount_rub,
        limit_rub=new.limit_rub,
        outstanding_rub=new.amount_rub,
        rate_percent=new.rate_percent,
        term_months=new.term_months,
        payment_rub=rows[0].total_rub if rows else None,
        loan_account=new.loan_account,
        settlement_account=new.settlement_account,
        opened_on=new.opened_on,
        status="ACTIVE",
    )
    session.add(loan)
    session.flush()
    for row in rows:
        row.loan_id = loan.id
    session.add_all(rows)
    session.flush()
    return loan


# --- чтение ---------------------------------------------------------------------------------------


def _visible_companies(session: Session, principal: auth.Principal) -> list[UUID]:
    """Отзыв членства и смена роли действуют сразу, даже при старой сессии Redis (D-096)."""
    user = auth.get(session, principal.user_id)
    if user is None or user.status != "ACTIVE" or user.role != "CLIENT":
        raise AppError(401, "UNAUTHENTICATED", "Нужно войти")
    return [
        member.company_id
        for member, _ in companies.memberships_of(session, principal.user_id)
        if member.role in {"DIRECTOR", "ACCOUNTANT"}
    ]


def list_for(
    session: Session, principal: auth.Principal, limit: int, cursor: str | None
) -> tuple[list[Loan], str | None]:
    query = select(Loan).where(Loan.company_id.in_(_visible_companies(session, principal)))
    if cursor:
        query = query.where(Loan.id < UUID(cursor))
    rows = list(session.scalars(query.order_by(Loan.id.desc()).limit(limit + 1)))
    next_cursor = str(rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], next_cursor


def get_for(session: Session, principal: auth.Principal, loan_id: UUID) -> Loan:
    """Чужой и несуществующий кредит неразличимы: 404 (R11)."""
    loan = session.get(Loan, loan_id)
    visible = _visible_companies(session, principal)
    if loan is None or loan.company_id not in visible:
        raise not_found("Кредит")
    return loan


def schedule_of(session: Session, loan: Loan) -> list[PaymentScheduleRow]:
    return list(
        session.scalars(
            select(PaymentScheduleRow)
            .where(PaymentScheduleRow.loan_id == loan.id)
            .order_by(PaymentScheduleRow.seq)
        )
    )


def next_payment(rows: list[PaymentScheduleRow], today: date) -> PaymentScheduleRow | None:
    """Ближайший платёж по календарю: первый не раньше сегодняшнего дня."""
    return next((r for r in rows if r.due_date >= today), None)
