"""T-362: свойства ручного решения: «никогда нельзя» и детерминизм (30-11)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.decisioning import (
    UnderwriterTerms,
    decide,
    evaluate_underwriter_decision,
)
from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.types import Level, Outcome
from tests.fixtures import core_personas as cases

INP = cases.stankoprom()
RESULT = decide(INP)
assert RESULT.features is not None
FEATS = RESULT.features
LONG = "Комментарий андеррайтера длиннее пятидесяти знаков, чтобы пройти любую проверку длины."


@settings(max_examples=150, deadline=None)
@given(
    flow=st.integers(min_value=100_000, max_value=3_000_000),
    shock=st.sampled_from([Decimal("0.1"), Decimal("0.2"), Decimal("0.3")]),
    rate=st.decimals(min_value="0.10", max_value="0.30", places=3),
    amount=st.integers(min_value=100, max_value=400).map(lambda n: n * 50_000),
    term=st.integers(min_value=6, max_value=84),
    level=st.sampled_from([Level.L1, Level.L2]),
)
def test_allowed_decision_never_breaks_hard_limits(
    flow: int, shock: Decimal, rate: Decimal, amount: int, term: int, level: Level
) -> None:
    result = replace(RESULT, features=replace(FEATS, flow_model_rub=flow, stress_shock=shock))
    terms = UnderwriterTerms(INP.application.product, amount, term, rate)
    ev = evaluate_underwriter_decision(
        INP, result, Outcome.COUNTER_OFFER, terms, level, "UW_POLICY_EXCEPTION", LONG
    )
    again = evaluate_underwriter_decision(
        INP, result, Outcome.COUNTER_OFFER, terms, level, "UW_POLICY_EXCEPTION", LONG
    )
    assert ev == again  # детерминизм
    if not ev.allowed:
        return
    aff = INP.policy.affordability
    uw = INP.policy.underwriter
    assert ev.rate_corridor_min is not None
    assert ev.rate_corridor_max is not None
    assert ev.rate_corridor_min <= rate <= ev.rate_corridor_max
    assert ev.payment_rub is not None
    assert ev.payment_rub > 0
    total = FEATS.existing_payments_rub + ev.payment_rub
    dscr = lm.dscr(flow, FEATS.existing_payments_rub, ev.payment_rub)
    stress = Decimal(flow) * (1 - shock) / total
    assert dscr >= uw.exception_dscr_min.value
    assert stress >= uw.exception_stress_min.value
    if dscr < aff.dscr_min.value or stress < aff.stress_dscr_min.value:
        assert ev.exception_used
        assert ev.required_level == Level.L2
    assert (level == Level.L2) or ev.required_level == Level.L1
    cfg = INP.policy.product_config(terms.product.value)
    assert cfg.amount_min_rub <= amount <= cfg.amount_max_rub
    assert cfg.term_min_months <= term <= cfg.term_max_months
