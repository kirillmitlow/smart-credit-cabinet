"""Чистая Decimal-математика сценарных кредитов по 30-16 и mocks 10.3.

Ядро T-280 пока не реализовано: его будущий модуль должен стать общим источником
этих формул. Здесь нет HTTP, БД и зависимости от ролей других моков.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.common.reldate import add_months


@dataclass(frozen=True)
class Instalment:
    day: date
    payment: int
    principal: int
    interest: int
    balance: int


def money(value: Decimal, step: int = 1) -> int:
    return int((value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * step


def annuity(amount: int, term: int, rate: Decimal) -> Decimal:
    if amount <= 0 or term < 1 or rate < 0:
        raise ValueError("Нужны положительные сумма, срок и неотрицательная ставка")
    with localcontext() as context:
        context.prec = 40
        monthly = rate / 1200
        return (
            Decimal(amount) / term
            if monthly == 0
            else amount * monthly / (1 - (1 + monthly) ** -term)
        )


def implied_rate(amount: int, term: int, payment: int) -> Decimal:
    """Неотрицательная ставка, при которой заданный платёж совпадает до рубля."""
    low, high = Decimal(0), Decimal(200)
    if payment < money(annuity(amount, term, low)) or payment > money(annuity(amount, term, high)):
        raise ValueError("monthlyPaymentRub несовместим с суммой и сроком при ставке 0…200%")
    with localcontext() as context:
        context.prec = 40
        for _ in range(140):
            mid = (low + high) / 2
            if annuity(amount, term, mid) < payment:
                low = mid
            else:
                high = mid
        return (low + high) / 2


def amount_for_payment(payment: int, term: int, rate: Decimal) -> int:
    if payment <= 0:
        raise ValueError("monthlyPaymentRub должен быть положительным для активного кредита")
    with localcontext() as context:
        context.prec = 40
        return max(1, money(Decimal(payment) / annuity(1, term, rate)))


def due_date(opened: date, month: int, *, working_days: bool = False) -> date:
    day = add_months(opened.replace(day=min(opened.day, 28)), month)
    if working_days and day.weekday() >= 5:
        day += timedelta(days=7 - day.weekday())
    return day


def schedule(
    amount: int, term: int, rate: Decimal, opened: date, *, bullet: bool = False
) -> list[Instalment]:
    """График ядра до 1 ₽; последний платёж закрывает весь остаток."""
    payment = money(annuity(amount, term, rate))
    remaining = amount
    result = []
    with localcontext() as context:
        context.prec = 40
        for month in range(1, term + 1):
            interest = money(Decimal(remaining) * rate / 1200)
            principal = (
                remaining
                if month == term
                else (0 if bullet else min(remaining, max(0, payment - interest)))
            )
            remaining -= principal
            result.append(
                Instalment(
                    due_date(opened, month, working_days=True),
                    principal + interest,
                    principal,
                    interest,
                    remaining,
                )
            )
    return result


def external_balance(amount: int, term: int, rate: Decimal, paid: int) -> int:
    """Чужой кредит: точная формула остатка, затем сценарное округление до 1000 ₽."""
    if paid >= term:
        return 0
    with localcontext() as context:
        context.prec = 40
        monthly = rate / 1200
        payment = annuity(amount, term, rate)
        balance = (
            (Decimal(amount) - payment * paid)
            if monthly == 0
            else (amount * (1 + monthly) ** paid - payment * ((1 + monthly) ** paid - 1) / monthly)
        )
        return min(amount, max(0, money(balance, 1000)))
