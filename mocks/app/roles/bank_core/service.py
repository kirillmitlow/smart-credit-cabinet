"""Логика mock-bank-core: чтение, выдача кредита, открытие счёта, комплаенс (раздел 7).

Выдача и открытие счёта делают все записи в одной транзакции и коммитят до возврата; от двойной
выплаты кроме ключа идемпотентности защищают уникальные ключи в БД (заявка, УИд, номер договора).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.accounts import (
    LOAN_IP,
    LOAN_LEGAL,
    SETTLEMENT_IP,
    SETTLEMENT_LEGAL,
    make_account,
)
from app.common.clock import MSK, last_full_month, month_start
from app.common.db import Origin
from app.common.problems import ProblemException
from app.common.reldate import add_months
from app.roles.bank_core import models as m
from app.roles.bank_core.models import loan_id_seq, settlement_serial_seq
from app.roles.bank_core.schemas import (
    AccountOut,
    AmlListOut,
    DisbursementIn,
    DisbursementPosting,
    LoanOut,
    OpenAccountIn,
    PostingOut,
    ScreeningResult,
    ScreeningSubject,
    StopListOut,
    TurnoverMonthOut,
    ZskOut,
)

SETTLEMENT_BALANCE = {"LEGAL_ENTITY": SETTLEMENT_LEGAL, "INDIVIDUAL_ENTREPRENEUR": SETTLEMENT_IP}
LOAN_BALANCE = {"LEGAL_ENTITY": LOAN_LEGAL, "INDIVIDUAL_ENTREPRENEUR": LOAN_IP}
MAX_SERIAL = 9_999_999
RECENT_POSTINGS = 20
_LOAN_ID = re.compile(r"^loan_(\d{1,9})$")


def customer_ref(customer_id: int) -> str:
    return f"cus_{customer_id:06d}"


def loan_ref(loan_id: int) -> str:
    return f"loan_{loan_id:06d}"


def parse_loan_ref(value: str) -> int | None:
    match = _LOAN_ID.match(value)
    return int(match.group(1)) if match else None


def check_customer_type(inn: str, customer_type: str) -> None:
    """ИП — 12 цифр ИНН, организация — 10."""
    expected = 12 if customer_type == "INDIVIDUAL_ENTREPRENEUR" else 10
    if len(inn) != expected:
        raise ProblemException(
            422,
            "VALIDATION_ERROR",
            f"У {'ИП' if expected == 12 else 'организации'} ИНН должен быть из {expected} цифр",
        )


def account_out(account: m.Account) -> AccountOut:
    return AccountOut(
        number=account.number,
        type=account.type,
        status=account.status,
        opened_at=account.opened_at,
        balance_rub=account.balance_rub,
    )


def loan_out(loan: m.Loan) -> LoanOut:
    return LoanOut(
        loan_id=loan_ref(loan.id),
        application_ref=loan.application_ref,
        contract_number=loan.contract_number,
        contract_uid=loan.contract_uid,
        product_code=loan.product_code,
        kind=loan.kind,
        amount_rub=loan.amount_rub,
        limit_rub=loan.limit_rub,
        outstanding_rub=loan.amount_rub,  # погашения мок не моделирует (7.5)
        term_months=loan.term_months,
        rate_percent=loan.rate_percent,
        repayment_type=loan.repayment_type,
        loan_account=loan.loan_account,
        settlement_account=loan.settlement_account,
        status=loan.status,
        disbursed_at=loan.disbursed_at,
    )


def customer_not_found(inn: str) -> ProblemException:
    return ProblemException(404, "CUSTOMER_NOT_FOUND", f"Клиент с ИНН {inn} не найден в банке")


async def find_customer(
    session: AsyncSession, inn: str, *, lock: bool = False
) -> m.Customer | None:
    query = sa.select(m.Customer).where(m.Customer.inn == inn)
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


async def require_customer(session: AsyncSession, inn: str) -> m.Customer:
    customer = await find_customer(session, inn)
    if customer is None:
        raise customer_not_found(inn)
    return customer


async def customer_accounts(
    session: AsyncSession, customer_id: int, *, include_closed: bool = True
) -> list[m.Account]:
    query = sa.select(m.Account).where(
        m.Account.customer_id == customer_id, m.Account.type == "SETTLEMENT"
    )
    if not include_closed:
        query = query.where(m.Account.status != "CLOSED")
    return list(await session.scalars(query.order_by(m.Account.opened_at, m.Account.number)))


async def customer_loans(session: AsyncSession, customer_id: int) -> list[m.Loan]:
    query = sa.select(m.Loan).where(m.Loan.customer_id == customer_id)
    return list(await session.scalars(query.order_by(m.Loan.disbursed_at, m.Loan.id)))


async def next_settlement_account(session: AsyncSession, bik: str, customer_type: str) -> str:
    """Свободный номер расчётного счёта с верным ключом."""
    balance = SETTLEMENT_BALANCE[customer_type]
    while True:
        serial = await session.scalar(sa.select(settlement_serial_seq.next_value()))
        if serial is None or serial > MAX_SERIAL:
            raise ProblemException(500, "INTERNAL_ERROR", "Номера расчётных счетов исчерпаны")
        number = make_account(bik, balance, serial)
        if await session.get(m.Account, number) is None:
            return number


async def next_loan_id(session: AsyncSession) -> int:
    value = await session.scalar(sa.select(loan_id_seq.next_value()))
    if value is None or value > MAX_SERIAL:
        raise ProblemException(500, "INTERNAL_ERROR", "Номера кредитов исчерпаны")
    return int(value)


def loan_account_number(bik: str, customer_type: str, loan_id: int) -> str:
    return make_account(bik, LOAN_BALANCE[customer_type], loan_id)


# ---- 7.2 обороты ----


def turnover_window(today: date, months: int, customer_since: date) -> tuple[date, date]:
    """Только полные месяцы до «сегодня» и не раньше месяца начала обслуживания."""
    last = last_full_month(today)
    first = max(add_months(last, -(months - 1)), month_start(customer_since))
    return first, last


async def turnover_months(
    session: AsyncSession, customer: m.Customer, months: int, today: date
) -> list[TurnoverMonthOut]:
    first, last = turnover_window(today, months, customer.customer_since)
    rows = await session.scalars(
        sa.select(m.MonthlyTurnover)
        .where(
            m.MonthlyTurnover.customer_id == customer.id,
            m.MonthlyTurnover.month >= first,
            m.MonthlyTurnover.month <= last,
        )
        .order_by(m.MonthlyTurnover.month)
    )
    return [
        TurnoverMonthOut(
            month=r.month.strftime("%Y-%m"),
            incoming_rub=r.incoming_rub,
            incoming_net_rub=r.incoming_net_rub,
            outgoing_rub=r.outgoing_rub,
            counterparties_in=r.counterparties_in,
            counterparties_out=r.counterparties_out,
        )
        for r in rows
    ]


# ---- 7.5 счета ----


async def recent_postings(session: AsyncSession, number: str) -> list[PostingOut]:
    rows = await session.scalars(
        sa.select(m.Posting)
        .where(sa.or_(m.Posting.debit_account == number, m.Posting.credit_account == number))
        .order_by(m.Posting.id.desc())
        .limit(RECENT_POSTINGS)
    )
    return [
        PostingOut(
            debit=p.debit_account,
            credit=p.credit_account,
            amount_rub=p.amount_rub,
            purpose=p.purpose,
            value_date=p.value_date,
        )
        for p in rows
    ]


# ---- 7.3 открытие счёта ----


async def open_account(
    session: AsyncSession, bik: str, today: date, inn: str, body: OpenAccountIn
) -> tuple[m.Customer, m.Account]:
    """Расчётный счёт клиенту; клиента создаёт, если его нет. Коммит — на стороне вызывающего.

    Строка клиента блокируется, поэтому два запроса с разными ключами не откроют два счёта.
    """
    customer = await find_customer(session, inn, lock=True)
    if customer is None:
        if body.customer is None:
            raise ProblemException(
                422,
                "VALIDATION_ERROR",
                "Клиента с таким ИНН нет: передайте customer (тип и наименование)",
                errors=[{"loc": ["body", "customer"], "msg": "Field required"}],
            )
        check_customer_type(inn, body.customer.type)
        await session.execute(
            insert(m.Customer)
            .values(
                inn=inn,
                type=body.customer.type,
                name=body.customer.name,
                customer_since=today,
                origin=Origin.RUNTIME.value,
                scenario_code=None,
            )
            .on_conflict_do_nothing(index_elements=[m.Customer.inn])
        )
        customer = await find_customer(session, inn, lock=True)
        assert customer is not None  # noqa: S101 — строка только что вставлена или уже была
    existing = await customer_accounts(session, customer.id, include_closed=False)
    if existing:
        raise ProblemException(
            409,
            "ACCOUNT_ALREADY_EXISTS",
            f"У клиента уже есть расчётный счёт {existing[0].number}",
        )
    account = m.Account(
        number=await next_settlement_account(session, bik, customer.type),
        customer_id=customer.id,
        type="SETTLEMENT",
        currency="RUB",
        status="OPEN",
        opened_at=today,
        balance_rub=0,
        origin=Origin.RUNTIME.value,
    )
    session.add(account)
    await session.flush()
    return customer, account


# ---- 7.4 выдача ----


@dataclass(frozen=True)
class DisbursementResult:
    disbursement_id: str
    loan: m.Loan
    postings: list[DisbursementPosting]
    value_date: date
    settlement_balance_rub: int


def _already_disbursed(body: DisbursementIn) -> ProblemException:
    return ProblemException(
        409,
        "ALREADY_DISBURSED",
        f"По заявке {body.application_ref} (договор {body.contract.number}) выдача уже была",
    )


async def disburse(
    session: AsyncSession, bik: str, now: datetime, body: DisbursementIn
) -> DisbursementResult:
    """Кредит, ссудный счёт, проводка и зачисление: либо всё, либо ничего.

    Вызывающий коммитит сессию до возврата ответа. Повторная выдача по той же заявке, УИд или
    номеру договора невозможна ни при каком ключе идемпотентности (уникальные ключи в БД).
    """
    customer = await require_customer(session, body.customer_inn)
    taken = await session.scalar(
        sa.select(m.Loan.id).where(
            sa.or_(
                m.Loan.application_ref == body.application_ref,
                m.Loan.contract_uid == body.contract.uid,
                m.Loan.contract_number == body.contract.number,
            )
        )
    )
    if taken is not None:
        raise _already_disbursed(body)

    # Блокировка строки счёта: остаток меняется последовательно даже при параллельных выдачах
    settlement = await session.get(m.Account, body.settlement_account, with_for_update=True)
    if (
        settlement is None
        or settlement.customer_id != customer.id
        or settlement.type != "SETTLEMENT"
    ):
        raise ProblemException(
            409,
            "ACCOUNT_NOT_OWNED",
            f"Счёта {body.settlement_account} нет среди расчётных счетов клиента",
        )
    if settlement.status != "OPEN":
        raise ProblemException(
            409,
            "ACCOUNT_BLOCKED",
            f"Счёт {settlement.number} в статусе {settlement.status}: зачисление невозможно",
        )

    today = now.astimezone(MSK).date()
    signed_on = body.contract.signed_at.astimezone(MSK).date()
    loan_id = await next_loan_id(session)
    loan_account = m.Account(
        number=loan_account_number(bik, customer.type, loan_id),
        customer_id=customer.id,
        type="LOAN",
        currency="RUB",
        status="OPEN",
        opened_at=today,
        balance_rub=body.amount_rub,
        origin=Origin.RUNTIME.value,
    )
    loan = m.Loan(
        id=loan_id,
        customer_id=customer.id,
        application_ref=body.application_ref,
        contract_number=body.contract.number,
        contract_uid=body.contract.uid,
        product_code=body.product.code,
        kind=body.kind,
        amount_rub=body.amount_rub,
        limit_rub=body.limit_rub,
        term_months=body.term_months,
        rate_percent=body.rate_percent,
        repayment_type=body.repayment_type,
        loan_account=loan_account.number,
        settlement_account=settlement.number,
        status="ACTIVE",
        disbursed_at=today,
        origin=Origin.RUNTIME.value,
    )
    try:
        session.add(loan_account)
        await session.flush()
        session.add(loan)
        await session.flush()
    except IntegrityError as exc:  # параллельная выдача с другим ключом выиграла гонку
        await session.rollback()
        raise _already_disbursed(body) from exc

    postings: list[DisbursementPosting] = []
    if body.amount_rub > 0:
        purpose = (
            f"Выдача кредита по договору № {body.contract.number} "
            f"от {signed_on:%d.%m.%Y}. НДС не облагается"
        )
        session.add(
            m.Posting(
                debit_account=loan_account.number,
                credit_account=settlement.number,
                amount_rub=body.amount_rub,
                purpose=purpose,
                value_date=today,
                loan_id=loan_id,
                created_at=now,
            )
        )
        settlement.balance_rub += body.amount_rub
        postings.append(
            DisbursementPosting(
                debit=loan_account.number,
                credit=settlement.number,
                amount_rub=body.amount_rub,
                purpose=purpose,
            )
        )
    await session.flush()
    return DisbursementResult(
        disbursement_id=f"dsb_{loan_id:07d}",
        loan=loan,
        postings=postings,
        value_date=today,
        settlement_balance_rub=settlement.balance_rub,
    )


# ---- 7.6 комплаенс ----


async def screen(
    session: AsyncSession, subjects: list[ScreeningSubject]
) -> tuple[str, list[ScreeningResult]]:
    inns = {s.inn for s in subjects}
    entries = (
        await session.scalars(sa.select(m.ComplianceEntry).where(m.ComplianceEntry.inn.in_(inns)))
    ).all()
    ratings = {
        r.inn: r
        for r in await session.scalars(sa.select(m.ZskRating).where(m.ZskRating.inn.in_(inns)))
    }
    aml = {e.inn: e for e in entries if e.list_type == "AML"}
    stop = {e.inn: e for e in entries if e.list_type == "INTERNAL_STOP"}

    results: list[ScreeningResult] = []
    for s in subjects:
        a, st, rating = aml.get(s.inn), stop.get(s.inn), ratings.get(s.inn)
        # Уровень риска платформы «Знай своего клиента» есть только у компаний и ИП
        has_zsk = s.role in ("COMPANY", "IE") and rating is not None
        results.append(
            ScreeningResult(
                inn=s.inn,
                role=s.role,
                aml_list=AmlListOut(listed=a is not None, list_name=a.list_name if a else None),
                zsk=ZskOut(risk_level=rating.risk_level, assessed_at=rating.assessed_at)
                if has_zsk and rating
                else None,
                internal_stop_list=StopListOut(
                    listed=st is not None, reason=st.reason if st else None
                ),
            )
        )
    hit = any(r.aml_list.listed or r.internal_stop_list.listed for r in results)
    return ("HIT" if hit else "CLEAR"), results


def new_screening_id() -> str:
    return "scr_" + secrets.token_hex(4).upper()
