"""Маршрут (T-296, 30-11): таблица из семи строк, серые зоны, матрица полномочий, флаги."""

from __future__ import annotations

import sys
from dataclasses import replace
from decimal import Decimal

import pytest

from app.modules.decisioning import decide
from app.modules.decisioning.affordability import Affordability, evaluate
from app.modules.decisioning.counter_offers import CounterOfferSearch
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.reasons import make
from app.modules.decisioning.routing import RouteResult, route
from app.modules.decisioning.scoring import ScoreResult
from app.modules.decisioning.types import (
    Application,
    Collateral,
    Features,
    Grade,
    Guarantor,
    Level,
    Outcome,
    Product,
    ReasonCode,
    Route,
)
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal
POLICY = cp.load_policy()
BASE = cp.t_base()
FEATS: Features = compute_features(BASE)
APP: Application = BASE.application  # EXPRESS, 1 млн, 12 мес.
RATE = D("0.215")
FEASIBLE = CounterOfferSearch(
    "PLACEHOLDER_T297", (), True, {"amount_rub": 100_000, "term_months": 36, "payment_rub": 3_700}
)
NO_OFFER = replace(FEASIBLE, feasible=False)
FLAG = make("MASS_REGISTRATION", which="адрес")


def mk_score(points: int) -> ScoreResult:
    row = POLICY.grade_of(points)
    return ScoreResult(points, Grade(row.grade), row.pd, (), None)


def afford(app: Application = APP, feats: Features = FEATS, **feat: object) -> Affordability:
    f = replace(feats, **feat)  # type: ignore[arg-type]
    return evaluate(
        POLICY, app.product, app.amount_rub, app.term_months, RATE, f, app, None, None, None
    )


def go(
    points: int = 93,
    app: Application = APP,
    feats: Features = FEATS,
    aff: Affordability | None = None,
    product: tuple[ReasonCode, ...] = (),
    flags: tuple[ReasonCode, ...] = (),
    search: CounterOfferSearch = FEASIBLE,
) -> RouteResult:
    return route(
        POLICY,
        app,
        feats,
        mk_score(points),
        aff or afford(app, feats),
        RATE,
        product,
        flags,
        search,
    )


FAIL = afford(feats=FEATS, flow_model_rub=60_000)  # DSCR ниже 1,25


# ---------------------------------------------------------------- строки 6 и 7: одобрение и встречные


def test_row_6_everything_fine_is_auto_approved() -> None:
    r = go()
    assert (r.outcome, r.route, r.level, r.reasons) == (Outcome.APPROVED, Route.AUTO, Level.L0, ())


def test_row_7_money_fails_but_offers_exist_is_counter_offer() -> None:
    r = go(aff=FAIL)
    assert (r.outcome, r.route, r.level) == (Outcome.COUNTER_OFFER, Route.AUTO, Level.L0)
    assert [x.code for x in r.reasons] == ["DSCR_LOW"]
    assert r.variants_status == "PLACEHOLDER_T297"
    assert r.variants == ()


def test_product_violation_alone_also_leads_to_counter_offer() -> None:
    r = go(
        product=(
            make(
                "PRODUCT_AGE_MIN",
                product="X",
                required_months=12,
                age_months=3,
                available_from=None,
            ),
        )
    )
    assert r.outcome == Outcome.COUNTER_OFFER
    assert r.reasons[0].code == "PRODUCT_AGE_MIN"


# ---------------------------------------------------------------- строка 5: грейд E и «нет встречных»


def test_row_5_no_offer_at_all_is_rejected_with_no_offer_found() -> None:
    r = go(aff=FAIL, search=NO_OFFER)
    assert (r.outcome, r.route) == (Outcome.REJECTED, Route.AUTO)
    assert r.reasons[0].code == "NO_OFFER_FOUND"  # главный код итога
    assert {"DSCR_LOW", "NO_OFFER_FOUND"} <= {x.code for x in r.reasons}


@pytest.mark.parametrize(
    ("points", "outcome"), [(43, Outcome.REJECTED), (46, Outcome.MANUAL_REVIEW)]
)
def test_grade_e_outside_gray_zone_is_rejected_d_goes_to_human(
    points: int, outcome: Outcome
) -> None:
    not_allowed = (make("GRADE_NOT_ALLOWED", grade="E", product="EXPRESS", why="NOT_OFFERED"),)
    r = go(points, product=not_allowed if points < 46 else ())
    assert r.outcome == outcome
    if outcome == Outcome.REJECTED:
        assert [x.code for x in r.reasons] == [
            "RISK_TOO_HIGH"
        ]  # шум GRADE_NOT_ALLOWED не показываем


# ---------------------------------------------------------------- серая зона баллов: 73 / 74 / 75 / 76 и 44 / 45


