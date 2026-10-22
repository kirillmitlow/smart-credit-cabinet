"""Лимиты (T-293, 30-08, 30-16): DSCR, стресс, потолок долга, пределы продуктов, обратная задача."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.decisioning import decide
from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.affordability import evaluate, meets_counter_thresholds, product_cap
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.types import ContractInfo, Features, Product
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal
POLICY = cp.load_policy()


def run(
    product: Product,
    amount: int,
    term: int,
    rate: str = "0.215",
    p_def12: Decimal | None = None,
    **feat: Any,
):  # type: ignore[no-untyped-def]
    inp = cp.t_base()
    feats = replace(compute_features(inp), **feat)
    app = replace(inp.application, product=product, amount_rub=amount, term_months=term)
    return evaluate(
        POLICY, product, amount, term, D(rate), feats, app, None, feats.inflow_average_rub, p_def12
    )


def codes(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [r.code for r in result.violations]


# ---------------------------------------------------------------- эталоны 30-17


def test_sokolova_numbers() -> None:
    n = decide(cp.sokolova()).numbers
    assert (n.dscr, n.stress_dscr) == (D("1.821769"), D("1.457415"))
    assert n.debt_to_revenue_with_new is not None
    assert n.debt_to_revenue_with_new.quantize(D("0.001")) == D("0.052")
    assert (n.p_max_rub, n.max_amount_rub) == (69_400, 700_000)


def test_snabkontrakt_does_not_pass_with_dscr_low_only() -> None:
    result = decide(cp.snabkontrakt())
    assert result.reason_codes == ("DSCR_LOW",)
    reason = result.reasons[0]
    assert reason.params["safe_payment_rub"] == 360_000  # «безопасно можно платить до»
    assert result.numbers.stress_dscr is not None
    assert result.numbers.stress_dscr < 1


def test_garipov_max_amount_and_term() -> None:
    n = decide(cp.garipov(second_pass=True)).numbers
    assert (n.p_max_rub, n.max_amount_rub) == (72_800, 1_850_000)
    assert n.max_amount_formula_rub is not None
    assert abs(n.max_amount_formula_rub - 1_893_388) <= 1


def test_stankoprom_collateral_cap_is_70_percent() -> None:
    inp = cp.stankoprom()
    feats = compute_features(inp)
    cap = product_cap(POLICY, Product.INVESTMENT, feats, inp.application, None, None)
    assert cap == ("INVESTMENT_70_PERCENT_OF_COLLATERAL", 17_500_000)
    assert inp.application.amount_rub <= 17_500_000


def test_zarya_line_cap_is_half_of_monthly_revenue() -> None:
    inp = cp.zarya()
    feats = compute_features(inp)
    cap = product_cap(POLICY, Product.CREDIT_LINE, feats, inp.application, None, None)
    assert cap == ("LINE_HALF_OF_MONTHLY_REVENUE", 27_083_333)


# ---------------------------------------------------------------- границы DSCR


# Платёж 93 354 + текущие 6 646 = ровно 100 000: поток 125 000 даёт DSCR 1,25 без округлений
EXISTING = 100_000 - 93_354


def boundary(flow: int, shock: str = "0.20"):  # type: ignore[no-untyped-def]
    return run(
        Product.EXPRESS,
        1_000_000,
        12,
        flow_model_rub=flow,
        existing_payments_rub=EXISTING,
        stress_shock=D(shock),
    )


@pytest.mark.parametrize(
    ("flow", "passes", "gray"),
    [
        (124_990, False, False),  # 1,2499 — не проходит
        (125_000, True, True),  # 1,25 ровно — проходит, но серая зона
        (129_990, True, True),  # 1,2999
        (130_000, True, False),  # 1,30 — зона кончилась
    ],
)
def test_dscr_boundary_and_gray_zone(flow: int, passes: bool, gray: bool) -> None:
    result = boundary(flow)
    assert result.passes is passes
    assert ("DSCR" in [r.params["metric"] for r in result.near_threshold]) is gray


def test_dscr_exactly_at_threshold_is_exact() -> None:
    assert boundary(125_000).dscr == D("1.25")
    assert codes(boundary(124_999)) == ["DSCR_LOW"]


# ---------------------------------------------------------------- стресс: STRESS_DSCR_LOW только при DSCR ≥ 1,25


def test_stress_code_is_not_set_when_dscr_already_fails() -> None:
    """DSCR 0,90: стресс при шоке 20% проваливается автоматически, код дублировал бы DSCR_LOW."""
    result = decide(cp.snabkontrakt())
    assert "STRESS_DSCR_LOW" not in result.reason_codes


def test_stress_code_with_shock_40_percent() -> None:
    """DSCR 1,30 при шоке 40%: стресс 0,78 < 1,0 → ставится STRESS_DSCR_LOW (30-12)."""
    payment = lm.annuity_payment(1_000_000, D("0.215"), 12)
    flow = int(D(payment) * D("1.30")) + 1
    result = run(
        Product.EXPRESS,
        1_000_000,
        12,
        flow_model_rub=flow,
        existing_payments_rub=0,
        stress_shock=D("0.40"),
    )
    assert codes(result) == ["STRESS_DSCR_LOW"]
    assert result.stress_dscr is not None
    assert result.stress_dscr < D("0.79")


def test_stress_gray_zone_between_1_00_and_1_05() -> None:
    payment = lm.annuity_payment(1_000_000, D("0.215"), 12)
    flow = int(D(payment) * D("1.27")) + 1  # DSCR 1,27 → стресс 1,016 при шоке 20%
    result = run(
        Product.EXPRESS,
        1_000_000,
        12,
        flow_model_rub=flow,
        existing_payments_rub=0,
        stress_shock=D("0.20"),
    )
    assert result.passes
    assert {r.params["metric"] for r in result.near_threshold} == {"DSCR", "STRESS_DSCR"}


# ---------------------------------------------------------------- долг к выручке


def test_debt_ceiling_and_gray_zone() -> None:
    annual = 12_000_000
    ok_ = run(Product.EXPRESS, 1_000_000, 12, revenue_annual_rub=annual, total_debt_rub=5_000_000)
    assert ok_.passes
    assert ok_.debt_ratio_with_new == D("0.5")
    gray = run(Product.EXPRESS, 1_000_000, 12, revenue_annual_rub=annual, total_debt_rub=10_400_000)
    assert gray.passes
    assert "DEBT_TO_REVENUE" in [r.params["metric"] for r in gray.near_threshold]
    exact_one = run(
        Product.EXPRESS, 1_000_000, 12, revenue_annual_rub=annual, total_debt_rub=11_000_000
    )
    assert exact_one.passes  # ровно 1,0 — не больше годовой выручки
    over = run(Product.EXPRESS, 1_000_000, 12, revenue_annual_rub=annual, total_debt_rub=11_000_001)
    assert codes(over) == ["DEBT_TOO_HIGH"]
    assert over.violations[0].params["max_new_rub"] == 999_999  # на рубль меньше запроса


# ---------------------------------------------------------------- особые лимиты продуктов


def test_line_limit_above_half_of_monthly_revenue() -> None:
    inp = cp.zarya()
    big = cp.with_application(inp, amount_rub=27_083_334)
    reasons = decide(big).reason_codes
    assert "LIMIT_ABOVE_CAP" in reasons
    assert (
        "LIMIT_ABOVE_CAP"
        not in decide(cp.with_application(inp, amount_rub=27_083_333)).reason_codes
    )


def test_overdraft_limit_is_30_percent_of_inflows() -> None:
    feats = compute_features(cp.sokolova())
    inp = cp.sokolova()
    cap = product_cap(
        POLICY, Product.OVERDRAFT, feats, inp.application, None, feats.inflow_average_rub
    )
    assert cap == ("OVERDRAFT_30_PERCENT_OF_INFLOWS", 271_500)  # пример 6
    over = run(Product.OVERDRAFT, 300_000, 12, "0.25", inflow_average_rub=905_000)
    assert [r.code for r in over.violations] == ["LIMIT_ABOVE_CAP"]
    assert over.dscr is None  # для овердрафта платежа по графику нет


def test_contract_limit_is_80_percent_of_unpaid() -> None:
    contract = ContractInfo("N1", 12_000_000, 0, "IN_PROGRESS", date(2027, 1, 15))
    inp = cp.snabkontrakt()
    feats = compute_features(inp)
    assert product_cap(POLICY, Product.CONTRACT, feats, inp.application, contract, None) == (
        "CONTRACT_80_PERCENT_OF_UNPAID",
        9_600_000,
    )
    partly_paid = replace(contract, paid_rub=2_000_000)
    cap = product_cap(POLICY, Product.CONTRACT, feats, inp.application, partly_paid, None)
    assert cap is not None
    assert cap[1] == 8_000_000


def test_contract_payment_is_interest_only() -> None:
    """Пример 4 и карточка 3 из 30-17: проценты 130 000, DSCR 1,644, стресс 1,315."""
    inp = cp.snabkontrakt()
    contract = inp.snapshot.contracts.contracts[0]
    feats = compute_features(inp)
    app = replace(inp.application, product=Product.CONTRACT, term_months=4)
    result = evaluate(
        POLICY, Product.CONTRACT, 8_000_000, 4, D("0.195"), feats, app, contract, None, None
    )
    assert result.payment_rub == 130_000
    assert result.last_payment_rub == 8_130_000
    assert result.overpayment_rub == 520_000
    assert result.dscr is not None
    assert result.dscr.quantize(D("0.001")) == D("1.644")
    assert result.stress_dscr is not None
    assert result.stress_dscr.quantize(D("0.001")) == D("1.315")
    assert result.passes


def test_investment_cap_without_collateral_is_not_applied() -> None:
    inp = cp.with_application(cp.stankoprom(), collateral=None)
    feats = compute_features(inp)
    assert product_cap(POLICY, Product.INVESTMENT, feats, inp.application, None, None) is None


# ---------------------------------------------------------------- вероятностный стресс (P_def12)


def test_p_def12_absent_is_skipped_and_recorded_in_trace() -> None:
    trace = {step.step: step for step in decide(cp.sokolova()).trace}
    assert trace["9.limits"].detail["p_def12"] == "SKIPPED_NOT_PROVIDED"


def test_p_def12_yellow_zone_goes_to_a_human_and_red_fails() -> None:
    inp = cp.sokolova()
    yellow = replace(inp, context=replace(inp.context, p_def12=D("0.15")))
    assert decide(yellow).outcome.value == "MANUAL_REVIEW"
    assert decide(yellow).reason_codes == ("NEAR_THRESHOLD",)
    red = replace(inp, context=replace(inp.context, p_def12=D("0.25")))
    result = decide(red)
    assert "STRESS_DSCR_LOW" in result.reason_codes
    assert result.outcome.value != "APPROVED"
    green = replace(inp, context=replace(inp.context, p_def12=D("0.05")))
    assert decide(green).outcome.value == "APPROVED"


# ---------------------------------------------------------------- обратная задача


def test_inverse_problem_is_verified_by_direct_calculation_inv_30() -> None:
    inp = cp.snabkontrakt()
    feats = compute_features(inp)
    app = inp.application
    for term in (12, 24, 36):
        res = evaluate(
            POLICY,
            Product.WORKING_CAPITAL,
            8_000_000,
            term,
            D("0.195"),
            feats,
            app,
            None,
            None,
            None,
        )
        top = dict(res.max_amount_by_term)[term]
        assert top % 50_000 == 0
        assert lm.dscr(
            feats.flow_model_rub or 0,
            feats.existing_payments_rub,
            lm.annuity_payment(top, D("0.195"), term),
        ) >= D("1.25")
        beyond = lm.annuity_payment(top + 50_000, D("0.195"), term)
        assert lm.dscr(feats.flow_model_rub or 0, feats.existing_payments_rub, beyond) < D("1.25")


def test_no_room_when_flow_does_not_cover_existing_payments() -> None:
    result = run(
        Product.EXPRESS, 1_000_000, 12, flow_model_rub=100_000, existing_payments_rub=200_000
    )
    assert result.p_max_rub == 0
    assert result.max_amount_rub == 0
    assert result.max_amount_formula_rub == 0
    assert result.min_term_months is None


def test_counter_thresholds_helper() -> None:
    kwargs: dict[str, Any] = {"shock": D("0.20")}
    assert meets_counter_thresholds(
        POLICY, 1_200_000, 600_000, 314_144, debt_ratio=D("0.1"), **kwargs
    )
    assert not meets_counter_thresholds(
        POLICY, 1_200_000, 600_000, 318_764, debt_ratio=D("0.1"), **kwargs
    )  # 3,45 млн
    assert not meets_counter_thresholds(
        POLICY, 1_200_000, 600_000, 314_144, debt_ratio=D("0.95"), **kwargs
    )
    assert not meets_counter_thresholds(POLICY, 1_200_000, 600_000, 0, debt_ratio=None, **kwargs)
    assert meets_counter_thresholds(POLICY, 1_200_000, 600_000, 314_144, debt_ratio=None, **kwargs)


def test_features_type_is_complete_for_replace() -> None:
    assert isinstance(compute_features(cp.t_base()), Features)
