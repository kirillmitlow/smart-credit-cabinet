"""Оракул 30-17: исходы, коды причин, грейды, баллы, ставки, платежи и DSCR персон на `decide()`.

Допуски (30-17, «Заметки для реализации»): рубли ±1, DSCR и стресс ±0,005, доли ±0,05 п.п.,
баллы, грейд, ставка, исход, уровень и коды — точно. «Главный код равен первому, остальные входят
в набор» — проверяем строже: последовательность кодов совпадает с оракулом.

Что оракул требует от шагов, которых в этой поставке ещё нет (флаги T-288/T-290, оптимизатор
встречных T-297), помечено `xfail(strict=True)` с номером задачи: когда шаг появится, тест
упадёт и пометку придётся снять, а не забыть.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.modules.decisioning import decide
from app.modules.decisioning.types import (
    DecisionResult,
    Grade,
    Level,
    Outcome,
    Route,
)
from tests.fixtures.core_personas import PERSONAS

pytestmark = pytest.mark.unit

D = Decimal


@dataclass(frozen=True)
class Expect:
    outcome: Outcome
    codes: tuple[str, ...] = ()
    grade: Grade | None = None
    points: int | None = None
    rate: Decimal | None = None
    payment: int | None = None
    last_payment: int | None = None
    overpayment: int | None = None
    dscr: Decimal | None = None
    stress: Decimal | None = None  # только если стресс назван в 30-17
    revenue: int | None = None
    flow: int | None = None
    level: Level = Level.L0
    route: Route = Route.AUTO
    p_max: int | None = None
    max_formula: int | None = None
    max_stepped: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


ORACLE: dict[str, Expect] = {
    "sokolova": Expect(
        Outcome.APPROVED,
        (),
        Grade.A,
        92,
        D("0.215"),
        46_677,
        46_679,
        60_126,
        D("1.822"),
        D("1.457"),
        905_000,
        90_500,
        p_max=69_400,
        max_formula=743_407,
        max_stepped=700_000,
    ),
    "snabkontrakt": Expect(
        Outcome.COUNTER_OFFER,
        ("DSCR_LOW",),
        Grade.A,
        92,
        D("0.195"),
        739_163,
        739_163,
        869_956,
        D("0.896"),
        D("0.717"),
        15_000_000,
        1_200_000,
        p_max=360_000,
        max_stepped=3_850_000,
    ),
    "stankoprom": Expect(
        Outcome.MANUAL_REVIEW,
        ("AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"),
        Grade.A,
        90,
        D("0.195"),
        393_247,
        393_215,
        8_594_788,
        D("6.91"),
        D("5.53"),
        35_000_000,
        2_716_667,
        level=Level.L1,
        route=Route.MANUAL,
    ),
    "garipov": Expect(
        Outcome.APPROVED,
        (),
        Grade.B,
        84,
        D("0.225"),
        57_674,
        57_700,
        576_290,
        D("1.578"),
        D("1.262"),
        700_000,
        91_000,
        p_max=72_800,
        max_formula=1_893_388,
        max_stepped=1_850_000,
    ),
    "garipov-pass1": Expect(Outcome.NEEDS_INFO, ("REVENUE_UNKNOWN",)),
    "romashka": Expect(Outcome.REJECTED, ("TAX_ARREARS_HIGH", "CURRENT_OVERDUE_90")),
    "vektor": Expect(Outcome.REJECTED, ("COMPANY_NOT_ACTIVE",)),
    "orlov": Expect(Outcome.NOT_ELIGIBLE, ("SELF_EMPLOYED",)),
    "zarya": Expect(
        Outcome.MANUAL_REVIEW,
        ("AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"),
        Grade.A,
        91,
        D("0.195"),
        325_000,
        None,
        None,
        D("3.15"),
        D("2.52"),
        54_166_667,
        5_750_000,
        level=Level.L2,
        route=Route.MANUAL,
    ),
    "quick-start": Expect(
        Outcome.COUNTER_OFFER,
        ("BUSINESS_TOO_YOUNG",),
        Grade.C,
        68,
        D("0.240"),
        52_871,
        52_874,
        268_907,
        D("1.390"),
        D("1.112"),
        490_000,
        73_500,
    ),
    "quick-start-guarantor": Expect(
        Outcome.MANUAL_REVIEW,
        ("BUSINESS_TOO_YOUNG", "GRADE_NEEDS_REVIEW"),
        Grade.C,
        68,
        D("0.240"),
        52_871,
        52_874,
        268_907,
        D("1.390"),
        D("1.112"),
        490_000,
        73_500,
        level=Level.L1,
        route=Route.MANUAL,
    ),
    "t-base": Expect(
        Outcome.APPROVED,
        (),
        Grade.A,
        93,
        D("0.215"),
        93_354,
        93_352,
        None,
        D("8.03"),
        D("6.43"),
        5_000_000,
        750_000,
    ),
    "t-aml": Expect(Outcome.REJECTED, ("AML_LIST",)),
    "t-gambling": Expect(Outcome.REJECTED, ("FORBIDDEN_INDUSTRY",)),
    "t-overdue-95": Expect(Outcome.REJECTED, ("CURRENT_OVERDUE_90",)),
    "t-bankrupt": Expect(Outcome.REJECTED, ("BANKRUPTCY",)),
    "t-tax-debt": Expect(Outcome.REJECTED, ("TAX_ARREARS_HIGH",)),
    "t-young-collateral": Expect(
        Outcome.MANUAL_REVIEW,
        ("BUSINESS_TOO_YOUNG", "GRADE_NEEDS_REVIEW", "COLLATERAL_REVIEW"),
        Grade.C,
        68,
        D("0.235"),
        94_318,
        None,
        None,
        D("1.67"),
        None,
        1_050_000,
        157_500,
        level=Level.L1,
        route=Route.MANUAL,
    ),
}

# Что оракул считает по числам, но исход и коды которых зависят от флагов T-288/T-290
FLAG_PERSONAS: dict[str, Expect] = {
    "t-mass": Expect(
        Outcome.MANUAL_REVIEW,
        ("MASS_REGISTRATION",),
        Grade.A,
        93,
        D("0.215"),
        93_354,
        93_352,
        None,
        D("8.03"),
        D("6.43"),
        5_000_000,
        750_000,
        level=Level.L1,
        route=Route.MANUAL,
    ),
    "t-overdue-45": Expect(
        Outcome.MANUAL_REVIEW,
        ("OVERDUE_30_89", "GRADE_NEEDS_REVIEW"),
        Grade.C,
        69,
        D("0.240"),
        94_560,
        None,
        None,
        D("4.37"),
        None,
        5_000_000,
        750_000,
        level=Level.L1,
        route=Route.MANUAL,
    ),
    "t-mismatch": Expect(
        Outcome.MANUAL_REVIEW,
        ("DATA_MISMATCH",),
        Grade.A,
        93,
        D("0.195"),
        277_186,
        None,
        None,
        D("1.62"),
        None,
        5_000_000,
        450_000,
        level=Level.L1,
        route=Route.MANUAL,
    ),
    "t-anomaly": Expect(
        Outcome.MANUAL_REVIEW,
        ("TURNOVER_ANOMALY",),
        Grade.A,
        89,
        D("0.215"),
        93_354,
        93_352,
        None,
        D("8.03"),
        None,
        6_000_000,
        750_000,
        level=Level.L1,
        route=Route.MANUAL,
    ),
}


def _close(actual: Decimal | None, expected: Decimal, tolerance: Decimal) -> bool:
    return actual is not None and abs(actual - expected) <= tolerance


def check_numbers(result: DecisionResult, exp: Expect) -> None:
    n = result.numbers
    assert n.grade == exp.grade
    assert n.score_points == exp.points
    if exp.rate is not None:
        assert n.rate == exp.rate
    for actual, expected, label in (
        (n.payment_rub, exp.payment, "платёж"),
        (n.last_payment_rub, exp.last_payment, "последний платёж"),
        (n.overpayment_rub, exp.overpayment, "переплата"),
        (n.revenue_cautious_rub, exp.revenue, "выручка"),
        (n.flow_rub, exp.flow, "поток"),
        (n.p_max_rub, exp.p_max, "P_max"),
        (n.max_amount_formula_rub, exp.max_formula, "S_max по формуле"),
    ):
        if expected is not None:
            assert actual is not None, label
            # Допуск оракула: рубли ±1 (последний платёж — ±n, берём ±1 с запасом на округление)
            assert abs(actual - expected) <= 1, f"{label}: {actual} против {expected}"
    if exp.max_stepped is not None:
        assert n.max_amount_rub == exp.max_stepped
    if exp.dscr is not None:
        assert _close(n.dscr, exp.dscr, D("0.005")), f"DSCR {n.dscr} против {exp.dscr}"
    if exp.stress is not None:
        assert _close(n.stress_dscr, exp.stress, D("0.005")), f"стресс {n.stress_dscr}"


@pytest.mark.parametrize("name", sorted(ORACLE))
def test_oracle_persona(name: str) -> None:
    exp = ORACLE[name]
    result = decide(PERSONAS[name]())
    assert result.outcome == exp.outcome
    assert result.reason_codes == exp.codes
    assert result.route == exp.route
    assert result.required_level == exp.level
    check_numbers(result, exp)


@pytest.mark.parametrize("name", sorted(FLAG_PERSONAS))
def test_oracle_flag_persona_numbers(name: str) -> None:
    """Числа этих сценариев ядро уже считает; исход и коды ждут флагов (см. ниже)."""
    exp = FLAG_PERSONAS[name]
    result = decide(PERSONAS[name]())
    check_numbers(result, exp)


@pytest.mark.xfail(
    strict=True,
    reason="флаги MASS_REGISTRATION, DATA_MISMATCH, TURNOVER_ANOMALY, OVERDUE_30_89: T-288, T-290",
)
@pytest.mark.parametrize("name", sorted(FLAG_PERSONAS))
def test_oracle_flag_persona_outcome_and_codes(name: str) -> None:
    exp = FLAG_PERSONAS[name]
    result = decide(PERSONAS[name]())
    assert result.outcome == exp.outcome
    assert result.reason_codes == exp.codes
    assert result.required_level == exp.level


# ---------------------------------------------------------------- детали отдельных персон


def test_romashka_two_stops_with_exact_share() -> None:
    result = decide(PERSONAS["romashka"]())
    tax = result.reasons[0]
    assert tax.code == "TAX_ARREARS_HIGH"
    assert tax.params["share"] == D("0.1453")  # 14,53% (30-17)
    assert tax.params["repay_min_rub"] == 358_334
    assert tax.params["allowed_rub"] == 791_666
    overdue = result.reasons[1]
    assert overdue.params["days"] == 94
    assert overdue.params["overdue_rub"] == 452_000
    assert result.numbers.grade is None  # скоринг не считается (30-17)


def test_t_tax_debt_is_fifteen_percent() -> None:
    result = decide(PERSONAS["t-tax-debt"]())
    assert result.reasons[0].params["share"] == D("0.1500")


def test_snabkontrakt_boundary_coverage_two_gives_six_points() -> None:
    result = decide(PERSONAS["snabkontrakt"]())
    coverage = next(f for f in result.numbers.factors if f.factor == "SC_COVERAGE")
    assert coverage.points == 6  # запас ровно 2,00 лежит в интервале [2; 3)
    assert result.features is not None
    assert result.features.coverage_existing == D(2)


def test_snabkontrakt_max_amount_by_term_matches_example_7() -> None:
    result = decide(PERSONAS["snabkontrakt"]())
    by_term = dict(result.numbers.max_amount_by_term)
    assert by_term[12] == 3_850_000
    assert by_term[24] == 7_100_000
    assert by_term[36] == 9_750_000
    assert result.numbers.min_term_months == 28  # n_min при пороге 1,25 (30-16)


def test_snabkontrakt_counter_offers_are_a_marked_placeholder() -> None:
    """Три карточки 30-17 строит T-297; пока — явная метка и пустой список."""
    result = decide(PERSONAS["snabkontrakt"]())
    assert result.variants == ()
    assert result.variants_status == "PLACEHOLDER_T297"


def test_quick_start_conditional_counter_offer_has_the_same_terms() -> None:
    result = decide(PERSONAS["quick-start"]())
    (variant,) = result.variants
    assert variant.kind == "CONDITIONAL_SECURITY"
    assert variant.security_required
    assert (variant.amount_rub, variant.term_months, variant.payment_rub) == (1_000_000, 24, 52_871)
    assert variant.rate == D("0.240")


def test_quick_start_grade_c_cap_is_not_recorded() -> None:
    """Грейд C получен по баллам, потолок ничего не понижает: GRADE_CAPPED не пишется."""
    result = decide(PERSONAS["quick-start"]())
    assert "GRADE_CAPPED" not in result.reason_codes


def test_manual_reviews_carry_a_recommendation() -> None:
    stank = decide(PERSONAS["stankoprom"]())
    assert stank.recommendation is not None
    assert stank.recommendation.outcome == Outcome.APPROVED
    assert stank.recommendation.hint == "REQUEST_SELLER_DOCUMENT"
    zarya = decide(PERSONAS["zarya"]())
    assert zarya.recommendation is not None
    assert zarya.recommendation.outcome == Outcome.APPROVED
    young = decide(PERSONAS["t-young-collateral"]())
    assert young.recommendation is not None
    assert young.recommendation.hint == "APPROVE_WITH_COLLATERAL"
    pass2 = decide(PERSONAS["quick-start-guarantor"]())
    assert pass2.recommendation is not None
    assert pass2.recommendation.hint == "APPROVE_WITH_GUARANTEE"


def test_zarya_line_payment_is_interest_on_the_whole_limit() -> None:
    result = decide(PERSONAS["zarya"]())
    assert result.numbers.payment_rub == 325_000
    assert result.features is not None
    assert result.features.is_seasonal
    assert result.numbers.stress_shock == D("0.20")  # сезонным шок 20%
    assert result.numbers.debt_to_revenue_with_new is not None
    assert (
        D("0.09") < result.numbers.debt_to_revenue_with_new < D("0.095")
    )  # (40 + 20) / 650 = 9,2%


def test_t_anomaly_series_gives_stability_four() -> None:
    result = decide(PERSONAS["t-anomaly"]())
    vol = next(f for f in result.numbers.factors if f.factor == "SC_VOLATILITY")
    assert vol.points == 4
    assert result.features is not None
    assert result.features.revenue_cv is not None
    assert abs(result.features.revenue_cv - D("0.289")) < D("0.001")
    assert result.numbers.stress_shock == result.features.revenue_cv


def test_garipov_second_pass_reuses_the_same_bki_report() -> None:
    first = PERSONAS["garipov-pass1"]()
    second = PERSONAS["garipov"]()
    assert first.snapshot.bki == second.snapshot.bki  # D-090: отчёт запрошен один раз
    assert decide(first).outcome == Outcome.NEEDS_INFO
    assert decide(second).outcome == Outcome.APPROVED
