"""Хранение админ-API mock-bank-core (раздел 8.3): клиент, счета, обороты, кредиты, комплаенс.

Субъект — ИНН. Это клиент банка (customers и всё, что к нему привязано) и/или запись в
справочниках комплаенса: директор-террорист в перечне клиентом банка быть не обязан.
`PUT` заменяет всё, что мок знает об ИНН, включая RUNTIME-записи (проводки выдач в том числе).
Номера счетов и кредитов при замене сохраняются, если их передали в теле (их отдаёт `GET`),
а у кредитов — если совпала заявка: правка через `PATCH` не меняет `loanId` и ссудный счёт.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.accounts import OUR_BANK_BIK, account_is_valid
from app.common.admin import (
    AdminHandler,
    ScenarioCount,
    SubjectSummary,
    SubjectView,
    make_admin_router,
)
from app.common.clock import Clock
from app.common.db import Origin
from app.common.idempotency import forget_replies, idempotency_keys
from app.common.problems import ProblemException
from app.roles.bank_core import models as m
from app.roles.bank_core import service
from app.roles.bank_core.schemas import (
    AccountBody,
    AmlBody,
    BankCoreBody,
    ComplianceBody,
    CustomerBody,
    LoanBody,
    StopListBody,
    TurnoverBody,
    ZskBody,
)


@dataclass(frozen=True)
class AdminEnv:
    """БИК и часы стенда: обработчик админ-API сессию получает, а настройки — нет."""

    bik: str
    clock: Clock | None


_env: ContextVar[AdminEnv | None] = ContextVar("bank_core_admin_env", default=None)
_DEFAULT_ENV = AdminEnv(OUR_BANK_BIK, None)


def _current() -> AdminEnv:
    return _env.get() or _DEFAULT_ENV


async def _bind_env(request: Request) -> None:
    _env.set(AdminEnv(request.app.state.settings.bank_bik, request.app.state.clock))


def _today() -> date:
    clock = _current().clock
    if clock is None:
        raise RuntimeError("Часы стенда не заданы: обработчик вызван вне запроса")
    return clock.today()


def _invalid(detail: str) -> ProblemException:
    return ProblemException(422, "VALIDATION_ERROR", detail)


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def _month_start(value: str) -> date:
    return date(int(value[:4]), int(value[5:7]), 1)


class BankCoreAdminHandler(AdminHandler[BankCoreBody]):
    body_model = BankCoreBody

    # ---- проверки ----

    def check(self, inn: str, body: BankCoreBody, *, bank_bik: str | None = None) -> None:
        if body.customer is None:
            if body.accounts or body.turnover or body.loans:
                raise _invalid(
                    "Счета, обороты и кредиты возможны только у клиента: задайте customer"
                )
            return
        service.check_customer_type(inn, body.customer.type)
        bik = bank_bik or _current().bik
        prefix = service.SETTLEMENT_BALANCE[body.customer.type]
        numbers = [a.number for a in body.accounts if a.number]
        for number in numbers:
            if not account_is_valid(bik, number) or not number.startswith(prefix):
                raise _invalid(
                    f"Счёт {number}: неверный ключ для БИК {bik} или балансовый счёт не {prefix}"
                )
        for label, values in (
            ("номера счетов", numbers),
            ("месяцы оборотов", [t.month for t in body.turnover]),
            ("заявки кредитов", [x.application_ref for x in body.loans]),
            ("УИд договоров", [x.contract_uid for x in body.loans]),
            ("номера договоров", [x.contract_number for x in body.loans]),
        ):
            if dupes := _duplicates(values):
                raise _invalid(f"Повторяются {label}: {', '.join(dupes)}")
        if body.loans and not body.accounts:
            raise _invalid("Кредит нужно зачислить на расчётный счёт: добавьте accounts")
        for loan in body.loans:
            if loan.kind != "LOAN" and loan.limit_rub is None:
                raise _invalid(
                    f"Кредит {loan.application_ref}: для линии и овердрафта нужен limitRub"
                )
            if loan.settlement_account and loan.settlement_account not in numbers:
                raise _invalid(
                    f"Кредит {loan.application_ref}: счёт {loan.settlement_account} "
                    "не указан среди accounts[].number"
                )

    # ---- запись ----

    async def put(
        self, session: AsyncSession, inn: str, body: BankCoreBody, scenario_code: str | None
    ) -> None:
        origin = (Origin.SCENARIO if scenario_code else Origin.RUNTIME).value
        old_loan_ids: dict[str, int] = {}
        existing = await service.find_customer(session, inn)
        if existing is not None:
            old = await service.customer_loans(session, existing.id)
            old_loan_ids = {loan.application_ref: loan.id for loan in old}
        await self._erase(session, inn)
        session.expunge_all()  # прежние объекты стёрты: новые с теми же ключами не должны с ними спорить

        if body.customer is not None:
            await self._write_customer(session, inn, body, origin, scenario_code, old_loan_ids)
        await self._write_compliance(session, inn, body.compliance, origin, scenario_code)

    async def _write_customer(
        self,
        session: AsyncSession,
        inn: str,
        body: BankCoreBody,
        origin: str,
        scenario_code: str | None,
        old_loan_ids: dict[str, int],
    ) -> None:
        assert body.customer is not None  # noqa: S101
        bik = _current().bik
        spec: CustomerBody = body.customer
        customer = m.Customer(
            inn=inn,
            type=spec.type,
            name=spec.name,
            customer_since=spec.customer_since,
            origin=origin,
            scenario_code=scenario_code,
        )
        session.add(customer)
        await session.flush()

        numbers: list[str] = []
        taken_by_others = set(
            await session.scalars(
                sa.select(m.Account.number).where(
                    m.Account.number.in_([a.number for a in body.accounts if a.number])
                )
            )
        )
        for acc in body.accounts:
            number = acc.number or await service.next_settlement_account(session, bik, spec.type)
            if number in taken_by_others:
                raise _invalid(f"Счёт {number} уже принадлежит другому клиенту")
            numbers.append(number)
            session.add(self._account(customer.id, number, acc, origin, scenario_code))
        await session.flush()

        for t in body.turnover:
            session.add(self._turnover(customer.id, t, origin, scenario_code))

        await self._check_loans_free(session, body.loans)
        for loan in body.loans:
            settlement = loan.settlement_account or numbers[0]
            loan_id = old_loan_ids.get(loan.application_ref) or await service.next_loan_id(session)
            loan_number = service.loan_account_number(bik, spec.type, loan_id)
            closed = loan.status == "CLOSED"
            session.add(
                m.Account(
                    number=loan_number,
                    customer_id=customer.id,
                    type="LOAN",
                    currency="RUB",
                    status="CLOSED" if closed else "OPEN",
                    opened_at=loan.disbursed_at,
                    balance_rub=0 if closed else loan.amount_rub,
                    origin=origin,
                    scenario_code=scenario_code,
                )
            )
            await session.flush()
            session.add(
                m.Loan(
                    id=loan_id,
                    customer_id=customer.id,
                    application_ref=loan.application_ref,
                    contract_number=loan.contract_number,
                    contract_uid=loan.contract_uid,
                    product_code=loan.product_code,
                    kind=loan.kind,
                    amount_rub=loan.amount_rub,
                    limit_rub=loan.limit_rub,
                    term_months=loan.term_months,
                    rate_percent=loan.rate_percent,
                    repayment_type=loan.repayment_type,
                    loan_account=loan_number,
                    settlement_account=settlement,
                    status=loan.status,
                    disbursed_at=loan.disbursed_at,
                    origin=origin,
                    scenario_code=scenario_code,
                )
            )
        await session.flush()

    @staticmethod
    def _account(
        customer_id: int, number: str, acc: AccountBody, origin: str, scenario_code: str | None
    ) -> m.Account:
        return m.Account(
            number=number,
            customer_id=customer_id,
            type="SETTLEMENT",
            currency="RUB",
            status=acc.status,
            opened_at=acc.opened_at,
            balance_rub=acc.balance_rub,
            origin=origin,
            scenario_code=scenario_code,
        )

    @staticmethod
    def _turnover(
        customer_id: int, t: TurnoverBody, origin: str, scenario_code: str | None
    ) -> m.MonthlyTurnover:
        return m.MonthlyTurnover(
            customer_id=customer_id,
            month=_month_start(t.month),
            incoming_rub=t.incoming_rub,
            incoming_net_rub=t.incoming_net_rub,
            outgoing_rub=t.outgoing_rub,
            counterparties_in=t.counterparties_in,
            counterparties_out=t.counterparties_out,
            origin=origin,
            scenario_code=scenario_code,
        )

    @staticmethod
    async def _check_loans_free(session: AsyncSession, loans: list[LoanBody]) -> None:
        if not loans:
            return
        clash = (
            await session.execute(
                sa.select(
                    m.Loan.application_ref, m.Loan.contract_uid, m.Loan.contract_number
                ).where(
                    sa.or_(
                        m.Loan.application_ref.in_([x.application_ref for x in loans]),
                        m.Loan.contract_uid.in_([x.contract_uid for x in loans]),
                        m.Loan.contract_number.in_([x.contract_number for x in loans]),
                    )
                )
            )
        ).first()
        if clash is not None:
            raise _invalid(
                f"Заявка {clash.application_ref}, УИд {clash.contract_uid} или договор "
                f"{clash.contract_number} уже есть у кредита другого клиента"
            )

    @staticmethod
    async def _write_compliance(
        session: AsyncSession,
        inn: str,
        compliance: ComplianceBody | None,
        origin: str,
        scenario_code: str | None,
    ) -> None:
        if compliance is None:
            return
        today = _today()
        common = {"origin": origin, "scenario_code": scenario_code}
        if compliance.aml is not None:
            session.add(
                m.ComplianceEntry(
                    inn=inn,
                    list_type="AML",
                    list_name=compliance.aml.list_name,
                    reason=compliance.aml.reason,
                    added_at=today,
                    **common,
                )
            )
        if compliance.internal_stop_list is not None:
            session.add(
                m.ComplianceEntry(
                    inn=inn,
                    list_type="INTERNAL_STOP",
                    list_name=None,
                    reason=compliance.internal_stop_list.reason,
                    added_at=today,
                    **common,
                )
            )
        if compliance.zsk is not None:
            session.add(
                m.ZskRating(
                    inn=inn,
                    risk_level=compliance.zsk.risk_level,
                    assessed_at=compliance.zsk.assessed_at,
                    **common,
                )
            )
        await session.flush()

    # ---- чтение ----

    async def get_body(self, session: AsyncSession, inn: str) -> BankCoreBody | None:
        customer = await service.find_customer(session, inn)
        compliance = await self._read_compliance(session, inn)
        if customer is None:
            return None if compliance is None else BankCoreBody(compliance=compliance)

        accounts = await service.customer_accounts(session, customer.id)
        turnover = (
            await session.scalars(
                sa.select(m.MonthlyTurnover)
                .where(m.MonthlyTurnover.customer_id == customer.id)
                .order_by(m.MonthlyTurnover.month)
            )
        ).all()
        loans = await service.customer_loans(session, customer.id)
        first = accounts[0].number if accounts else None
        return BankCoreBody(
            customer=CustomerBody(
                type=customer.type,
                name=customer.name,
                customer_since=customer.customer_since,
            ),
            accounts=[
                AccountBody(
                    number=a.number,
                    status=a.status,
                    opened_at=a.opened_at,
                    balance_rub=a.balance_rub,
                )
                for a in accounts
            ],
            turnover=[
                TurnoverBody(
                    month=t.month.strftime("%Y-%m"),
                    incoming_rub=t.incoming_rub,
                    incoming_net_rub=t.incoming_net_rub,
                    outgoing_rub=t.outgoing_rub,
                    counterparties_in=t.counterparties_in,
                    counterparties_out=t.counterparties_out,
                )
                for t in turnover
            ],
            loans=[
                LoanBody(
                    application_ref=x.application_ref,
                    contract_number=x.contract_number,
                    contract_uid=x.contract_uid,
                    product_code=x.product_code,
                    kind=x.kind,
                    amount_rub=x.amount_rub,
                    limit_rub=x.limit_rub,
                    term_months=x.term_months,
                    rate_percent=x.rate_percent,
                    repayment_type=x.repayment_type,
                    status=x.status,
                    disbursed_at=x.disbursed_at,
                    # Счёт по умолчанию (первый) не повторяем: правка accounts не ломает кредиты
                    settlement_account=None
                    if x.settlement_account == first
                    else x.settlement_account,
                )
                for x in loans
            ],
            compliance=compliance or ComplianceBody(),
        )

    @staticmethod
    async def _read_compliance(session: AsyncSession, inn: str) -> ComplianceBody | None:
        entries = {
            e.list_type: e
            for e in await session.scalars(
                sa.select(m.ComplianceEntry).where(m.ComplianceEntry.inn == inn)
            )
        }
        rating = await session.get(m.ZskRating, inn)
        if not entries and rating is None:
            return None
        aml, stop = entries.get("AML"), entries.get("INTERNAL_STOP")
        return ComplianceBody(
            aml=AmlBody(list_name=aml.list_name, reason=aml.reason) if aml else None,
            zsk=ZskBody(risk_level=rating.risk_level, assessed_at=rating.assessed_at)
            if rating
            else None,
            internal_stop_list=StopListBody(reason=stop.reason) if stop else None,
        )

    async def view(self, session: AsyncSession, inn: str) -> SubjectView | None:
        body = await self.get_body(session, inn)
        if body is None:
            return None
        customer = await service.find_customer(session, inn)
        origin_row: m.Customer | m.ComplianceEntry | m.ZskRating | None = customer
        if origin_row is None:
            origin_row = await session.scalar(
                sa.select(m.ComplianceEntry).where(m.ComplianceEntry.inn == inn).limit(1)
            ) or await session.get(m.ZskRating, inn)
        assert origin_row is not None  # noqa: S101
        runtime: dict[str, object] = {}
        if customer is not None:
            runtime = await self._runtime(session, customer)
        return SubjectView(
            inn=inn,
            scenario_code=origin_row.scenario_code,
            origin=origin_row.origin,
            data=body.model_dump(mode="json", by_alias=True),
            runtime=runtime,
        )

    @staticmethod
    async def _runtime(session: AsyncSession, customer: m.Customer) -> dict[str, object]:
        accounts = (
            await session.scalars(
                sa.select(m.Account)
                .where(m.Account.customer_id == customer.id)
                .order_by(m.Account.number)
            )
        ).all()
        numbers = [a.number for a in accounts]
        postings = (
            await session.scalars(
                sa.select(m.Posting)
                .where(
                    sa.or_(
                        m.Posting.debit_account.in_(numbers), m.Posting.credit_account.in_(numbers)
                    )
                )
                .order_by(m.Posting.id.desc())
                .limit(100)
            )
        ).all()
        loans = await service.customer_loans(session, customer.id)
        return {
            "loanAccounts": [
                service.account_out(a).model_dump(mode="json", by_alias=True)
                for a in accounts
                if a.type == "LOAN"
            ],
            "openedAccounts": [
                service.account_out(a).model_dump(mode="json", by_alias=True)
                for a in accounts
                if a.type == "SETTLEMENT" and a.origin == Origin.RUNTIME.value
            ],
            "loans": [
                {**service.loan_out(x).model_dump(mode="json", by_alias=True), "origin": x.origin}
                for x in loans
            ],
            "postings": [
                {
                    "debit": p.debit_account,
                    "credit": p.credit_account,
                    "amountRub": p.amount_rub,
                    "purpose": p.purpose,
                    "valueDate": p.value_date.isoformat(),
                    "loanId": service.loan_ref(p.loan_id) if p.loan_id else None,
                }
                for p in postings
            ],
        }

    # ---- списки и удаление ----

    @staticmethod
    def _subjects() -> sa.Subquery:
        """Один ряд на ИНН: клиент банка приоритетнее записей комплаенса."""
        c, e, z = m.Customer, m.ComplianceEntry, m.ZskRating
        union = sa.union_all(
            sa.select(
                c.inn, c.scenario_code, c.origin, c.name.label("title"), sa.literal(0).label("prio")
            ),
            sa.select(
                e.inn,
                e.scenario_code,
                e.origin,
                sa.literal(None, sa.String).label("title"),
                sa.literal(1),
            ),
            sa.select(
                z.inn,
                z.scenario_code,
                z.origin,
                sa.literal(None, sa.String).label("title"),
                sa.literal(2),
            ),
        ).subquery()
        return (
            sa.select(union)
            .ext(distinct_on(union.c.inn))
            .order_by(union.c.inn, union.c.prio)
            .subquery()
        )

    async def list_subjects(
        self,
        session: AsyncSession,
        scenario: str | None,
        origin: Origin | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SubjectSummary], int]:
        subjects = self._subjects()
        query = sa.select(subjects)
        if scenario:
            query = query.where(subjects.c.scenario_code == scenario)
        if origin:
            query = query.where(subjects.c.origin == origin.value)
        total = await session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))
        rows = (
            await session.execute(query.order_by(subjects.c.inn).limit(limit).offset(offset))
        ).all()
        items = [
            SubjectSummary(inn=r.inn, scenario_code=r.scenario_code, origin=r.origin, title=r.title)
            for r in rows
        ]
        return items, int(total or 0)

    async def scenarios(self, session: AsyncSession) -> list[ScenarioCount]:
        subjects = self._subjects()
        rows = await session.execute(
            sa.select(subjects.c.scenario_code, sa.func.count())
            .where(subjects.c.scenario_code.is_not(None))
            .group_by(subjects.c.scenario_code)
            .order_by(subjects.c.scenario_code)
        )
        return [ScenarioCount(scenario_code=code, subjects=count) for code, count in rows]

    async def delete(self, session: AsyncSession, inn: str) -> bool:
        return await self._erase(session, inn)

    async def delete_scenario(self, session: AsyncSession, code: str) -> int:
        inns: set[str] = set()
        for table in (m.Customer, m.ComplianceEntry, m.ZskRating):
            inns.update(
                await session.scalars(sa.select(table.inn).where(table.scenario_code == code))
            )
        for inn in inns:
            await self._erase(session, inn)
        return len(inns)

    async def wipe(self, session: AsyncSession) -> None:
        for table in (
            m.Posting,
            m.Loan,
            m.MonthlyTurnover,
            m.Account,
            m.Customer,
            m.ComplianceEntry,
            m.ZskRating,
        ):
            await session.execute(sa.delete(table))
        # Сохранённые ответы выдач ссылаются на уже стёртые кредиты: повтор вернул бы призрак
        await session.execute(sa.delete(idempotency_keys))

    @staticmethod
    async def _erase(session: AsyncSession, inn: str) -> bool:
        """Стереть всё об ИНН: клиента, счета, проводки, обороты, кредиты и комплаенс."""
        existed = False
        customer = await service.find_customer(session, inn)
        if customer is not None:
            existed = True
            numbers = list(
                await session.scalars(
                    sa.select(m.Account.number).where(m.Account.customer_id == customer.id)
                )
            )
            await forget_replies(
                session, {"number": set(numbers), "settlementAccount": set(numbers)}
            )
            await session.execute(
                sa.delete(m.Posting).where(
                    sa.or_(
                        m.Posting.debit_account.in_(numbers), m.Posting.credit_account.in_(numbers)
                    )
                )
            )
            await session.execute(sa.delete(m.Loan).where(m.Loan.customer_id == customer.id))
            await session.execute(
                sa.delete(m.MonthlyTurnover).where(m.MonthlyTurnover.customer_id == customer.id)
            )
            await session.execute(sa.delete(m.Account).where(m.Account.customer_id == customer.id))
            await session.execute(sa.delete(m.Customer).where(m.Customer.id == customer.id))
        for table in (m.ComplianceEntry, m.ZskRating):
            result = await session.execute(sa.delete(table).where(table.inn == inn))
            existed = existed or bool(cast(CursorResult[Any], result).rowcount)
        await session.flush()
        return existed


# Родительский роутер привязывает БИК и часы стенда к запросу: на маршруты вложенного роутера
# зависимости родителя действуют так же, как свои.
admin_router = APIRouter(dependencies=[Depends(_bind_env)])
admin_router.include_router(make_admin_router(BankCoreAdminHandler()))
