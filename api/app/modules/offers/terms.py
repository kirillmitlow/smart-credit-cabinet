"""Условия займа для карточки и договора: платёж, последний платёж, переплата, график (30-16).

Единственное место, где предложение считает деньги: все числа берутся из функций ядра
`decisioning` (те же, что у калькулятора каталога и у графика кредита), поэтому «платёж на
карточке = платёж в графике = калькулятор» (T-340). Линия и овердрафт (D-093) считаются как в
калькуляторе: проценты на весь лимит.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.modules import catalog
from app.modules.decisioning import (
    ScheduleRow,
    build_schedule,
    bullet_schedule,
    overpayment,
    payment_for,
)

PREVIEW_ROWS = 3


@dataclass(frozen=True, slots=True)
class LoanTerms:
    payment_rub: int
    last_payment_rub: int
    overpayment_rub: int
    total_rub: int
    schedule: tuple[ScheduleRow, ...]


def repayment_of(product_code: str) -> str:
    return catalog.get_policy().product_config(product_code).repayment.value


def product_title(product_code: str) -> str:
    return catalog.get_policy().product_config(product_code).title


def loan_terms(
    product_code: str, amount_rub: int, annual_rate: Decimal, term_months: int
) -> LoanTerms:
    """Платёж и график по виду погашения продукта. `annual_rate` — доля (0,215), не проценты."""
    repayment = repayment_of(product_code)
    if repayment == "ANNUITY":
        rows = build_schedule(amount_rub, annual_rate, term_months)
    elif repayment == "BULLET":
        rows = bullet_schedule(amount_rub, annual_rate, term_months)
    else:
        payment = payment_for("LINE", amount_rub, annual_rate, term_months)
        rows = tuple(
            ScheduleRow(k, payment, 0, payment, amount_rub) for k in range(1, term_months + 1)
        )
    total = sum(row.payment for row in rows)
    return LoanTerms(
        payment_rub=rows[0].payment,
        last_payment_rub=rows[-1].payment,
        overpayment_rub=overpayment(rows, amount_rub)
        if repayment in ("ANNUITY", "BULLET")
        else total,
        total_rub=total,
        schedule=rows,
    )


def preview(rows: tuple[ScheduleRow, ...]) -> list[ScheduleRow]:
    """Первые платежи и последний: клиенту хватает, чтобы понять ритм."""
    if len(rows) <= PREVIEW_ROWS + 1:
        return list(rows)
    return [*rows[:PREVIEW_ROWS], rows[-1]]
