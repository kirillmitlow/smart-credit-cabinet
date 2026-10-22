"""Калькулятор платежа (T-241, 30-16): тот же код, что у ядра и графика оферты.

Без `ratePercent` считаем по базовой ставке каталога (10-06, 30-09: «ставка от») и помечаем
расчёт ориентировочным: итоговую ставку даст ядро после проверки. С `ratePercent` (ставка из
оферты) число совпадает с графиком оферты до рубля.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from app.modules.decisioning import (
    Policy,
    Product,
    ProductContext,
    build_schedule,
    bullet_schedule,
    check_product,
    lowest_rate,
    overpayment,
    payment_for,
)
from app.shared.errors import AppError

from .schemas import PaymentKind, PaymentOut

_CTX = Context(prec=40, rounding=ROUND_HALF_UP)
_PERCENT_STEP = Decimal("0.01")

# Проверяем только границы суммы и срока: остальное зависит от компании, не от калькулятора
_ANY_COMPANY = ProductContext(
    app_today=date(2000, 1, 1),
    business_age_months=None,
    registration_date=None,
    is_bank_customer=True,
    customer_turnover_months=10_000,
    collateral_provided=True,
    security_confirmed=True,
)


def validate_bounds(policy: Policy, code: str, amount_rub: int, term_months: int) -> None:
    """Значения вне границ продукта → 422 VALIDATION_ERROR с путём к полю."""
    cfg = policy.product_config(code)
    reasons = check_product(policy, Product(code), amount_rub, term_months, _ANY_COMPANY)
    if not any(r.code == "AMOUNT_OUT_OF_RANGE" for r in reasons):
        return
    errors: list[dict[str, object]] = []
    if not cfg.amount_min_rub <= amount_rub <= cfg.amount_max_rub:
        errors.append(
            {
                "loc": ["body", "amountRub"],
                "msg": f"Сумма для продукта {code}: от {cfg.amount_min_rub} до {cfg.amount_max_rub} ₽",
                "type": "value_error.range",
            }
        )
    if not cfg.term_min_months <= term_months <= cfg.term_max_months:
        errors.append(
            {
                "loc": ["body", "termMonths"],
                "msg": f"Срок для продукта {code}: от {cfg.term_min_months} до {cfg.term_max_months} мес.",
                "type": "value_error.range",
            }
        )
    raise AppError(422, "VALIDATION_ERROR", "Значения вне границ продукта", errors=errors)


def effective_rate_percent(annual_rate: Decimal) -> Decimal:
    """Эффективная годовая ставка при ежемесячных платежах: `(1 + r/12)^12 − 1`, в процентах."""
    with localcontext(_CTX):
        monthly = annual_rate / 12
        value = ((Decimal(1) + monthly) ** 12 - 1) * 100
        return value.quantize(_PERCENT_STEP, rounding=ROUND_HALF_UP)


def resolve_rate(policy: Policy, code: str, rate_percent: Decimal | None) -> Decimal:
    """Годовая ставка долей. Заданная должна лежать в коридоре продукта (10-06, R-003)."""
    cfg = policy.product_config(code)
    if rate_percent is None:
        return cfg.base_rate
    rate = rate_percent / 100
    corridor = policy.catalog.rate_corridor.value
    if not cfg.base_rate - corridor <= rate <= cfg.base_rate + corridor:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Ставка вне коридора продукта",
            errors=[
                {
                    "loc": ["body", "ratePercent"],
                    "msg": f"Для {code}: от {(cfg.base_rate - corridor) * 100:f} до "
                    f"{(cfg.base_rate + corridor) * 100:f} %",
                    "type": "value_error.range",
                }
            ],
        )
    return rate


def calculate(
    policy: Policy, code: str, amount_rub: int, term_months: int, rate_percent: Decimal | None
) -> PaymentOut:
    validate_bounds(policy, code, amount_rub, term_months)
    cfg = policy.product_config(code)
    rate = resolve_rate(policy, code, rate_percent)
    repayment = cfg.repayment.value
    payment = payment_for(repayment, amount_rub, rate, term_months)
    kind = PaymentKind.ANNUITY
    if repayment == "ANNUITY":
        schedule = build_schedule(amount_rub, rate, term_months)
        last, total = schedule[-1].payment, sum(row.payment for row in schedule)
        over = overpayment(schedule, amount_rub)
    elif repayment == "BULLET":
        kind = PaymentKind.INTEREST_ONLY
        rows = bullet_schedule(amount_rub, rate, term_months)
        last, total = rows[-1].payment, sum(row.payment for row in rows)
        over = overpayment(rows, amount_rub)
    else:
        # Линия и овердрафт (D-093): долг клиент возвращает сам в пределах лимита; считаем проценты
        # на весь лимит, как для DSCR (30-08, способ 3б)
        kind = PaymentKind.INTEREST_ONLY
        payment = payment_for("LINE", amount_rub, rate, term_months)
        last, total, over = payment, payment * term_months, payment * term_months
    return PaymentOut(
        product_code=code,
        amount_rub=amount_rub,
        term_months=term_months,
        payment_kind=kind,
        payment_rub=payment,
        last_payment_rub=last,
        total_payment_rub=total,
        overpayment_rub=over,
        rate_percent=rate * 100,
        rate_percent_from=lowest_rate(policy, Product(code)) * 100,
        effective_rate_percent=effective_rate_percent(rate),
        approximate=rate_percent is None,
    )