@pytest.mark.parametrize(
    ("points", "outcome", "codes"),
    [
        (76, Outcome.APPROVED, []),
        (75, Outcome.MANUAL_REVIEW, ["NEAR_THRESHOLD"]),
        (74, Outcome.MANUAL_REVIEW, ["NEAR_THRESHOLD"]),
        (73, Outcome.MANUAL_REVIEW, ["GRADE_NEEDS_REVIEW"]),  # уже грейд C
        (45, Outcome.MANUAL_REVIEW, ["NEAR_THRESHOLD"]),  # «вместо отказа»
        (44, Outcome.MANUAL_REVIEW, ["NEAR_THRESHOLD"]),
        (43, Outcome.REJECTED, ["RISK_TOO_HIGH"]),
    ],
)
def test_points_gray_zone_boundaries(points: int, outcome: Outcome, codes: list[str]) -> None:
    r = go(points)
    assert r.outcome == outcome
    assert [x.code for x in r.reasons] == codes


def test_grade_e_in_gray_zone_recommendation_is_to_reject() -> None:
    r = go(45)
    assert r.recommendation is not None
    assert r.recommendation.outcome == Outcome.REJECTED


# ---------------------------------------------------------------- строка 4: ручные причины


def test_any_flag_sends_a_human_even_to_a_perfect_client() -> None:
    r = go(flags=(FLAG,))
    assert (r.outcome, r.route) == (Outcome.MANUAL_REVIEW, Route.MANUAL)
    assert r.reasons[0].code == "MASS_REGISTRATION"
    assert r.recommendation is not None
    assert r.recommendation.outcome == Outcome.APPROVED


def test_flag_plus_grade_c_intersection() -> None:
    r = go(65, flags=(FLAG,))
    assert [x.code for x in r.reasons] == ["MASS_REGISTRATION", "GRADE_NEEDS_REVIEW"]
    assert r.level == Level.L1


@pytest.mark.parametrize(("points", "grade"), [(70, "C"), (50, "D")])
def test_grade_c_and_d_always_need_review(points: int, grade: str) -> None:
    r = go(points)
    assert r.outcome == Outcome.MANUAL_REVIEW
    assert r.reasons[0].code == "GRADE_NEEDS_REVIEW"
    assert r.reasons[0].params["grade"] == grade


def test_amount_above_auto_limit_only_when_request_itself_passes() -> None:
    big = replace(APP, product=Product.WORKING_CAPITAL, amount_rub=10_000_001, term_months=36)
    feats = replace(FEATS, flow_model_rub=5_000_000, revenue_annual_rub=600_000_000)
    r = go(93, big, feats, aff=afford(big, feats))
    assert r.outcome == Outcome.MANUAL_REVIEW
    assert r.reasons[0].code == "AMOUNT_ABOVE_AUTO_LIMIT"
    assert r.reasons[0].params["limit_rub"] == 10_000_000
    # на лимите A (10 млн) — автомат
    edge = replace(big, amount_rub=10_000_000)
    assert go(93, edge, feats, aff=afford(edge, feats)).outcome == Outcome.APPROVED
    # грейд B — лимит каталога, 5 млн
    over_b = replace(big, amount_rub=5_000_001)
    assert go(80, over_b, feats, aff=afford(over_b, feats)).outcome == Outcome.MANUAL_REVIEW
    assert (
        go(
            80,
            replace(big, amount_rub=5_000_000),
            feats,
            aff=afford(replace(big, amount_rub=5_000_000), feats),
        ).outcome
        == Outcome.APPROVED
    )


def test_original_request_above_limit_does_not_block_an_automatic_counter_offer() -> None:
    """Уточнение C-04: превышение авто-лимита в исходном запросе — не ручная причина, если он не проходит."""
    big = replace(APP, product=Product.WORKING_CAPITAL, amount_rub=6_000_000, term_months=12)
    feats = replace(FEATS, flow_model_rub=100_000)
    r = go(80, big, feats, aff=afford(big, feats))  # грейд B: авто-лимит 5 млн
    assert r.outcome == Outcome.COUNTER_OFFER
    assert r.route == Route.AUTO


def test_collateral_review_when_collateral_given_or_required() -> None:
    with_collateral = replace(APP, collateral=Collateral("оборудование", 2_000_000))
    r = go(93, with_collateral)
    assert r.outcome == Outcome.MANUAL_REVIEW
    assert r.reasons[0].code == "COLLATERAL_REVIEW"
    assert r.reasons[0].params["share"] == D("0.5")  # сумма / оценка залога
    investment = replace(
        APP,
        product=Product.INVESTMENT,
        amount_rub=2_000_000,
        term_months=36,
        collateral=Collateral("станок", 3_000_000),
    )
    codes = [x.code for x in go(93, investment, aff=afford(investment)).reasons]
    assert codes == ["AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"]  # INVESTMENT всегда вручную


