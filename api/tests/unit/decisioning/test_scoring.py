"""Скоркарта, потолки грейда и PD (T-291, 30-07): каждая граница, сумма максимумов, персоны."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.modules.decisioning import decide
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.scoring import ScoreResult, band_points, score
from app.modules.decisioning.types import Features, Grade, Mode
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal
POLICY = cp.load_policy()
BASE: Features = compute_features(cp.t_base())


def sc(mode: Mode = Mode.DECISION, **changes: Any) -> ScoreResult:
    return score(replace(BASE, **changes), POLICY, mode)


def points(result: ScoreResult, factor: str) -> int:
    return next(f.points for f in result.factors if f.factor == factor)


def test_sum_of_maximums_is_100() -> None:
    result = sc()
    assert sum(f.max_points for f in result.factors) == 100
    assert len(result.factors) == 9
    assert result.points == 93
    assert result.grade == Grade.A


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (0, 0),
        (5, 0),
        (6, 3),
        (11, 3),
        (12, 6),
        (23, 6),
        (24, 8),
        (35, 8),
        (36, 10),
        (59, 10),
        (60, 12),
        (300, 12),
    ],
)
def test_age_boundaries(age: int, expected: int) -> None:
    assert points(sc(business_age_months=age, max_overdue_24m_days=0), "SC_AGE") == expected


def test_age_unknown_gets_no_data_points() -> None:
    assert points(sc(business_age_months=None), "SC_AGE") == 0


@pytest.mark.parametrize(
    ("klass", "expected"),
    [
        ("CLEAN", 24),
        ("MINOR", 18),
        ("THIN_CLEAN", 16),
        ("NO_HISTORY", 13),
        ("PAST_30", 10),
        ("PAST_60", 5),
        ("CURRENT_30_89", 2),
        ("PAST_90", 0),
    ],
)
def test_credit_history_table(klass: str, expected: int) -> None:
    assert points(sc(credit_history_class=klass), "SC_CREDIT_HISTORY") == expected


def test_restructuring_caps_history_at_ten() -> None:
    assert points(sc(restructurings_24m=1), "SC_CREDIT_HISTORY") == 10
    assert (
        points(sc(restructurings_24m=1, credit_history_class="PAST_60"), "SC_CREDIT_HISTORY") == 5
    )


@pytest.mark.parametrize(
    ("inquiries", "rejected", "expected"),
    [
        (0, 0, 8), (1, 0, 8), (2, 0, 6), (3, 0, 6), (4, 0, 4), (6, 0, 4), (7, 0, 3),
        (0, 1, 7), (0, 2, 6), (0, 3, 5), (9, 9, 0),
    ],
)  # fmt: skip
def test_inquiries_table(inquiries: int, rejected: int, expected: int) -> None:
    assert points(sc(inquiries_30d=inquiries, rejected_90d=rejected), "SC_INQUIRIES") == expected


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [("0.0001", 14), ("0.0999", 14), ("0.10", 11), ("0.2499", 11), ("0.25", 7), ("0.4999", 7),
     ("0.50", 3), ("0.7499", 3), ("0.75", 0), ("3", 0)],
)  # fmt: skip
def test_debt_load_boundaries_closed_on_the_left(ratio: str, expected: int) -> None:
    assert points(sc(debt_to_revenue=D(ratio), total_debt_rub=1), "SC_DEBT_LOAD") == expected


def test_debt_load_zero_unknown_and_preview() -> None:
    assert points(sc(debt_to_revenue=D(0), total_debt_rub=0), "SC_DEBT_LOAD") == 16
    assert points(sc(debt_to_revenue=None), "SC_DEBT_LOAD") == 7


@pytest.mark.parametrize(
    ("trend", "expected"),
    [("-0.31", 0), ("-0.30", 1), ("-0.16", 1), ("-0.15", 3), ("-0.06", 3), ("-0.05", 6), ("0", 6),
     ("0.0499", 6), ("0.05", 8), ("0.1499", 8), ("0.15", 10), ("0.9", 10)],
)  # fmt: skip
def test_trend_boundaries(trend: str, expected: int) -> None:
    assert points(sc(revenue_trend_pct=D(trend)), "SC_TREND") == expected


def test_trend_no_data() -> None:
    assert points(sc(revenue_trend_pct=None), "SC_TREND") == 5


@pytest.mark.parametrize(
    ("cv", "expected"),
    [("0", 8), ("0.0999", 8), ("0.10", 6), ("0.1999", 6), ("0.20", 4), ("0.3499", 4), ("0.35", 2),
     ("0.4999", 2), ("0.50", 0), ("2", 0)],
)  # fmt: skip
def test_volatility_boundaries(cv: str, expected: int) -> None:
    assert points(sc(revenue_cv=D(cv)), "SC_VOLATILITY") == expected


def test_volatility_seasonal_and_no_data() -> None:
    assert points(sc(is_seasonal=True, revenue_cv=D("0.9")), "SC_VOLATILITY") == 5
    assert points(sc(revenue_cv=None), "SC_VOLATILITY") == 4


@pytest.mark.parametrize(
    ("debt", "penalties", "offenses", "block", "expected"),
    [
        (0, 0, 0, False, 8),
        (100_000, 0, 0, False, 6),  # 2% от 5 млн — включительно
        (100_001, 0, 0, False, 4),
        (250_000, 0, 0, False, 4),  # 5%
        (250_001, 0, 0, False, 2),
        (500_000, 0, 0, False, 2),  # 10%
        (500_001, 0, 0, False, 0),
        (0, 50_000, 0, False, 6),  # пени тоже считаются
        (0, 0, 2, False, 6),  # минус 2 за правонарушения
        (500_001, 0, 5, False, 0),  # не уходит ниже нуля
        (0, 0, 0, True, 0),  # блокировка счёта
    ],
)
def test_tax_factor(debt: int, penalties: int, offenses: int, block: bool, expected: int) -> None:
    result = sc(
        tax_debt_rub=debt,
        tax_penalties_rub=penalties,
        tax_offenses=offenses,
        account_block_active=block,
    )
    assert points(result, "SC_TAX") == expected


def test_tax_unknown_profile_gets_no_data_points() -> None:
    assert points(sc(tax_known=False), "SC_TAX") == 4


@pytest.mark.parametrize(
    ("customer", "tenure", "expected"),
    [(False, None, 2), (True, 0, 3), (True, 11, 3), (True, 12, 5), (True, 35, 5), (True, 36, 6)],
)
def test_client_factor(customer: bool, tenure: int | None, expected: int) -> None:
    result = sc(is_bank_customer=customer, customer_tenure_months=tenure)
    assert points(result, "SC_CLIENT") == expected


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        ("1.19", 0),
        ("1.2", 2),
        ("1.49", 2),
        ("1.5", 4),
        ("1.99", 4),
        ("2", 6),
        ("2.99", 6),
        ("3", 8),
        ("40", 8),
    ],
)
def test_coverage_boundaries_two_is_in_the_upper_interval(coverage: str, expected: int) -> None:
    assert points(sc(coverage_existing=D(coverage)), "SC_COVERAGE") == expected


def test_no_payments_gives_full_coverage_points() -> None:
    assert points(sc(coverage_existing=None), "SC_COVERAGE") == 8


# ---------------------------------------------------------------- режим preview, потолки, шкала


def test_preview_uses_cautious_bki_factors() -> None:
    bad_bki = {"credit_history_class": "PAST_90", "inquiries_30d": 9, "debt_to_revenue": D("0.9")}
    preview = sc(Mode.PREVIEW, **bad_bki)
    assert points(preview, "SC_CREDIT_HISTORY") == 16
    assert points(preview, "SC_INQUIRIES") == 5
    assert points(preview, "SC_DEBT_LOAD") == 7
    real = sc(Mode.DECISION, **bad_bki)
    assert real.points < preview.points


def test_missing_bki_in_decision_mode_is_cautious_too() -> None:
    result = sc(bki_known=False, credit_history_class="NO_HISTORY")
    assert points(result, "SC_CREDIT_HISTORY") == 16
    assert points(result, "SC_INQUIRIES") == 5


def test_preview_never_promises_more_than_a_clean_decision() -> None:
    clean = sc(Mode.DECISION)
    assert sc(Mode.PREVIEW).points <= clean.points


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"business_age_months": 5}, "возраст бизнеса"),
        ({"max_overdue_24m_days": 60}, "просрочка за 24 мес."),
        ({"restructurings_24m": 1}, "реструктуризация за 24 мес."),
    ],
)
def test_grade_cap_to_c_even_when_points_are_enough(
    overrides: dict[str, Any], expected_reason: str
) -> None:
    result = sc(**overrides)
    assert result.grade == Grade.C
    assert result.pd == D("0.07")
    assert result.capped is not None
    assert result.capped.code == "GRADE_CAPPED"
    assert expected_reason in str(result.capped.params["because"])


def test_cap_does_not_fire_below_thresholds_or_when_already_c() -> None:
    assert sc(max_overdue_24m_days=59).capped is None
    assert sc(business_age_months=6).capped is None
    weak = sc(business_age_months=3, credit_history_class="NO_HISTORY")
    assert weak.grade in (Grade.C, Grade.D, Grade.E)
    assert weak.capped is None


def test_master_scale_boundaries_and_pd() -> None:
    expected = {
        100: ("A", "0.01"), 86: ("A", "0.01"), 85: ("B", "0.03"), 74: ("B", "0.03"),
        73: ("C", "0.07"), 60: ("C", "0.07"), 59: ("D", "0.15"), 46: ("D", "0.15"),
        45: ("E", "0.30"), 0: ("E", "0.30"),
    }  # fmt: skip
    for pts, (grade, pd) in expected.items():
        row = POLICY.grade_of(pts)
        assert (row.grade, row.pd) == (grade, D(pd))


def test_weak_applicant_from_30_07_is_grade_e_with_26_points() -> None:
    """8 мес., просрочка 60–89 в прошлом, 5 запросов и 2 отказа, нагрузка 60%, тренд −10%,
    стабильность 40%, налоги 3%, не клиент, запас 1,3 → 26 баллов (30-07)."""
    result = sc(
        business_age_months=8,
        credit_history_class="PAST_60",
        max_overdue_24m_days=75,
        inquiries_30d=5,
        rejected_90d=2,
        debt_to_revenue=D("0.6"),
        total_debt_rub=1,
        revenue_trend_pct=D("-0.10"),
        revenue_cv=D("0.40"),
        tax_debt_rub=150_000,  # 3% от 5 млн
        is_bank_customer=False,
        customer_tenure_months=None,
        coverage_existing=D("1.3"),
    )
    assert result.points == 26
    assert result.grade == Grade.E
    assert result.pd == D("0.30")


def test_deficit_is_maximum_minus_points() -> None:
    result = sc(business_age_months=0)
    age = next(f for f in result.factors if f.factor == "SC_AGE")
    assert age.deficit == 12


def test_band_points_empty_table_is_an_error() -> None:
    with pytest.raises(ValueError, match="пустая"):
        band_points(D(1), ())


# ---------------------------------------------------------------- персоны (30-07, «Грейды персон»)


@pytest.mark.parametrize(
    ("name", "factors", "total", "grade"),
    [
        ("sokolova", [10, 24, 8, 14, 6, 8, 8, 6, 8], 92, "A"),
        ("snabkontrakt", [12, 24, 8, 14, 6, 8, 8, 6, 6], 92, "A"),
        ("stankoprom", [12, 24, 8, 16, 8, 4, 8, 2, 8], 90, "A"),
        ("garipov", [12, 16, 8, 16, 6, 8, 8, 2, 8], 84, "B"),
        ("zarya", [12, 24, 8, 14, 6, 5, 8, 6, 8], 91, "A"),
        ("quick-start", [0, 16, 8, 16, 5, 4, 8, 3, 8], 68, "C"),
        ("t-base", [10, 24, 8, 16, 6, 8, 8, 5, 8], 93, "A"),
        ("t-mass", [10, 24, 8, 16, 6, 8, 8, 5, 8], 93, "A"),
        ("t-mismatch", [10, 24, 8, 16, 6, 8, 8, 5, 8], 93, "A"),
        ("t-overdue-45", [10, 2, 8, 14, 6, 8, 8, 5, 8], 69, "C"),
        ("t-anomaly", [10, 24, 8, 16, 6, 4, 8, 5, 8], 89, "A"),
        ("t-young-collateral", [0, 16, 8, 16, 5, 4, 8, 3, 8], 68, "C"),
    ],
)
def test_persona_points_by_factor(name: str, factors: list[int], total: int, grade: str) -> None:
    result = decide(cp.PERSONAS[name]())
    assert [f.points for f in result.numbers.factors] == factors
    assert (result.numbers.score_points, result.numbers.grade) == (total, Grade(grade))
