"""Чтение и запись данных mock-tax (раздел 5.7).

«Сводные» значения считаются при чтении: `dataActualAt`, `summary`, `previous`, `availableYears`,
признак «снята» у блокировки. В базе лежат только исходные факты.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import Origin
from app.common.problems import ProblemException
from app.roles.tax import models as m
from app.roles.tax import schemas as sc

RMSP_UPDATE_DAY = 10


# --- даты «сведения актуальны на» ----------------------------------------------------------------


def first_of_month(today: date) -> date:
    """«Прозрачный бизнес» (5.1): один срез на первое число текущего месяца."""
    return today.replace(day=1)


def rmsp_actual_at(today: date) -> date:
    """Реестр МСП обновляется 10-го числа каждого месяца (5.3)."""
    if today.day >= RMSP_UPDATE_DAY:
        return today.replace(day=RMSP_UPDATE_DAY)
    previous_month = today.replace(day=1) - timedelta(days=1)
    return previous_month.replace(day=RMSP_UPDATE_DAY)


def yesterday(today: date) -> date:
    return today - timedelta(days=1)


# --- 5.1 налоговый профиль -----------------------------------------------------------------------


async def load_tax_profile(session: AsyncSession, inn: str) -> sc.TaxProfileCard | None:
    row = await session.get(m.TaxProfile, inn)
    if row is None:
        return None
    paid = await session.scalars(
        sa.select(m.TaxPaid).where(m.TaxPaid.inn == inn).order_by(m.TaxPaid.year.desc())
    )
    income = None
    if row.income_rub is not None:
        income = sc.IncomeExpenses(
            year=row.income_year or 0, income_rub=row.income_rub, expenses_rub=row.expenses_rub or 0
        )
    headcount = None
    if row.avg_headcount is not None:
        headcount = sc.AvgHeadcount(value=row.avg_headcount, year=row.headcount_year or 0)
    return sc.TaxProfileCard(
        inn=inn,
        tax_regimes=[sc.TaxRegime.model_validate(r) for r in row.tax_regimes],
        avg_headcount=headcount,
        taxes_paid=[sc.TaxesPaidItem(year=p.year, total_rub=p.total_rub) for p in paid],
        debts=sc.Debts(
            as_of=row.debts_as_of,
            tax_debt_rub=row.tax_debt_rub,
            penalties_rub=row.penalties_rub,
            fines_rub=row.fines_rub,
        ),
        income_expenses=income,
        tax_offenses=(
            None if row.tax_offenses is None else sc.TaxOffenses.model_validate(row.tax_offenses)
        ),
        risk_flags=sc.RiskFlags.model_validate(row.risk_flags),
    )


# --- 5.2 отчётность ------------------------------------------------------------------------------


async def load_financials(
    session: AsyncSession, inn: str, year: int | None
) -> sc.FinancialsCard | None:
    """Ответ без `meta`; `None`, если такого года (или отчётности вообще) нет."""
    rows = {
        r.year: r
        for r in await session.scalars(
            sa.select(m.FinancialStatement).where(m.FinancialStatement.inn == inn)
        )
    }
    if not rows:
        return None
    chosen_year = max(rows) if year is None else year  # без year — последний доступный
    row = rows.get(chosen_year)
    if row is None:
        return None
    previous = rows.get(chosen_year - 1)
    lines = {
        code: sc.LinePair(
            current=row.lines[code], previous=None if previous is None else previous.lines[code]
        )
        for code in sc.LINE_CODES
    }
    cur = row.lines
    return sc.FinancialsCard(
        inn=inn,
        year=chosen_year,
        available_years=sorted(rows, reverse=True),
        form_type=row.form_type,
        submitted_at=row.submitted_at,
        lines=lines,
        summary=sc.FinancialSummary(
            revenue_rub=cur["2110"],
            sales_profit_rub=cur["2200"],
            interest_payable_rub=cur["2330"],
            net_profit_rub=cur["2400"],
            total_assets_rub=cur["1600"],
            equity_rub=cur["1300"],
            long_term_liabilities_rub=cur["1400"],
            short_term_liabilities_rub=cur["1500"],
        ),
    )


# --- 5.3 МСП, 5.4 НПД ----------------------------------------------------------------------------


async def sme_status(session: AsyncSession, inn: str) -> m.SmeRegistry | None:
    return await session.get(m.SmeRegistry, inn)


async def is_self_employed(session: AsyncSession, inn: str, on: date) -> bool:
    row = await session.get(m.NpdStatus, inn)
    if row is None or row.registered_at > on:
        return False
    return row.deregistered_at is None or row.deregistered_at > on


# --- 5.5 блокировки ------------------------------------------------------------------------------


async def active_blocks(session: AsyncSession, inn: str, bik: str | None) -> list[sc.BlockDecision]:
    """Действующие решения: снятые (`lifted_at` не NULL) в ответе не показываются (5.7)."""
    query = sa.select(m.AccountBlock).where(
        m.AccountBlock.inn == inn, m.AccountBlock.lifted_at.is_(None)
    )
    if bik is not None:
        query = query.where(m.AccountBlock.bik == bik)
    rows = await session.scalars(
        query.order_by(m.AccountBlock.decision_date.desc(), m.AccountBlock.number)
    )
    return [
        sc.BlockDecision(
            number=b.number,
            date=b.decision_date,
            tax_authority_code=b.tax_authority_code,
            bik=b.bik,
            reason=b.reason,
        )
        for b in rows
    ]


# --- 5.6 госзакупки ------------------------------------------------------------------------------


def _contract(c: m.PublicContract) -> sc.Contract:
    return sc.Contract(
        registry_number=c.registry_number,
        customer=sc.Customer(name=c.customer_name, inn=c.customer_inn),
        subject=c.subject,
        price_rub=c.price_rub,
        concluded_at=c.concluded_at,
        execution_deadline=c.execution_deadline,
        payment_deadline=c.payment_deadline,
        status=c.status,
        paid_rub=c.paid_rub,
    )


async def contracts_of(session: AsyncSession, inn: str, status: str | None) -> list[sc.Contract]:
    """От новых к старым."""
    query = sa.select(m.PublicContract).where(m.PublicContract.supplier_inn == inn)
    if status is not None:
        query = query.where(m.PublicContract.status == status)
    rows = await session.scalars(
        query.order_by(m.PublicContract.concluded_at.desc(), m.PublicContract.registry_number)
    )
    return [_contract(c) for c in rows]


# --- тело админ-API ------------------------------------------------------------------------------


async def load_body(session: AsyncSession, inn: str) -> sc.TaxBody | None:
    if await session.get(m.TaxSubject, inn) is None:
        return None
    statements = await session.scalars(
        sa.select(m.FinancialStatement)
        .where(m.FinancialStatement.inn == inn)
        .order_by(m.FinancialStatement.year.desc())
    )
    sme = await session.get(m.SmeRegistry, inn)
    npd = await session.get(m.NpdStatus, inn)
    blocks = await session.scalars(
        sa.select(m.AccountBlock).where(m.AccountBlock.inn == inn).order_by(m.AccountBlock.id)
    )
    contracts = await session.scalars(
        sa.select(m.PublicContract)
        .where(m.PublicContract.supplier_inn == inn)
        .order_by(m.PublicContract.position)
    )
    return sc.TaxBody(
        tax_profile=await load_tax_profile(session, inn),
        financials=[
            sc.FinancialRecord(
                year=s.year,
                form_type=s.form_type,
                submitted_at=s.submitted_at,
                lines=sc.StatementLines.model_validate(s.lines),
            )
            for s in statements
        ],
        sme=None
        if sme is None
        else sc.SmeRecord(
            category=sme.category,
            included_at=sme.included_at,
            is_newly_created=sme.is_newly_created,
            is_social_enterprise=sme.is_social_enterprise,
        ),
        npd=None
        if npd is None
        else sc.NpdRecord(registered_at=npd.registered_at, deregistered_at=npd.deregistered_at),
        account_blocks=[
            sc.AccountBlockRecord(
                number=b.number,
                date=b.decision_date,
                tax_authority_code=b.tax_authority_code,
                bik=b.bik,
                reason=b.reason,
                lifted_at=b.lifted_at,
            )
            for b in blocks
        ],
        contracts=[_contract(c) for c in contracts],
    )


async def subject_info(session: AsyncSession, inn: str) -> tuple[str | None, str] | None:
    subject = await session.get(m.TaxSubject, inn)
    return None if subject is None else (subject.scenario_code, subject.origin)


async def delete_subject(session: AsyncSession, inn: str) -> bool:
    result = await session.execute(sa.delete(m.TaxSubject).where(m.TaxSubject.inn == inn))
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def replace_subject(
    session: AsyncSession, inn: str, body: sc.TaxBody, scenario_code: str | None
) -> None:
    numbers = [c.registry_number for c in body.contracts]
    if numbers:
        taken = await session.scalar(
            sa.select(m.PublicContract.registry_number).where(
                m.PublicContract.registry_number.in_(numbers), m.PublicContract.supplier_inn != inn
            )
        )
        if taken is not None:
            raise ProblemException(
                422, "VALIDATION_ERROR", f"Контракт {taken} уже записан у другого поставщика"
            )
    await delete_subject(session, inn)
    origin = Origin.SCENARIO.value if scenario_code else Origin.RUNTIME.value
    session.add(m.TaxSubject(inn=inn, origin=origin, scenario_code=scenario_code))
    await session.flush()  # субъект должен быть в базе до записей, которые на него ссылаются

    profile = body.tax_profile
    if profile is not None:
        session.add(
            m.TaxProfile(
                inn=inn,
                tax_regimes=[r.model_dump(mode="json", by_alias=True) for r in profile.tax_regimes],
                avg_headcount=profile.avg_headcount.value if profile.avg_headcount else None,
                headcount_year=profile.avg_headcount.year if profile.avg_headcount else None,
                tax_debt_rub=profile.debts.tax_debt_rub,
                penalties_rub=profile.debts.penalties_rub,
                fines_rub=profile.debts.fines_rub,
                debts_as_of=profile.debts.as_of,
                income_rub=profile.income_expenses.income_rub if profile.income_expenses else None,
                expenses_rub=(
                    profile.income_expenses.expenses_rub if profile.income_expenses else None
                ),
                income_year=profile.income_expenses.year if profile.income_expenses else None,
                tax_offenses=(
                    profile.tax_offenses.model_dump(mode="json", by_alias=True)
                    if profile.tax_offenses
                    else None
                ),
                risk_flags=profile.risk_flags.model_dump(mode="json", by_alias=True),
            )
        )
        session.add_all(
            m.TaxPaid(inn=inn, year=t.year, total_rub=t.total_rub) for t in profile.taxes_paid
        )
    session.add_all(
        m.FinancialStatement(
            inn=inn,
            year=f.year,
            form_type=f.form_type,
            submitted_at=f.submitted_at,
            lines=_lines(f.lines),
        )
        for f in body.financials
    )
    if body.sme is not None:
        session.add(
            m.SmeRegistry(
                inn=inn,
                category=body.sme.category,
                included_at=body.sme.included_at,
                is_newly_created=body.sme.is_newly_created,
                is_social_enterprise=body.sme.is_social_enterprise,
            )
        )
    if body.npd is not None:
        session.add(
            m.NpdStatus(
                inn=inn,
                registered_at=body.npd.registered_at,
                deregistered_at=body.npd.deregistered_at,
            )
        )
    session.add_all(
        m.AccountBlock(
            inn=inn,
            number=b.number,
            decision_date=b.date,
            tax_authority_code=b.tax_authority_code,
            bik=b.bik,
            reason=b.reason,
            lifted_at=b.lifted_at,
        )
        for b in body.account_blocks
    )
    session.add_all(
        m.PublicContract(
            registry_number=c.registry_number,
            supplier_inn=inn,
            position=i,
            customer_name=c.customer.name,
            customer_inn=c.customer.inn,
            subject=c.subject,
            price_rub=c.price_rub,
            concluded_at=c.concluded_at,
            execution_deadline=c.execution_deadline,
            payment_deadline=c.payment_deadline,
            status=c.status,
            paid_rub=c.paid_rub,
        )
        for i, c in enumerate(body.contracts)
    )
    await session.flush()


def _lines(lines: sc.StatementLines) -> dict[str, int]:
    return dict(lines.model_dump(by_alias=True))


# --- список, сценарии, сброс ------------------------------------------------------------------------


def _filtered(scenario: str | None, origin: Origin | None) -> sa.Select[Any]:
    query = sa.select(m.TaxSubject)
    if scenario:
        query = query.where(m.TaxSubject.scenario_code == scenario)
    if origin:
        query = query.where(m.TaxSubject.origin == origin.value)
    return query


async def list_subjects(
    session: AsyncSession, scenario: str | None, origin: Origin | None, limit: int, offset: int
) -> tuple[list[m.TaxSubject], int]:
    query = _filtered(scenario, origin)
    total = await session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(m.TaxSubject.inn).limit(limit).offset(offset))
    return list(rows), int(total or 0)


async def scenario_counts(session: AsyncSession) -> list[tuple[str, int]]:
    rows = await session.execute(
        sa.select(m.TaxSubject.scenario_code, sa.func.count())
        .where(m.TaxSubject.scenario_code.is_not(None))
        .group_by(m.TaxSubject.scenario_code)
        .order_by(m.TaxSubject.scenario_code)
    )
    return [(code, n) for code, n in rows if code is not None]


async def delete_scenario(session: AsyncSession, code: str) -> int:
    result = await session.execute(
        sa.delete(m.TaxSubject).where(m.TaxSubject.scenario_code == code)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def wipe(session: AsyncSession) -> None:
    await session.execute(sa.delete(m.TaxSubject))  # остальное — каскадом
