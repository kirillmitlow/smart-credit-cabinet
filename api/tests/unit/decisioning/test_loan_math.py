"""Кредитная математика (T-282, T-283): табличные тесты по примерам 1–10 из 30-16."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.dates import add_months, full_months_between, next_business_day

pytestmark = pytest.mark.unit

D = Decimal


# ---------------------------------------------------------------- аннуитет, примеры 1–3


def test_example_1_sokolova_vector_24_percent() -> None:
    rows = lm.build_schedule(500_000, D("0.24"), 12)
    assert rows[0].payment == 47_280
    assert (rows[0].interest, rows[0].principal, rows[0].balance) == (10_000, 37_280, 462_720)
    assert rows[5].balance == 264_833  # после 6-го платежа
    assert rows[-1].payment == 47_278
    assert rows[-1].balance == 0
    assert lm.overpayment(rows, 500_000) == 67_358
    assert sum(r.principal for r in rows) == 500_000


def test_example_1_sokolova_battle_rate() -> None:
    rows = lm.build_schedule(500_000, D("0.215"), 12)
    assert rows[0].payment == 46_677
    assert rows[-1].payment == 46_679
    assert lm.overpayment(rows, 500_000) == 60_126


@pytest.mark.parametrize(
    ("amount", "rate", "term", "payment", "last", "over"),
    [
        (8_000_000, "0.21", 12, 744_910, 744_913, 938_923),
        (8_000_000, "0.21", 36, 301_401, 301_374, 2_850_409),
        (8_000_000, "0.195", 12, 739_163, 739_163, 869_956),
        (8_000_000, "0.195", 36, 295_274, 295_295, 2_629_885),
        (1_500_000, "0.225", 36, 57_674, 57_700, 576_290),
        (1_500_000, "0.24", 36, 58_849, 58_866, 618_581),
    ],
)
def test_examples_2_and_3_snabkontrakt_and_garipov(
    amount: int, rate: str, term: int, payment: int, last: int, over: int
) -> None:
    rows = lm.build_schedule(amount, D(rate), term)
    assert lm.annuity_payment(amount, D(rate), term) == payment
    assert rows[-1].payment == last
    assert lm.overpayment(rows, amount) == over


@pytest.mark.parametrize(
    ("amount", "rate", "term", "payment"),
    [
        (8_000_000, "0.21", 24, 411_085),
        (8_000_000, "0.195", 24, 405_215),
        (1_000_000, "0.24", 24, 52_871),
        (15_000_000, "0.195", 60, 393_247),
        (1_000_000, "0.215", 12, 93_354),
        (3_000_000, "0.195", 12, 277_186),
    ],
)
def test_persona_payments(amount: int, rate: str, term: int, payment: int) -> None:
    assert lm.annuity_payment(amount, D(rate), term) == payment


def test_closed_formula_balance_matches_schedule_within_half_ruble_per_month() -> None:
    rows = lm.build_schedule(500_000, D("0.24"), 12)
    for k, row in enumerate(rows[:-1], start=1):
        exact = lm.balance_after(500_000, D("0.24"), 12, k)
        assert abs(exact - row.balance) <= D(k) / 2 + 1


def test_zero_rate_is_even_split() -> None:
    assert lm.annuity_payment(1_200_000, D(0), 12) == 100_000
    assert lm.balance_after(1_200_000, D(0), 12, 3) == D(900_000)
    assert lm.max_amount_formula(D(100_000), D(0), 12, "ANNUITY") == 1_200_000


def test_invalid_term_is_rejected() -> None:
    with pytest.raises(ValueError, match="срок"):
        lm.annuity_payment(1_000, D("0.2"), 0)


# ---------------------------------------------------------------- проценты в конце срока, линия, овердрафт


def test_example_4_contract_snabkontrakt() -> None:
    rows = lm.bullet_schedule(8_000_000, D("0.195"), 4)
    assert [r.payment for r in rows] == [130_000, 130_000, 130_000, 8_130_000]
    assert lm.overpayment(rows, 8_000_000) == 520_000
    assert lm.bullet_interest(8_000_000, D("0.20")) == 133_333  # тестовый вектор 20%
    assert lm.overpayment(lm.bullet_schedule(8_000_000, D("0.20"), 4), 8_000_000) == 533_332
    assert lm.bullet_schedule(8_000_000, D("0.20"), 4)[-1].payment == 8_133_333
    # покрытие контрактом: цена неоплаченной части 12 млн против суммы с процентами
    assert Decimal(12_000_000) / Decimal(8_533_332) > D("1.40")


def test_example_5_credit_line() -> None:
    assert lm.line_payment_on_limit(5_000_000, D("0.20")) == 83_333
    assert lm.line_interest_on_average_use(2_000_000, 3_000_000, D("0.20")) == 41_667
    assert lm.line_payment_on_limit(20_000_000, D("0.195")) == 325_000  # zarya


def test_example_6_overdraft_by_days() -> None:
    assert lm.overdraft_interest([200_000] * 10, D("0.25")) == 1_370
    assert lm.overdraft_interest([], D("0.25")) == 0


def test_bullet_payment_does_not_depend_on_term() -> None:
    """INV-23: платёж BULLET не зависит от срока, переплата растёт линейно."""
    p4 = lm.overpayment(lm.bullet_schedule(1_000_000, D("0.2"), 4), 1_000_000)
    p8 = lm.overpayment(lm.bullet_schedule(1_000_000, D("0.2"), 8), 1_000_000)
    assert p8 == 2 * p4
    assert lm.payment_for("BULLET", 1_000_000, D("0.2"), 4) == lm.payment_for(
        "BULLET", 1_000_000, D("0.2"), 9
    )


def test_payment_for_by_repayment_kind() -> None:
    assert lm.payment_for("ANNUITY", 500_000, D("0.215"), 12) == 46_677
    assert lm.payment_for("LINE", 5_000_000, D("0.20"), 12) == 83_333
    assert lm.payment_for("OVERDRAFT", 100_000, D("0.25"), 12) == 0
    with pytest.raises(ValueError, match="вид погашения"):
        lm.payment_for("MAGIC", 1, D("0.1"), 1)


# ---------------------------------------------------------------- DSCR и обратная задача (пример 7)


def test_dscr_and_stress_examples() -> None:
    assert lm.dscr(90_500, 3_000, 46_677).quantize(D("0.001")) == D("1.822")
    assert lm.stress_dscr(90_500, 3_000, 46_677, D("0.2")).quantize(D("0.001")) == D("1.457")
    assert lm.dscr(1_200_000, 600_000, 739_163).quantize(D("0.001")) == D("0.896")
    with pytest.raises(ValueError, match="положительной"):
        lm.dscr(100, 0, 0)
    with pytest.raises(ValueError, match="положительной"):
        lm.stress_dscr(100, 0, 0, D("0.2"))


@pytest.mark.parametrize(
    ("term", "formula", "stepped", "payment", "dscr_value"),
    [
        (12, 3_896_299, 3_850_000, 355_722, "1.256"),
        (24, 7_107_338, 7_100_000, 359_628, "1.250"),
        (36, 9_753_637, 9_750_000, 359_866, "1.250"),
    ],
)
def test_example_7_max_amount_for_snabkontrakt(
    term: int, formula: int, stepped: int, payment: int, dscr_value: str
) -> None:
    rate = D("0.195")
    p_max = lm.max_payment(1_200_000, 600_000, D("1.25"))
    assert p_max == 360_000
    assert abs(lm.max_amount_formula(p_max, rate, term, "ANNUITY") - formula) <= 1

    def ok(amount: int) -> bool:
        return lm.dscr(1_200_000, 600_000, lm.annuity_payment(amount, rate, term)) >= D("1.25")

    found = lm.largest_step_amount(ok, formula, 50_000)
    assert found == stepped
    assert lm.annuity_payment(found, rate, term) == payment
    assert lm.dscr(1_200_000, 600_000, payment).quantize(D("0.001")) == D(dscr_value)
    assert not ok(found + 50_000)  # INV-30: на шаг выше уже не проходит


def test_example_7_minimum_term_and_counter_threshold() -> None:
    rate = D("0.195")
    p_max = lm.max_payment(1_200_000, 600_000, D("1.25"))
    assert lm.min_term(8_000_000, rate, p_max) == 28
    assert lm.annuity_payment(8_000_000, rate, 27) == 368_397  # при 27 мес. не проходит
    threshold = lm.counter_threshold(D("1.30"), D("1.05"), D("0.20"))
    assert threshold == D("1.3125")
    p_counter = lm.max_payment(1_200_000, 600_000, threshold)
    assert abs(p_counter - D("314285.714285")) < 1
    assert lm.min_term(8_000_000, rate, p_counter) == 34
    for term, stepped in ((12, 3_400_000), (24, 6_200_000), (36, 8_500_000)):
        hint = lm.max_amount_formula(p_counter, rate, term, "ANNUITY")

        def ok(amount: int, term: int = term) -> bool:
            pay = lm.annuity_payment(amount, rate, term)
            return lm.dscr(1_200_000, 600_000, pay) >= D("1.30") and lm.stress_dscr(
                1_200_000, 600_000, pay, D("0.20")
            ) >= D("1.05")

        assert lm.largest_step_amount(ok, hint, 50_000) == stepped


def test_sokolova_and_garipov_max_amounts() -> None:
    p = lm.max_payment(90_500, 3_000, D("1.25"))
    assert p == 69_400
    assert abs(lm.max_amount_formula(p, D("0.215"), 12, "ANNUITY") - 743_407) <= 1
    p = lm.max_payment(91_000, 0, D("1.25"))
    assert p == 72_800
    assert abs(lm.max_amount_formula(p, D("0.225"), 36, "ANNUITY") - 1_893_388) <= 1


def test_max_amount_edge_cases() -> None:
    assert lm.max_amount_formula(D(-5), D("0.2"), 12, "ANNUITY") == 0
    assert lm.max_amount_formula(D(100_000), D("0.2"), 12, "OVERDRAFT") == 0
    assert lm.max_amount_formula(D(100_000), D("0.2"), 12, "BULLET") == 6_000_000
    assert lm.largest_step_amount(lambda _a: False, 10, 50_000) == 0
    assert (
        lm.largest_step_amount(lambda a: a <= 400_000, 10_000_000, 50_000, cap=300_000) == 300_000
    )
    with pytest.raises(ValueError, match="шаг"):
        lm.largest_step_amount(lambda _a: True, 0, 0)


def test_min_term_edge_cases() -> None:
    assert lm.min_term(1_000_000, D("0.2"), D(0)) is None
    assert lm.min_term(1_000_000, D("0.2"), D(10_000)) is None  # платёж меньше процентов
    assert lm.min_term(1_200_000, D(0), D(100_000)) == 12


# ---------------------------------------------------------------- даты (пример 9)


def test_example_9_payment_dates_move_to_next_business_day() -> None:
    dates = lm.payment_dates(date(2026, 10, 20), 12)
    expected = [
        date(2026, 11, 20),
        date(2026, 12, 21),
        date(2027, 1, 20),
        date(2027, 2, 22),
        date(2027, 3, 22),
        date(2027, 4, 20),
        date(2027, 5, 20),
        date(2027, 6, 21),
        date(2027, 7, 20),
        date(2027, 8, 20),
        date(2027, 9, 20),
        date(2027, 10, 20),
    ]
    assert list(dates) == expected
    assert all(d.weekday() < 5 for d in dates)  # инвариант 12


def test_payment_day_is_capped_at_28_and_holidays_shift() -> None:
    # 31.01 → день платежа 28-е; 28.02.2026 — суббота, переносится на понедельник 02.03
    assert lm.payment_dates(date(2026, 1, 31), 1)[0] == date(2026, 3, 2)
    shifted = lm.payment_dates(date(2026, 10, 20), 1, holidays=frozenset({date(2026, 11, 20)}))
    assert shifted[0] == date(2026, 11, 23)


def test_calendar_helpers() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 10, 21), -60) == date(2021, 10, 21)
    assert add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert full_months_between(date(2026, 4, 12), date(2026, 10, 21)) == 6
    assert full_months_between(date(2026, 4, 22), date(2026, 10, 21)) == 5
    assert full_months_between(date(2026, 10, 21), date(2026, 4, 1)) == 0
    assert next_business_day(date(2026, 12, 20)) == date(2026, 12, 21)
