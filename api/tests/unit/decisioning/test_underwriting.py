"""T-362/T-364: проверка ручного решения андеррайтера (30-11): пороги, уровни, ставка, детерминизм."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.modules.decisioning import (
    DecisionInput,
    DecisionResult,
    UnderwriterEvaluation,
    UnderwriterTerms,
    ViolationKind,
    decide,
    evaluate_underwriter_decision,
)
from app.modules.decisioning.types import Level, Outcome, Product, Recommendation, Route
from tests.fixtures import core_personas as cases

pytestmark = pytest.mark.unit

L1, L2 = Level.L1, Level.L2
LONG = "Пересмотрели условия вручную после разговора с клиентом и проверки данных."  # > 50 знаков


def basis(factory=cases.stankoprom) -> tuple[DecisionInput, DecisionResult]:
    inp = factory()
    return inp, decide(inp)


def same_terms(inp: DecisionInput, rate: Decimal | None = None) -> UnderwriterTerms:
    a = inp.application
    return UnderwriterTerms(a.product, a.amount_rub, a.term_months, rate)


def with_flow(result: DecisionResult, flow: int, shock: Decimal | None = None) -> DecisionResult:
    assert result.features is not None
    feats = replace(
        result.features,
        flow_model_rub=flow,
        **({"stress_shock": shock} if shock is not None else {}),
    )
    return replace(result, features=feats)


def codes(ev: UnderwriterEvaluation) -> set[str]:
    return set(ev.violation_codes)


def flow_for(inp: DecisionInput, result: DecisionResult, dscr: Decimal) -> int:
    """Поток, при котором DSCR условий запроса равен `dscr` (с точностью до рубля вниз)."""
    ev = evaluate_underwriter_decision(
        inp, result, Outcome.APPROVED, same_terms(inp), L2, None, None
    )
    assert result.features is not None
    assert ev.payment_rub is not None
    total = result.features.existing_payments_rub + ev.payment_rub
    return int(dscr * total)


def test_agreeing_with_core_is_allowed_without_reason() -> None:
    inp, result = basis()
    ev = evaluate_underwriter_decision(
        inp, result, Outcome.APPROVED, same_terms(inp), L2, None, None, application_version=3
    )
    assert ev.allowed
    assert not ev.deviation
    assert ev.required_level == L1  # 15 млн, грейд A
    assert ev.rate == Decimal("0.195")
    assert ev.payment_rub == 393_247
    assert ev.application_version == 3
    assert (ev.inputs_hash, ev.policy_hash) == (result.inputs_hash, result.policy_hash)
    assert ev.policy_version == inp.policy.meta.version
    assert all(c.passed for c in ev.checks)


def test_evaluation_is_deterministic() -> None:
    inp, result = basis()
    args = (inp, result, Outcome.COUNTER_OFFER, UnderwriterTerms(Product.INVESTMENT, 9_000_000, 48))
    one = evaluate_underwriter_decision(*args, L2, "UW_RISK_HIGHER", LONG)
    two = evaluate_underwriter_decision(*args, L2, "UW_RISK_HIGHER", LONG)
    assert one == two


def test_l1_cannot_decide_on_l2_amount_but_l2_can() -> None:
    inp, result = basis(cases.zarya)  # 20 млн: матрица требует L2
    low = evaluate_underwriter_decision(
        inp, result, Outcome.APPROVED, same_terms(inp), L1, None, None
    )
    high = evaluate_underwriter_decision(
        inp, result, Outcome.APPROVED, same_terms(inp), L2, None, None
    )
    assert low.required_level == L2
    assert not low.allowed
    assert [v.kind for v in low.violations] == [ViolationKind.AUTHORITY]
    assert low.violation_codes == ("AUTHORITY_LEVEL_TOO_LOW",)
    assert high.allowed


def test_counter_with_smaller_amount_lowers_required_level() -> None:
    inp, result = basis(cases.zarya)
    smaller = UnderwriterTerms(inp.application.product, 2_000_000, inp.application.term_months)
    ev = evaluate_underwriter_decision(inp, result, Outcome.COUNTER_OFFER, smaller, L1, None, None)
    assert ev.required_level == L1
    assert ev.deviation is False or ev.reason_code is None


@pytest.mark.parametrize(
    ("rate", "ok"),
    [("0.1500", True), ("0.1499", False), ("0.2300", True), ("0.2301", False)],
)
def test_rate_corridor_edges(rate: str, ok: bool) -> None:  # noqa: FBT001
    inp, result = basis()  # инвестиционный: база 19%, коридор 15–23%
    ev = evaluate_underwriter_decision(
        inp, result, Outcome.APPROVED, same_terms(inp, Decimal(rate)), L2, None, None
    )
    assert ("RATE_OUT_OF_CORRIDOR" in codes(ev)) is (not ok)
    assert ev.allowed is ok
    assert ev.rate_corridor_min == Decimal("0.15")
    assert ev.rate_corridor_max == Decimal("0.23")


def test_rate_violation_is_hard_and_not_waived_by_l2() -> None:
    inp, result = basis()
    ev = evaluate_underwriter_decision(
        inp,
        result,
        Outcome.APPROVED,
        same_terms(inp, Decimal("0.5")),
        L2,
        "UW_POLICY_EXCEPTION",
        LONG,
    )
    assert not ev.allowed
    assert {v.kind for v in ev.violations if v.code == "RATE_OUT_OF_CORRIDOR"} == {
        ViolationKind.HARD
    }


def test_dscr_between_floors_is_an_exception_that_needs_l2_reason_and_long_comment() -> None:
    inp, result = basis()
    low_flow = with_flow(result, flow_for(inp, result, Decimal("1.2")))  # ниже 1,25, выше 1,15
    base = (inp, low_flow, Outcome.APPROVED, same_terms(inp))
    plain = evaluate_underwriter_decision(*base, L2, None, None)
    assert plain.exception_used
    assert plain.exception_codes == ("DSCR_LOW", "STRESS_DSCR_LOW")
    assert plain.required_level == L2
    assert codes(plain) == {"REASON_REQUIRED", "COMMENT_TOO_SHORT"}
    short = evaluate_underwriter_decision(
        *base, L2, "UW_POLICY_EXCEPTION", "коротко, меньше пятидесяти"
    )
    assert codes(short) == {"COMMENT_TOO_SHORT"}
    assert short.min_comment_chars == 50
    assert evaluate_underwriter_decision(
        *base, L1, "UW_POLICY_EXCEPTION", LONG
    ).violation_codes == ("AUTHORITY_LEVEL_TOO_LOW",)
    ok = evaluate_underwriter_decision(*base, L2, "UW_POLICY_EXCEPTION", LONG)
    assert ok.allowed
    assert ok.deviation


@pytest.mark.parametrize(
    ("dscr", "allowed"),
    [("1.1499", False), ("1.1500", True), ("1.2499", True), ("1.2500", True)],
)
def test_dscr_exception_floor_boundaries(dscr: str, allowed: bool) -> None:  # noqa: FBT001
    inp, result = basis()
    flow = flow_for(inp, result, Decimal(dscr))
    ev = evaluate_underwriter_decision(
        inp,
        with_flow(result, flow),
        Outcome.APPROVED,
        same_terms(inp),
        L2,
        "UW_POLICY_EXCEPTION",
        LONG,
    )
    # поток округлён вниз: «1.1500» даёт чуть меньше порога, поэтому добавляем рубль в запас
    if dscr == "1.1500":
        ev = evaluate_underwriter_decision(
            inp,
            with_flow(result, flow + 1),
            Outcome.APPROVED,
            same_terms(inp),
            L2,
            "UW_POLICY_EXCEPTION",
            LONG,
        )
    assert ev.allowed is allowed
    assert ("DSCR_BELOW_EXCEPTION_FLOOR" in codes(ev)) is (not allowed)


def test_stress_floor_is_checked_separately() -> None:
    inp, result = basis()
    # DSCR 1,2 проходит пол исключения, но при шоке 30% стресс 0,84 < 0,9
    flow = flow_for(inp, result, Decimal("1.2"))
    ev = evaluate_underwriter_decision(
        inp,
        with_flow(result, flow, Decimal("0.3")),
        Outcome.APPROVED,
        same_terms(inp),
        L2,
        "UW_POLICY_EXCEPTION",
        LONG,
    )
    assert "STRESS_BELOW_EXCEPTION_FLOOR" in codes(ev)
    assert not ev.allowed


def test_rejecting_against_recommendation_needs_reason_and_comment() -> None:
    inp, result = basis()
    bare = evaluate_underwriter_decision(inp, result, Outcome.REJECTED, None, L2, None, None)
    assert bare.deviation
    assert codes(bare) == {"REASON_REQUIRED", "COMMENT_TOO_SHORT"}
    ok = evaluate_underwriter_decision(
        inp,
        result,
        Outcome.REJECTED,
        None,
        L1,
        "UW_RISK_HIGHER",
        "Вижу риск, которого нет в модели",
    )
    assert ok.allowed  # 15 млн, грейд A: L1 достаточно, комментарий 20+
    assert ok.rate is None
    assert evaluate_underwriter_decision(
        inp, result, Outcome.REJECTED, None, L1, "UW_RISK_HIGHER", "коротко"
    ).violation_codes == ("COMMENT_TOO_SHORT",)


def test_unknown_reason_code_and_bad_inputs() -> None:
    inp, result = basis()
    ev = evaluate_underwriter_decision(inp, result, Outcome.REJECTED, None, L2, "UW_MAGIC", LONG)
    assert "REASON_UNKNOWN" in codes(ev)
    assert "OUTCOME_NOT_ALLOWED" in codes(
        evaluate_underwriter_decision(inp, result, Outcome.NEEDS_INFO, None, L2, None, None)
    )
    assert "TERMS_REQUIRED" in codes(
        evaluate_underwriter_decision(inp, result, Outcome.APPROVED, None, L2, None, None)
    )
    assert "TERMS_NOT_ALLOWED" in codes(
        evaluate_underwriter_decision(
            inp, result, Outcome.REJECTED, same_terms(inp), L2, None, None
        )
    )
    assert "ACTOR_LEVEL_INVALID" in codes(
        evaluate_underwriter_decision(inp, result, Outcome.REJECTED, None, Level.L0, None, None)
    )


def test_approved_must_match_request_and_counter_must_differ() -> None:
    inp, result = basis()
    other = UnderwriterTerms(Product.INVESTMENT, 9_000_000, inp.application.term_months)
    assert "APPROVED_TERMS_DIFFER" in codes(
        evaluate_underwriter_decision(inp, result, Outcome.APPROVED, other, L2, None, None)
    )
    assert "COUNTER_SAME_AS_REQUEST" in codes(
        evaluate_underwriter_decision(
            inp, result, Outcome.COUNTER_OFFER, same_terms(inp), L2, None, None
        )
    )


def test_catalog_bounds_cannot_be_overridden() -> None:
    inp, result = basis()
    huge = UnderwriterTerms(Product.INVESTMENT, 900_000_000, inp.application.term_months)
    ev = evaluate_underwriter_decision(
        inp, result, Outcome.COUNTER_OFFER, huge, L2, "UW_POLICY_EXCEPTION", LONG
    )
    assert "AMOUNT_OUT_OF_RANGE" in codes(ev)
    assert not ev.allowed


def test_non_manual_engine_result_is_refused() -> None:
    inp = cases.sokolova()
    result = decide(inp)
    assert result.outcome != Outcome.MANUAL_REVIEW
    ev = evaluate_underwriter_decision(inp, result, Outcome.REJECTED, None, L2, "UW_OTHER", LONG)
    assert ev.violation_codes == ("ENGINE_NOT_MANUAL_REVIEW",)


def test_manual_without_financial_assessment_can_only_reject_with_reason_and_authority() -> None:
    inp, result = basis(cases.garipov)
    assert result.outcome == Outcome.NEEDS_INFO
    assert result.features is None
    manual = replace(
        result,
        outcome=Outcome.MANUAL_REVIEW,
        route=Route.MANUAL,
        required_level=L2,
        recommendation=Recommendation(Outcome.NEEDS_INFO),
    )
    assert evaluate_underwriter_decision(
        inp, manual, Outcome.REJECTED, None, L2, "UW_DOCUMENT_ISSUE", LONG
    ).allowed
    missing_reason = evaluate_underwriter_decision(
        inp, manual, Outcome.REJECTED, None, L2, None, None
    )
    assert {"REASON_REQUIRED", "COMMENT_TOO_SHORT"} <= codes(missing_reason)
    assert "AUTHORITY_LEVEL_TOO_LOW" in codes(
        evaluate_underwriter_decision(
            inp, manual, Outcome.REJECTED, None, L1, "UW_DOCUMENT_ISSUE", LONG
        )
    )
    for outcome in (Outcome.APPROVED, Outcome.COUNTER_OFFER):
        denied = evaluate_underwriter_decision(
            inp, manual, outcome, same_terms(inp), L2, "UW_DOCUMENT_ISSUE", LONG
        )
        assert not denied.allowed
        assert "ENGINE_NOT_MANUAL_REVIEW" in codes(denied)


def test_mismatched_inputs_are_refused() -> None:
    inp, result = basis()
    other = cases.zarya()
    ev = evaluate_underwriter_decision(other, result, Outcome.REJECTED, None, L2, "UW_OTHER", LONG)
    assert ev.violation_codes == ("ENGINE_RESULT_MISMATCH",)