def test_money_gray_zone_goes_to_a_human() -> None:
    gray = afford(flow_model_rub=int(D("1.27") * 93_354) + 1, existing_payments_rub=0)
    assert gray.passes
    assert gray.near_threshold
    r = go(93, aff=gray)
    assert r.outcome == Outcome.MANUAL_REVIEW
    assert {x.params["metric"] for x in r.reasons} == {"DSCR", "STRESS_DSCR"}


def test_manual_review_on_failing_request_recommends_what_core_would_decide() -> None:
    r = go(65, aff=FAIL)  # грейд C и деньги не проходят
    assert r.outcome == Outcome.MANUAL_REVIEW
    assert r.recommendation is not None
    assert r.recommendation.outcome == Outcome.COUNTER_OFFER
    assert {"GRADE_NEEDS_REVIEW", "DSCR_LOW"} <= {x.code for x in r.reasons}
    nothing = go(65, aff=FAIL, search=NO_OFFER)
    assert nothing.recommendation is not None
    assert nothing.recommendation.outcome == Outcome.REJECTED


# ---------------------------------------------------------------- строка 3: молодой бизнес (D-077)

YOUNG = replace(FEATS, business_age_months=3, security_confirmed=False, collateral_provided=False)


def test_row_3_young_business_without_security_gets_conditional_counter_offer_even_at_grade_c() -> (
    None
):
    r = go(65, feats=YOUNG)
    assert (r.outcome, r.route, r.level) == (Outcome.COUNTER_OFFER, Route.AUTO, Level.L0)
    assert [x.code for x in r.reasons] == ["BUSINESS_TOO_YOUNG"]
    (variant,) = r.variants
    assert variant.security_required
    assert variant.recommended
    assert variant.amount_rub == APP.amount_rub
    assert r.variants_status == "CONDITIONAL_ONLY"


def test_young_business_with_security_goes_to_a_human() -> None:
    secured = replace(YOUNG, security_confirmed=True, guarantor_confirmed=True)
    app = replace(APP, guarantor=Guarantor("1", True))
    r = go(93, app, secured)
    assert (r.outcome, r.level) == (Outcome.MANUAL_REVIEW, Level.L1)
    assert r.reasons[0].code == "BUSINESS_TOO_YOUNG"
    assert r.recommendation is not None
    assert r.recommendation.hint == "APPROVE_WITH_GUARANTEE"


def test_young_business_with_a_flag_is_not_given_the_conditional_offer() -> None:
    r = go(65, feats=YOUNG, flags=(FLAG,))
    assert r.outcome == Outcome.MANUAL_REVIEW
    assert r.variants == ()
    assert [x.code for x in r.reasons][:2] == ["MASS_REGISTRATION", "BUSINESS_TOO_YOUNG"]


def test_young_business_with_failing_money_follows_the_ordinary_path() -> None:
    r = go(93, feats=YOUNG, aff=FAIL)
    assert r.outcome == Outcome.COUNTER_OFFER
    assert r.variants == ()
    assert [x.code for x in r.reasons] == ["BUSINESS_TOO_YOUNG", "DSCR_LOW"]


# ---------------------------------------------------------------- флаги подключаются снаружи (T-288/T-290)


def test_flags_plug_in_through_the_flag_evaluator(monkeypatch: pytest.MonkeyPatch) -> None:
    decide_module = sys.modules["app.modules.decisioning.decide"]  # имя `decide` в пакете — функция
    monkeypatch.setattr(decide_module, "evaluate_flags", lambda _inp, _feats: (FLAG,))
    result = decide(cp.t_base())
    assert result.outcome == Outcome.MANUAL_REVIEW
    assert result.reason_codes == ("MASS_REGISTRATION",)
    assert result.recommendation is not None
    assert result.recommendation.outcome == Outcome.APPROVED
    assert result.required_level == Level.L1  # 1 млн, грейд A
    # INV-61: флаг без стоп-фактора — никогда не автоодобрение, даже у лучшего клиента
    assert result.outcome != Outcome.APPROVED


def test_authority_level_follows_amount_and_grade() -> None:
    cases = [
        (1_000_000, 65, Level.L1),
        (4_000_000, 50, Level.L2),
        (15_000_000, 90, Level.L1),
        (20_000_000, 90, Level.L2),
    ]
    for amount, points, level in cases:
        app = replace(
            APP,
            product=Product.INVESTMENT,
            amount_rub=amount,
            term_months=36,
            collateral=Collateral("x", amount * 2),
        )
        feats = replace(FEATS, flow_model_rub=50_000_000, revenue_annual_rub=5_000_000_000)
        r = go(points, app, feats, aff=afford(app, feats))
        assert r.outcome == Outcome.MANUAL_REVIEW
        assert r.level == level
