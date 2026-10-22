"""Встречные предложения: ЗАГЛУШКА оптимизатора (T-297 не в этой задаче) и условное встречное.

Что здесь готово:
  * `conditional_security_variant` — «тот же запрос с обеспечением» для молодого бизнеса
    (30-04, D-077): одна карточка, считается сразу, оптимизатор не нужен;
  * `search_counter_offers` — только ответ на вопрос «есть ли вообще хоть один проходящий
    вариант» (минимальная сумма на максимальный срок, 30-11 строка 5), чтобы маршрут мог
    отличить `COUNTER_OFFER` от `NO_OFFER_FOUND`. Карточек он НЕ строит: `variants` пуст,
    `status == "PLACEHOLDER_T297"`.

TODO(T-297): перебор сетки продуктов × сроков × сумм с залогом и без, расстояние до запроса
с весами из `policy.counter_offers.weights`, три карточки и «рекомендуем» (30-10, вариант Г).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.affordability import Affordability, meets_counter_thresholds
from app.modules.decisioning.policy import Policy
from app.modules.decisioning.types import Application, Features, ParamValue, Product, Variant

PLACEHOLDER_STATUS = "PLACEHOLDER_T297"


@dataclass(frozen=True, slots=True)
class CounterOfferSearch:
    status: str
    variants: tuple[Variant, ...]
    feasible: bool
    probe: dict[str, ParamValue]


def _debt_ratio(feats: Features, amount: int) -> Decimal | None:
    if not feats.revenue_annual_rub:
        return None
    return Decimal(feats.total_debt_rub + amount) / Decimal(feats.revenue_annual_rub)


def search_counter_offers(
    policy: Policy,
    app: Application,
    rate: Decimal,
    feats: Features,
    max_overdraft_rub: int | None = None,
) -> CounterOfferSearch:
    """Заглушка T-297: есть ли хотя бы одно проходящее условие у продукта запроса."""
    cfg = policy.product_config(app.product.value)
    step = policy.counter_offers.amount_step_rub.value
    flow = feats.flow_model_rub or 0
    existing = feats.existing_payments_rub
    amount = max(step, cfg.amount_min_rub)
    amount = ((amount + step - 1) // step) * step
    grid = [
        t
        for t in policy.counter_offers.term_grid_months.value
        if cfg.term_min_months <= t <= cfg.term_max_months
    ]
    term = max(grid) if grid else cfg.term_max_months
    if app.product == Product.OVERDRAFT:
        feasible = max_overdraft_rub is not None and max_overdraft_rub >= cfg.amount_min_rub
        payment = 0
    else:
        payment = lm.payment_for(cfg.repayment.value, amount, rate, term)
        feasible = meets_counter_thresholds(
            policy, flow, existing, payment, feats.stress_shock, _debt_ratio(feats, amount)
        )
    return CounterOfferSearch(
        status=PLACEHOLDER_STATUS,
        variants=(),
        feasible=feasible,
        probe={"amount_rub": amount, "term_months": term, "payment_rub": payment},
    )


def conditional_security_variant(app: Application, rate: Decimal, afford: Affordability) -> Variant:
    """«Тот же запрос с поручительством владельца или залогом» (молодой бизнес без обеспечения)."""
    return Variant(
        kind="CONDITIONAL_SECURITY",
        product=app.product,
        amount_rub=app.amount_rub,
        term_months=app.term_months,
        rate=rate,
        payment_rub=afford.payment_rub,
        dscr=afford.dscr if afford.dscr is not None else Decimal(0),
        stress_dscr=afford.stress_dscr if afford.stress_dscr is not None else Decimal(0),
        security_required=True,
        recommended=True,
        note="тот же запрос с поручительством владельца или залогом",
    )
