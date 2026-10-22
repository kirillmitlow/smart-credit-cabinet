"""T-241: калькулятор платежа на числах 30-16 и границы продукта."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.catalog.calculator import calculate, effective_rate_percent
from app.modules.catalog.schemas import PaymentKind
from app.shared.errors import AppError
from tests.fixtures.core_personas import load_policy

pytestmark = pytest.mark.unit


def test_sokolova_base_rate_vector_30_16_example_1() -> None:
    """Пример 1, тестовый вектор 24%: 47 280, последний 47 278, переплата 67 358."""
    result = calculate(load_policy(), "EXPRESS", 500_000, 12, None)
    assert (result.payment_rub, result.last_payment_rub) == (47_280, 47_278)
    assert (result.total_payment_rub, result.overpayment_rub) == (567_358, 67_358)
    assert result.payment_kind is PaymentKind.ANNUITY
    assert result.rate_percent == Decimal("24")
    assert result.rate_percent_from == Decimal("24")
    assert result.approximate is True


def test_sokolova_offer_rate_matches_oracle_30_17() -> None:
    """Боевая ставка из оферты 21,5%: платёж 46 677, последний 46 679, переплата 60 126."""
    result = calculate(load_policy(), "EXPRESS", 500_000, 12, Decimal("21.5"))
    assert (result.payment_rub, result.last_payment_rub, result.overpayment_rub) == (
        46_677,
        46_679,
        60_126,
    )
    assert result.approximate is False


def test_snabkontrakt_vectors_30_16_example_2() -> None:
    policy = load_policy()
    twelve = calculate(policy, "WORKING_CAPITAL", 8_000_000, 12, None)
    assert (twelve.payment_rub, twelve.last_payment_rub, twelve.overpayment_rub) == (
        744_910,
        744_913,
        938_923,
    )
    thirty_six = calculate(policy, "WORKING_CAPITAL", 8_000_000, 36, None)
    assert (thirty_six.payment_rub, thirty_six.last_payment_rub) == (301_401, 301_374)
    assert thirty_six.overpayment_rub == 2_850_409
    boevaya = calculate(policy, "WORKING_CAPITAL", 8_000_000, 12, Decimal("19.5"))
    assert boevaya.payment_rub == 739_163


def test_garipov_vector_30_16_example_3() -> None:
    result = calculate(load_policy(), "EXPRESS", 1_500_000, 36, None)
    assert (result.payment_rub, result.last_payment_rub, result.overpayment_rub) == (
        58_849,
        58_866,
        618_581,
    )


def test_contract_pays_interest_only_30_16_example_4() -> None:
    """Под контракт — проценты ежемесячно, долг в конце; 20%: 133 333 в месяц, 8 133 333 в конце."""
    result = calculate(load_policy(), "CONTRACT", 8_000_000, 4, None)
    assert result.payment_kind is PaymentKind.INTEREST_ONLY
    assert result.payment_rub == 133_333
    assert result.last_payment_rub == 8_133_333
    assert result.overpayment_rub == 533_332
    assert result.total_payment_rub == 8_533_332


def test_credit_line_shows_interest_on_the_whole_limit() -> None:
    result = calculate(load_policy(), "CREDIT_LINE", 5_000_000, 12, None)
    assert result.payment_kind is PaymentKind.INTEREST_ONLY
    assert result.payment_rub == 83_333  # 5 000 000 · 0,20 / 12
    assert result.overpayment_rub == 83_333 * 12


def test_effective_rate_exceeds_nominal() -> None:
    assert effective_rate_percent(Decimal("0.24")) == Decimal("26.82")
    assert effective_rate_percent(Decimal("0")) == Decimal("0.00")


@pytest.mark.parametrize(
    ("code", "amount", "term", "fields"),
    [
        ("EXPRESS", 99_999, 12, {"amountRub"}),
        ("EXPRESS", 3_000_001, 12, {"amountRub"}),
        ("EXPRESS", 500_000, 5, {"termMonths"}),
        ("EXPRESS", 500_000, 37, {"termMonths"}),
        ("WORKING_CAPITAL", 400_000, 2, {"amountRub", "termMonths"}),
        ("OVERDRAFT", 100_000, 6, {"termMonths"}),
    ],
)
def test_out_of_bounds_is_validation_error_with_field_path(
    code: str, amount: int, term: int, fields: set[str]
) -> None:
    with pytest.raises(AppError) as caught:
        calculate(load_policy(), code, amount, term, None)
    assert caught.value.status == 422
    assert caught.value.code == "VALIDATION_ERROR"
    assert caught.value.errors is not None
    assert {e["loc"][1] for e in caught.value.errors} == fields


def test_bounds_are_inclusive() -> None:
    policy = load_policy()
    calculate(policy, "EXPRESS", 100_000, 6, None)
    calculate(policy, "EXPRESS", 3_000_000, 36, None)


@pytest.mark.parametrize("rate", ["19.99", "28.01"])
def test_rate_outside_corridor_is_rejected(rate: str) -> None:
    with pytest.raises(AppError) as caught:
        calculate(load_policy(), "EXPRESS", 500_000, 12, Decimal(rate))
    assert caught.value.errors is not None
    assert caught.value.errors[0]["loc"] == ["body", "ratePercent"]


def test_money_is_integer_rubles() -> None:
    result = calculate(load_policy(), "EXPRESS", 777_777, 17, None)
    for value in (
        result.payment_rub,
        result.last_payment_rub,
        result.total_payment_rub,
        result.overpayment_rub,
    ):
        assert type(value) is int
