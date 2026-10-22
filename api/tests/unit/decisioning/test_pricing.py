"""Ставка по ожидаемым потерям (T-292, 30-09): таблица ставок, коридор, монотонность."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.decisioning import decide, pricing
from app.modules.decisioning.types import Grade, Product
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal
POLICY = cp.load_policy()


@pytest.mark.parametrize(
    ("product", "grade", "collateral", "expected"),
    [
        # экспресс: A 21,5 / B 22,5 / C 24,0 (30-17)
        (Product.EXPRESS, Grade.A, False, "0.215"),
        (Product.EXPRESS, Grade.B, False, "0.225"),
        (Product.EXPRESS, Grade.C, False, "0.240"),
        # остальные продукты: A 19,5 / B 20,5 / C 22,0
        (Product.WORKING_CAPITAL, Grade.A, False, "0.195"),
        (Product.WORKING_CAPITAL, Grade.B, False, "0.205"),
        (Product.WORKING_CAPITAL, Grade.C, False, "0.220"),
        (Product.CREDIT_LINE, Grade.A, False, "0.195"),
        (Product.INVESTMENT, Grade.A, False, "0.195"),
        # с залогом: A 21,5 / 19,5, C 23,5 / 21,5
        (Product.EXPRESS, Grade.A, True, "0.215"),
        (Product.EXPRESS, Grade.C, True, "0.235"),
        (Product.WORKING_CAPITAL, Grade.A, True, "0.195"),
        (Product.WORKING_CAPITAL, Grade.C, True, "0.215"),
    ],
)
def test_rate_table_from_30_17(
    product: Product, grade: Grade, collateral: bool, expected: str
) -> None:
    assert pricing.rate_for(POLICY, product, grade, collateral).rate == D(expected)


@pytest.mark.parametrize(
    ("grade", "raw", "rounded"),
    [(Grade.A, "0.1945", "0.195"), (Grade.B, "0.2235", "0.225"), (Grade.C, "0.2415", "0.240")],
)
def test_raw_rate_and_rounding_to_half_percentage_point(
    grade: Grade, raw: str, rounded: str
) -> None:
    """Сырые 19,45 → 19,5; 22,35 → 22,5; 24,15 → 24,0 (ближайшие 0,5 п.п.)."""
    product = Product.WORKING_CAPITAL if grade == Grade.A else Product.EXPRESS
    if grade == Grade.A:
        assert pricing.raw_rate(POLICY, product, grade, False) == D(raw)
    else:
        assert pricing.raw_rate(POLICY, product, grade, False) == D(raw)
    assert pricing.rate_for(POLICY, product, grade, False).rate == D(rounded)


def test_rounding_is_half_up_on_the_exact_midpoint() -> None:
    assert pricing._round_to_step(D("0.2175"), D("0.005")) == D("0.220")  # ровно середина → вверх
    assert pricing._round_to_step(D("0.2174"), D("0.005")) == D("0.215")


def test_breakdown_adds_up() -> None:
    bd = pricing.rate_for(POLICY, Product.EXPRESS, Grade.B, False)
    assert (
        bd.key_rate + bd.spread + bd.expected_loss + bd.expenses + bd.capital_charge == bd.raw_rate
    )
    assert (bd.pd, bd.lgd, bd.expected_loss) == (D("0.03"), D("0.45"), D("0.0135"))
    assert bd.expenses == D("0.04")  # у экспресса расходы выше на 2 п.п.


def test_collateral_hint_is_given_only_when_it_helps() -> None:
    helps = pricing.rate_for(POLICY, Product.WORKING_CAPITAL, Grade.C, False)
    assert helps.rate_with_collateral == D("0.215")  # вместо 22,0%
    same = pricing.rate_for(POLICY, Product.WORKING_CAPITAL, Grade.A, False)
    assert same.rate_with_collateral is None  # 19,5% и так
    assert (
        pricing.rate_for(POLICY, Product.WORKING_CAPITAL, Grade.C, True).rate_with_collateral
        is None
    )


def test_guarantor_does_not_lower_lgd_and_amount_does_not_matter() -> None:
    without = decide(cp.quick_start()).numbers.rate
    with_guarantor = decide(cp.quick_start(with_guarantor=True)).numbers.rate
    assert without == with_guarantor == D("0.240")
    small = cp.with_application(cp.t_base(), amount_rub=200_000)
    big = cp.with_application(cp.t_base(), amount_rub=3_000_000)
    assert decide(small).numbers.rate == decide(big).numbers.rate  # D-084: ставка до лимитов


def test_rate_is_clamped_to_product_corridor() -> None:
    """Овердрафт: формула даёт 19,5% для A, коридор 21–29% поднимает до 21%."""
    bd = pricing.rate_for(POLICY, Product.OVERDRAFT, Grade.A, False)
    assert bd.raw_rate < bd.corridor_min
    assert bd.rate == bd.corridor_min == D("0.21")
    d = pricing.rate_for(POLICY, Product.INVESTMENT, Grade.E, False)
    assert d.corridor_min <= d.rate <= d.corridor_max


def test_rate_never_rises_with_collateral_and_never_falls_with_worse_grade_inv_05_06() -> None:
    for product in Product:
        rates = []
        for grade in Grade:
            plain = pricing.rate_for(POLICY, product, grade, False)
            secured = pricing.rate_for(POLICY, product, grade, True)
            assert secured.rate <= plain.rate
            assert plain.corridor_min <= plain.rate <= plain.corridor_max
            rates.append(plain.rate)
        assert rates == sorted(rates)
