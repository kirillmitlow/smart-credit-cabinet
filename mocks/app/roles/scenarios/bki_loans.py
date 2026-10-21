"""Обязательства и заготовки bank-core из параметров сценария (T-123)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.common.reldate import add_months, resolve
from app.roles.scenarios.credit_math import (
    amount_for_payment,
    annuity,
    due_date,
    external_balance,
    implied_rate,
    money,
    schedule,
)
from app.roles.scenarios.credit_uid import contract_uid
from app.roles.scenarios.schemas import ActiveLoan, ClosedLoan

LIMIT_KINDS = frozenset({"CREDIT_LINE", "OVERDRAFT", "CREDIT_CARD"})


@dataclass(frozen=True)
class CreditDefaults:
    """Настройки генерации; ставка и минимальный платёж не зашиты в формулы."""

    rate_percent: Decimal = Decimal(21)
    limit_payment_percent: Decimal = Decimal(5)

    def __post_init__(self) -> None:
        if not 0 <= self.rate_percent <= 200 or not 0 <= self.limit_payment_percent <= 100:
            raise ValueError("Некорректные настройки ставки или платежа по лимитам")


DEFAULTS = CreditDefaults()


def absolute(expr: str, today: date) -> date:
    return resolve(expr, today) if expr.startswith(("+", "-")) else date.fromisoformat(expr)


def normalized_kind(kind: str) -> str:
    return "LOAN" if kind in {"CONSUMER_LOAN", "MICROLOAN"} else kind


def _base(uid: str, kind: str, opened: date, planned: date, secured: bool) -> dict[str, Any]:
    return {
        "uid": uid,
        "kind": normalized_kind(kind),
        "role": "BORROWER",
        "openedAt": opened.isoformat(),
        "plannedCloseAt": planned.isoformat(),
        "closedAt": None,
        "amountRub": None,
        "limitRub": None,
        "balanceRub": 0,
        "monthlyPaymentRub": None,
        "overdueRub": 0,
        "overduePeriods": [],
        "status": "ACTIVE",
        "secured": secured,
        "paymentHistory": None,
    }


def active_loan(
    loan: ActiveLoan,
    code: str,
    inn: str,
    index: int,
    today: date,
    earliest: date | None,
    defaults: CreditDefaults = DEFAULTS,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    term = loan.term_months or 24
    if term > 1200:
        raise ValueError("Срок сценарного кредита не должен превышать 1200 месяцев")
    opened = (
        absolute(loan.opened_at, today)
        if loan.opened_at
        else add_months(today, -min(term // 2, 18))
    )
    if earliest is not None and opened < earliest:
        if loan.opened_at:
            raise ValueError("Кредит компании не может быть открыт до её регистрации")
        opened = earliest
    if opened > today:
        raise ValueError("openedAt активного кредита не может быть в будущем")
    planned = add_months(opened, term)
    if due_date(opened, term, working_days=bool(loan.our_bank)) <= today:
        raise ValueError("Срок activeLoans истёк; перенесите кредит в closedLoans")
    uid = contract_uid(code, inn, f"active-{index}")
    body = _base(uid, loan.kind, opened, planned, bool(loan.secured))
    rate = (
        Decimal(str(loan.rate_percent)) if loan.rate_percent is not None else defaults.rate_percent
    )
    revolving = loan.kind in LIMIT_KINDS
    if revolving:
        limit, balance = loan.limit_rub, loan.balance_rub or 0
        assert limit is not None  # noqa: S101
        if balance > limit:
            raise ValueError("balanceRub не может превышать limitRub")
        body.update(
            limitRub=limit,
            balanceRub=balance,
            monthlyPaymentRub=money(Decimal(balance) * defaults.limit_payment_percent / 100),
        )
        amount = balance
    else:
        amount = loan.amount_rub or amount_for_payment(loan.monthly_payment_rub or 0, term, rate)
        if loan.monthly_payment_rub is not None:
            if loan.rate_percent is None:
                rate = implied_rate(amount, term, loan.monthly_payment_rub)
            elif money(annuity(amount, term, rate)) != loan.monthly_payment_rub:
                raise ValueError("ratePercent и monthlyPaymentRub задают разные платежи")
        if loan.our_bank:
            rows = schedule(amount, term, rate, opened)
            paid_rows = [row for row in rows if row.day <= today]
            balance = paid_rows[-1].balance if paid_rows else amount
            payment = rows[0].payment
        else:
            paid = sum(due_date(opened, month) <= today for month in range(1, term + 1))
            balance = external_balance(amount, term, rate, paid)
            payment = money(annuity(amount, term, rate), 100)
        body.update(amountRub=amount, balanceRub=balance, monthlyPaymentRub=payment)
    bank = None
    if loan.our_bank:
        if body["kind"] not in {"LOAN", "CREDIT_LINE", "OVERDRAFT"}:
            raise ValueError("ourBank поддерживает только LOAN, CREDIT_LINE и OVERDRAFT")
        if term > 600 or rate > 100:
            raise ValueError("ourBank: bank-core допускает срок до 600 месяцев и ставку до 100%")
        bank = {
            "applicationRef": f"SC-{uid}",
            "contractNumber": f"SC-{uid}",
            "contractUid": uid,
            "productCode": "WORKING_CAPITAL" if not revolving else body["kind"],
            "kind": body["kind"],
            "amountRub": amount,
            "limitRub": loan.limit_rub if revolving else None,
            "termMonths": term,
            "ratePercent": float(rate),
            "repaymentType": "REVOLVING" if revolving else "ANNUITY",
            "status": "ACTIVE",
            "disbursedAt": opened.isoformat(),
            "settlementAccount": None,
        }
    return body, bank


def closed_loan(
    loan: ClosedLoan,
    code: str,
    inn: str,
    label: str,
    today: date,
    earliest: date | None,
    defaults: CreditDefaults = DEFAULTS,
) -> dict[str, Any]:
    opened, closed = absolute(loan.opened_at, today), absolute(loan.closed_at, today)
    if not opened < closed <= today:
        raise ValueError("closedLoans: нужны openedAt < closedAt ≤ сегодня")
    if earliest is not None and opened < earliest:
        raise ValueError("Закрытый кредит компании не может быть открыт до её регистрации")
    term = max(1, (closed.year - opened.year) * 12 + closed.month - opened.month)
    payment = (
        money(Decimal(loan.amount_rub) * defaults.rate_percent / 1200, 100)
        if loan.repayment == "BULLET"
        else money(annuity(loan.amount_rub, term, defaults.rate_percent), 100)
    )
    body = _base(contract_uid(code, inn, label), loan.kind, opened, closed, bool(loan.secured))
    if loan.kind in LIMIT_KINDS:
        body["limitRub"] = loan.amount_rub
        payment = 0
    else:
        body["amountRub"] = loan.amount_rub
    body.update(
        closedAt=closed.isoformat(), balanceRub=0, monthlyPaymentRub=payment, status="CLOSED"
    )
    return body
