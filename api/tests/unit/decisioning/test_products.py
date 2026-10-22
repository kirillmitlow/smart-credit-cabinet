"""Правила продукта одной функцией для мастера и ядра (T-294, D-018, 10-06, 30-07, 30-11)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app.modules.decisioning import check_product, decide
from app.modules.decisioning.products import ProductContext, authority_level, auto_limit
from app.modules.decisioning.types import ContractInfo, Grade, Level, Product, ReasonKind
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

POLICY = cp.load_policy()
TODAY = date(2026, 10, 21)
CONTRACT = ContractInfo("N1", 12_000_000, 0, "IN_PROGRESS", date(2027, 1, 15))


def ctx(**changes: object) -> ProductContext:
    base = ProductContext(
        app_today=TODAY,
        business_age_months=60,
        registration_date=date(2021, 10, 21),
        is_bank_customer=True,
        customer_turnover_months=12,
        collateral_provided=True,
        security_confirmed=True,
        grade=Grade.A,
        contract=CONTRACT,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def codes(product: Product, amount: int, term: int, **changes: object) -> list[str]:
    return [r.code for r in check_product(POLICY, product, amount, term, ctx(**changes))]


VALID = {
    Product.EXPRESS: (1_000_000, 12),
    Product.WORKING_CAPITAL: (5_000_000, 12),
    Product.CONTRACT: (8_000_000, 4),
    Product.CREDIT_LINE: (5_000_000, 12),
    Product.OVERDRAFT: (200_000, 12),
    Product.INVESTMENT: (10_000_000, 36),
}


@pytest.mark.parametrize("product", list(Product))
def test_valid_request_passes_for_every_product(product: Product) -> None:
    amount, term = VALID[product]
    assert codes(product, amount, term) == []


# Допустимость грейдов (30-07): «Нет» → GRADE_NOT_ALLOWED
NOT_ALLOWED = {
    Product.EXPRESS: {"E"},
    Product.WORKING_CAPITAL: {"E"},
    Product.CONTRACT: {"D", "E"},
    Product.CREDIT_LINE: {"D", "E"},
    Product.OVERDRAFT: {"C", "D", "E"},
    Product.INVESTMENT: {"E"},
}


@pytest.mark.parametrize("product", list(Product))
@pytest.mark.parametrize("grade", list(Grade))
def test_product_grade_matrix_matches_30_07(product: Product, grade: Grade) -> None:
    amount, term = VALID[product]
    amount = min(amount, POLICY.product_config(product.value).amount_max_rub // 2)
    found = "GRADE_NOT_ALLOWED" in codes(product, amount, term, grade=grade)
    assert found is (grade.value in NOT_ALLOWED[product])


def test_grade_d_needs_security_and_at_most_half_of_maximum() -> None:
    assert codes(Product.EXPRESS, 1_500_000, 12, grade=Grade.D) == []
    assert codes(Product.EXPRESS, 1_500_001, 12, grade=Grade.D) == [
        "GRADE_NOT_ALLOWED"
    ]  # > 50% максимума
    assert codes(Product.EXPRESS, 1_000_000, 12, grade=Grade.D, security_confirmed=False) == [
        "GRADE_NOT_ALLOWED"
    ]
    # оборотный: только с залогом (поручительства мало), сумма ≤ 50% максимума
    assert codes(Product.WORKING_CAPITAL, 5_000_000, 12, grade=Grade.D) == []
    assert codes(
        Product.WORKING_CAPITAL, 5_000_000, 12, grade=Grade.D, collateral_provided=False
    ) == ["GRADE_NOT_ALLOWED"]
    assert codes(Product.WORKING_CAPITAL, 15_000_001, 12, grade=Grade.D) == ["GRADE_NOT_ALLOWED"]


def test_amount_and_term_boundaries() -> None:
    assert codes(Product.EXPRESS, 99_999, 12) == ["AMOUNT_OUT_OF_RANGE"]
    assert codes(Product.EXPRESS, 100_000, 12) == []
    assert codes(Product.EXPRESS, 3_000_000, 36) == []
    assert codes(Product.EXPRESS, 3_000_001, 12) == ["AMOUNT_OUT_OF_RANGE"]
    assert codes(Product.EXPRESS, 500_000, 5) == ["AMOUNT_OUT_OF_RANGE"]
    assert codes(Product.EXPRESS, 500_000, 37) == ["AMOUNT_OUT_OF_RANGE"]
    # оборотный: срок 3–36 мес. (D-084)
    assert codes(Product.WORKING_CAPITAL, 1_000_000, 3) == []
    assert codes(Product.WORKING_CAPITAL, 1_000_000, 36) == []
    assert codes(Product.WORKING_CAPITAL, 1_000_000, 2) == ["AMOUNT_OUT_OF_RANGE"]
    assert codes(Product.WORKING_CAPITAL, 499_999, 12) == ["AMOUNT_OUT_OF_RANGE"]


def test_business_age_minimum_and_when_it_becomes_available() -> None:
    assert codes(Product.WORKING_CAPITAL, 1_000_000, 12, business_age_months=11) == [
        "PRODUCT_AGE_MIN"
    ]
    assert codes(Product.WORKING_CAPITAL, 1_000_000, 12, business_age_months=12) == []
    reason = check_product(
        POLICY,
        Product.CREDIT_LINE,
        5_000_000,
        12,
        ctx(business_age_months=23, registration_date=date(2024, 12, 5)),
    )[0]
    assert reason.params["available_from"] == "2026-12-05"  # «что станет доступно и когда»
    assert codes(Product.CREDIT_LINE, 5_000_000, 12, business_age_months=None) == []


def test_young_business_keeps_express_but_not_the_other_products() -> None:
    """D-077: молодому бизнесу экспресс доступен (только с обеспечением), оборотный — нет."""
    assert codes(Product.EXPRESS, 1_000_000, 12, business_age_months=3) == []
    assert codes(Product.WORKING_CAPITAL, 1_000_000, 12, business_age_months=3) == [
        "PRODUCT_AGE_MIN"
    ]


def test_overdraft_needs_our_client_with_six_months_of_turnover() -> None:
    assert codes(Product.OVERDRAFT, 200_000, 12, is_bank_customer=False) == ["NOT_BANK_CLIENT"]
    assert codes(Product.OVERDRAFT, 200_000, 12, customer_turnover_months=5) == ["NOT_BANK_CLIENT"]
    assert codes(Product.OVERDRAFT, 200_000, 12, customer_turnover_months=6) == []


@pytest.mark.parametrize(
    ("product", "amount", "term", "needs"),
    [
        (Product.WORKING_CAPITAL, 10_000_000, 12, False),  # ровно порог
        (Product.WORKING_CAPITAL, 10_000_001, 12, True),
        (Product.CREDIT_LINE, 15_000_000, 12, False),
        (Product.CREDIT_LINE, 15_000_001, 12, True),
        (Product.INVESTMENT, 1_000_000, 12, True),  # залог обязателен всегда
        (Product.EXPRESS, 3_000_000, 12, False),
    ],
)
def test_collateral_required_above_threshold(
    product: Product, amount: int, term: int, needs: bool
) -> None:
    assert (
        "COLLATERAL_REQUIRED" in codes(product, amount, term, collateral_provided=False)
    ) is needs
    assert "COLLATERAL_REQUIRED" not in codes(product, amount, term, collateral_provided=True)


def test_contract_validity() -> None:
    assert codes(Product.CONTRACT, 8_000_000, 4, contract=None) == ["CONTRACT_INVALID"]
    for broken in (
        replace(CONTRACT, status="EXECUTED"),
        replace(CONTRACT, status="TERMINATED"),
        replace(CONTRACT, payment_deadline=date(2026, 10, 20)),
        replace(CONTRACT, paid_rub=12_000_000),
    ):
        assert codes(Product.CONTRACT, 8_000_000, 4, contract=broken) == ["CONTRACT_INVALID"]
    # срок = оплата через 3 мес. + 1 мес.
    assert codes(Product.CONTRACT, 8_000_000, 4) == []
    reason = check_product(POLICY, Product.CONTRACT, 8_000_000, 5, ctx())[0]
    assert reason.code == "CONTRACT_INVALID"
    assert "срок" in str(reason.params["reason_text"])
    assert (
        codes(
            Product.CONTRACT,
            8_000_000,
            12,
            contract=replace(CONTRACT, payment_deadline=date(2027, 10, 21)),
        )
        == []
    )


def test_violations_are_collected_not_first_only() -> None:
    found = codes(
        Product.OVERDRAFT, 99, 12, grade=Grade.E, is_bank_customer=False, business_age_months=1
    )
    assert set(found) == {"AMOUNT_OUT_OF_RANGE", "NOT_BANK_CLIENT", "GRADE_NOT_ALLOWED"}
    assert all(
        r.kind == ReasonKind.PRODUCT
        for r in check_product(
            POLICY, Product.OVERDRAFT, 99, 12, ctx(grade=Grade.E, is_bank_customer=False)
        )
    )


# ---------------------------------------------------------------- авто-лимиты и полномочия


@pytest.mark.parametrize(
    ("product", "grade", "expected"),
    [
        (Product.EXPRESS, Grade.B, 3_000_000),
        (Product.EXPRESS, Grade.A, 3_000_000),  # не выше максимума продукта
        (Product.WORKING_CAPITAL, Grade.B, 5_000_000),
        (Product.WORKING_CAPITAL, Grade.A, 10_000_000),
        (Product.CONTRACT, Grade.B, 10_000_000),
        (Product.CONTRACT, Grade.A, 20_000_000),
        (Product.CREDIT_LINE, Grade.B, 5_000_000),
        (Product.CREDIT_LINE, Grade.A, 10_000_000),
        (Product.OVERDRAFT, Grade.A, None),  # без предела: ограничен 30% поступлений
        (Product.INVESTMENT, Grade.A, 0),  # всегда вручную
        (Product.INVESTMENT, Grade.B, 0),
        (Product.WORKING_CAPITAL, Grade.C, 0),  # у C и D автомата нет
    ],
)
def test_auto_limits(product: Product, grade: Grade, expected: int | None) -> None:
    assert auto_limit(POLICY, product, grade) == expected


@pytest.mark.parametrize(
    ("amount", "grade", "expected"),
    [
        (3_000_000, Grade.A, Level.L1), (3_000_000, Grade.D, Level.L1),
        (3_000_001, Grade.C, Level.L1), (3_000_001, Grade.D, Level.L2),
        (15_000_000, Grade.A, Level.L1), (15_000_000, Grade.B, Level.L1), (15_000_000, Grade.C, Level.L1),
        (15_000_000, Grade.D, Level.L2), (15_000_001, Grade.A, Level.L2), (20_000_000, Grade.A, Level.L2),
        (50_000_000, Grade.C, Level.L2), (60_000_000, Grade.A, Level.L2), (1_000_000, Grade.E, Level.L1),
    ],
)  # fmt: skip
def test_authority_matrix(amount: int, grade: Grade, expected: Level) -> None:
    assert authority_level(POLICY, amount, grade) == expected


# ---------------------------------------------------------------- согласованность мастера и ядра


@pytest.mark.parametrize(
    "name", ["sokolova", "snabkontrakt", "stankoprom", "zarya", "quick-start", "t-young-collateral"]
)
def test_wizard_and_core_agree_on_product_rules(name: str) -> None:
    """Те же аргументы в `check_product` (как у мастера) дают те же нарушения, что и в `decide()`."""
    inp = cp.PERSONAS[name]()
    result = decide(inp)
    f = result.features
    assert f is not None
    assert result.numbers.grade is not None
    wizard_ctx = ProductContext(
        app_today=inp.context.app_today,
        business_age_months=f.business_age_months,
        registration_date=inp.snapshot.registry.registration_date,
        is_bank_customer=f.is_bank_customer,
        customer_turnover_months=len(inp.snapshot.turnover.months),
        collateral_provided=f.collateral_provided,
        security_confirmed=f.security_confirmed,
        grade=result.numbers.grade,
        contract=next(iter(inp.snapshot.contracts.contracts), None)
        if inp.application.product == Product.CONTRACT
        else None,
    )
    app = inp.application
    wizard = {
        r.code
        for r in check_product(POLICY, app.product, app.amount_rub, app.term_months, wizard_ctx)
    }
    core = {r.code for r in result.reasons if r.kind == ReasonKind.PRODUCT}
    assert wizard == core


def test_new_limits_are_config_not_code() -> None:
    cfg = POLICY.product_config("EXPRESS").model_copy(update={"amount_max_rub": 2_000_000})
    policy = POLICY.model_copy(
        update={
            "catalog": POLICY.catalog.model_copy(
                update={"products": {**POLICY.catalog.products, "EXPRESS": cfg}}
            )
        }
    )
    assert [r.code for r in check_product(policy, Product.EXPRESS, 2_500_000, 12, ctx())] == [
        "AMOUNT_OUT_OF_RANGE"
    ]
    assert check_product(POLICY, Product.EXPRESS, 2_500_000, 12, ctx()) == ()
