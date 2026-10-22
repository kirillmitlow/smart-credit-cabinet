"""«Ставка от X%» — честная нижняя граница (D-018): не выше ставки ни одного доступного грейда."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.decisioning import Grade, Product, lowest_rate
from app.modules.decisioning.policy import GradeAccess
from app.modules.decisioning.pricing import rate_for
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("product", list(Product))
def test_lowest_rate_is_not_above_any_reachable_rate(product: Product) -> None:
    policy = cp.load_policy()
    low = lowest_rate(policy, product)
    access = policy.product_config(product.value).grade_access
    reachable = [
        rate_for(policy, product, grade, collateral).rate
        for grade in Grade
        if access[grade.value] is not GradeAccess.NO
        for collateral in (False, True)
    ]
    assert low == min(reachable)


def test_sokolova_rate_is_not_below_express_rate_from() -> None:
    # Оракул 30-17: Соколова, EXPRESS, грейд A — 21,5% при базе продукта 24%
    assert lowest_rate(cp.load_policy(), Product.EXPRESS) <= Decimal("0.215")
