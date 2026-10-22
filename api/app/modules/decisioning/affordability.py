"""Лимиты: DSCR, стресс, потолок долга, особые лимиты продукта, обратная задача (T-293, 30-08).

Шаги 9 и 10 независимы: собираются все нарушения, а не первое (30-01). Сравнения идут по точным
`Decimal`, показанные в результате числа округлены уже после проверки.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.policy import Policy
from app.modules.decisioning.reasons import make
from app.modules.decisioning.types import (
    Application,
    ContractInfo,
    Features,
    Product,
    ReasonCode,
)

_Q6 = Decimal("0.000001")


def q6(value: Decimal) -> Decimal:
    return value.quantize(_Q6)


@dataclass(frozen=True, slots=True)
class Affordability:
    payment_rub: int
    last_payment_rub: int | None
    overpayment_rub: int | None
    dscr: Decimal | None  # овердрафт: платежа по графику нет
    stress_dscr: Decimal | None
    shock: Decimal
    debt_ratio_with_new: Decimal | None
    p_max_rub: int
    max_amount_formula_rub: int
    max_amount_rub: int
    max_amount_by_term: tuple[tuple[int, int], ...]
    min_term_months: int | None
    violations: tuple[ReasonCode, ...]  # DSCR_LOW, STRESS_DSCR_LOW, DEBT_TOO_HIGH, LIMIT_ABOVE_CAP
    near_threshold: tuple[ReasonCode, ...]  # серые зоны (NEAR_THRESHOLD)

    @property
    def passes(self) -> bool:
        return not self.violations


def schedule_numbers(
    repayment: str, amount: int, rate: Decimal, term: int
) -> tuple[int, int | None, int | None]:
    """(платёж для DSCR, последний платёж, переплата)."""
    payment = lm.payment_for(repayment, amount, rate, term)
    if repayment == "ANNUITY":
        rows = lm.build_schedule(amount, rate, term)
        return payment, rows[-1].payment, lm.overpayment(rows, amount)
    if repayment == "BULLET":
        rows = lm.bullet_schedule(amount, rate, term)
        return payment, rows[-1].payment, lm.overpayment(rows, amount)
    if repayment == "LINE":
        return payment, None, payment * term
    return payment, None, None


def product_cap(
    policy: Policy,
    product: Product,
    feats: Features,
    app: Application,
    contract: ContractInfo | None,
    inflow_average: int | None,
) -> tuple[str, int] | None:
    """Особый предел продукта: (правило, максимум рублей) или `None`, если предела нет."""
    aff = policy.affordability
    if product == Product.CREDIT_LINE and feats.revenue_cautious_rub is not None:
        cap = lm.floor_rub(
            Decimal(feats.revenue_cautious_rub) * aff.line_share_of_monthly_revenue.value
        )
        return "LINE_HALF_OF_MONTHLY_REVENUE", cap
    if product == Product.OVERDRAFT and inflow_average is not None:
        cap = lm.floor_rub(Decimal(inflow_average) * aff.overdraft_share_of_inflows.value)
        return "OVERDRAFT_30_PERCENT_OF_INFLOWS", cap
    if product == Product.CONTRACT and contract is not None:
        unpaid = max(contract.price_rub - contract.paid_rub, 0)
        cap = lm.floor_rub(Decimal(unpaid) * aff.contract_share_of_unpaid.value)
        return "CONTRACT_80_PERCENT_OF_UNPAID", cap
    if product == Product.INVESTMENT and app.collateral is not None:
        cap = lm.floor_rub(
            Decimal(app.collateral.value_rub) * aff.investment_share_of_collateral.value
        )
        return "INVESTMENT_70_PERCENT_OF_COLLATERAL", cap
    return None


def term_options(policy: Policy, product: Product, requested_term: int) -> list[int]:
    cfg = policy.product_config(product.value)
    grid = [
        t
        for t in policy.counter_offers.term_grid_months.value
        if cfg.term_min_months <= t <= cfg.term_max_months
    ]
    return sorted({*grid, requested_term})


def evaluate(  # noqa: PLR0913, PLR0914 — один расчёт шагов 9–10 с общими входами
    policy: Policy,
    product: Product,
    amount: int,
    term: int,
    rate: Decimal,
    feats: Features,
    app: Application,
    contract: ContractInfo | None,
    inflow_average: int | None,
    p_def12: Decimal | None,
) -> Affordability:
    aff = policy.affordability
    cfg = policy.product_config(product.value)
    repayment = cfg.repayment.value
    flow = feats.flow_model_rub or 0
    existing = feats.existing_payments_rub
    shock = feats.stress_shock

    payment, last, over = schedule_numbers(repayment, amount, rate, term)
    has_payment = payment > 0
    d = lm.dscr(flow, existing, payment) if has_payment else None
    s = lm.stress_dscr(flow, existing, payment, shock) if has_payment else None

    annual = feats.revenue_annual_rub
    debt_ratio: Decimal | None = None
    if annual:
        debt_ratio = Decimal(feats.total_debt_rub + amount) / Decimal(annual)

    p_max_exact = lm.max_payment(flow, existing, aff.dscr_min.value)
    p_max = max(lm.floor_rub(p_max_exact), 0) if p_max_exact > 0 else 0
    formula = lm.max_amount_formula(p_max_exact, rate, term, repayment)

    def max_for_term(n: int) -> tuple[int, int]:
        if p_max_exact <= 0 or repayment == "OVERDRAFT":
            return 0, 0
        hint = lm.max_amount_formula(p_max_exact, rate, n, repayment)

        def ok(amount_try: int) -> bool:
            pay = lm.payment_for(repayment, amount_try, rate, n)
            return pay <= 0 or lm.dscr(flow, existing, pay) >= aff.dscr_min.value

        step = aff.amount_step_rub.value
        return hint, lm.largest_step_amount(ok, hint, step, cap=cfg.amount_max_rub)

    max_formula, max_stepped = max_for_term(term)
    by_term: tuple[tuple[int, int], ...] = ()
    if repayment == "ANNUITY":
        by_term = tuple((t, max_for_term(t)[1]) for t in term_options(policy, product, term))
    min_t = lm.min_term(amount, rate, p_max_exact) if repayment == "ANNUITY" else None

    violations: list[ReasonCode] = []
    near: list[ReasonCode] = []

    safe_payment = max(p_max, 0)
    if d is not None and s is not None:
        if d < aff.dscr_min.value:
            violations.append(
                make(
                    "DSCR_LOW",
                    payment_rub=payment,
                    safe_payment_rub=safe_payment,
                    flow_rub=flow,
                    existing_rub=existing,
                    dscr=q6(d),
                    threshold=aff.dscr_min.value,
                )
            )
        elif s < aff.stress_dscr_min.value:
            violations.append(
                make(
                    "STRESS_DSCR_LOW",
                    shock=shock,
                    stress_dscr=q6(s),
                    threshold=aff.stress_dscr_min.value,
                )
            )
    if debt_ratio is not None and debt_ratio > aff.debt_to_revenue_max.value:
        max_debt_new = lm.floor_rub(
            Decimal(annual or 0) * aff.debt_to_revenue_max.value - Decimal(feats.total_debt_rub)
        )
        violations.append(
            make(
                "DEBT_TOO_HIGH",
                debt_rub=feats.total_debt_rub,
                new_rub=amount,
                share=q6(debt_ratio),
                revenue_rub=annual,
                max_new_rub=max(max_debt_new, 0),
            )
        )
    cap = product_cap(policy, product, feats, app, contract, inflow_average)
    if cap is not None and amount > cap[1]:
        violations.append(
            make("LIMIT_ABOVE_CAP", rule=cap[0], requested_rub=amount, cap_rub=cap[1])
        )
    if p_def12 is not None and p_def12 > aff.p_def12_red.value:
        violations.append(
            make(
                "STRESS_DSCR_LOW",
                source="P_DEF12",
                p_def12=p_def12,
                shock=shock,
                stress_dscr=q6(s) if s is not None else None,
                threshold=aff.p_def12_red.value,
            )
        )

    # Серые зоны (30-11) смотрим, только если жёстких нарушений нет
    if not violations:
        gray = policy.routing.gray
        if d is not None and aff.dscr_min.value <= d < gray.dscr_upto:
            near.append(_near("DSCR", q6(d), aff.dscr_min.value, gray.dscr_upto))
        if s is not None and aff.stress_dscr_min.value <= s < gray.stress_upto:
            near.append(_near("STRESS_DSCR", q6(s), aff.stress_dscr_min.value, gray.stress_upto))
        if debt_ratio is not None and gray.debt_from <= debt_ratio <= aff.debt_to_revenue_max.value:
            near.append(
                _near(
                    "DEBT_TO_REVENUE", q6(debt_ratio), gray.debt_from, aff.debt_to_revenue_max.value
                )
            )
        if p_def12 is not None and p_def12 > aff.p_def12_yellow.value:
            near.append(_near("P_DEF12", p_def12, aff.p_def12_yellow.value, aff.p_def12_red.value))

    return Affordability(
        payment_rub=payment,
        last_payment_rub=last,
        overpayment_rub=over,
        dscr=q6(d) if d is not None else None,
        stress_dscr=q6(s) if s is not None else None,
        shock=shock,
        debt_ratio_with_new=q6(debt_ratio) if debt_ratio is not None else None,
        p_max_rub=p_max,
        max_amount_formula_rub=formula,
        max_amount_rub=max_stepped,
        max_amount_by_term=by_term,
        min_term_months=min_t,
        violations=tuple(violations),
        near_threshold=tuple(near),
    )


def _near(metric: str, value: Decimal, low: Decimal, high: Decimal) -> ReasonCode:
    return make("NEAR_THRESHOLD", metric=metric, value=value, zone_from=low, zone_to=high)


def meets_counter_thresholds(
    policy: Policy,
    flow: int,
    existing: int,
    payment: int,
    shock: Decimal,
    debt_ratio: Decimal | None,
) -> bool:
    """Условия встречного (30-10): DSCR ≥ 1,30, стресс ≥ 1,05, долг к выручке < 0,95."""
    co = policy.counter_offers
    if payment <= 0:
        return False
    if lm.dscr(flow, existing, payment) < co.dscr_min.value:
        return False
    if lm.stress_dscr(flow, existing, payment, shock) < co.stress_dscr_min.value:
        return False
    return debt_ratio is None or debt_ratio < co.debt_to_revenue_below.value
