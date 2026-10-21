"""Ставка по ожидаемым потерям (T-292, 30-09, D-071).

`ставка = ключевая + спред + PD·LGD + расходы + плата за капитал`, округление до 0,5 п.п.
«половина вверх», затем коридор продукта «базовая ± 4 п.п.». Не зависит от суммы (D-084).
Поручительство LGD не меняет: уменьшает LGD только залог.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from app.modules.decisioning.policy import Policy
from app.modules.decisioning.types import Grade, Product, RateBreakdown

_CTX = Context(prec=40, rounding=ROUND_HALF_UP)


def _round_to_step(value: Decimal, step: Decimal) -> Decimal:
    with localcontext(_CTX):
        return (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


def raw_rate(policy: Policy, product: Product, grade: Grade, collateral: bool) -> Decimal:
    pr = policy.pricing
    pd = policy.grade_row(grade.value).pd
    lgd = pr.lgd_secured.value if collateral else pr.lgd_unsecured.value
    with localcontext(_CTX):
        return (
            pr.key_rate.value
            + pr.spread.value
            + pd * lgd
            + policy.product_config(product.value).expense_rate
            + pr.capital_charge.value
        )


def corridor(policy: Policy, product: Product) -> tuple[Decimal, Decimal]:
    base = policy.product_config(product.value).base_rate
    width = policy.catalog.rate_corridor.value
    return base - width, base + width


def rate_for(policy: Policy, product: Product, grade: Grade, collateral: bool) -> RateBreakdown:
    pr = policy.pricing
    cfg = policy.product_config(product.value)
    pd = policy.grade_row(grade.value).pd
    lgd = pr.lgd_secured.value if collateral else pr.lgd_unsecured.value
    raw = raw_rate(policy, product, grade, collateral)
    rounded = _round_to_step(raw, pr.rounding_step.value)
    low, high = corridor(policy, product)
    rate = min(max(rounded, low), high)
    hint: Decimal | None = None
    if not collateral:
        with_collateral = raw_rate(policy, product, grade, True)
        hint_rate = min(max(_round_to_step(with_collateral, pr.rounding_step.value), low), high)
        hint = hint_rate if hint_rate < rate else None
    with localcontext(_CTX):
        expected_loss = pd * lgd
    return RateBreakdown(
        key_rate=pr.key_rate.value,
        spread=pr.spread.value,
        expected_loss=expected_loss,
        expenses=cfg.expense_rate,
        capital_charge=pr.capital_charge.value,
        raw_rate=raw,
        rate=rate,
        lgd=lgd,
        pd=pd,
        corridor_min=low,
        corridor_max=high,
        rate_with_collateral=hint,
    )
