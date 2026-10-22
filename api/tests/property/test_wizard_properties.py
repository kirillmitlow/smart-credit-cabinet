"""T-242, свойство: любые ответы дают продукт, прошедший требования, либо «каталог с подсказкой»."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.catalog import CompanyFacts
from app.modules.catalog.facts import product_context
from app.modules.catalog.schemas import WizardAnswers, WizardOutcome
from app.modules.catalog.service import evaluate
from app.modules.catalog.wizard import recommend
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.property

TODAY = cp.TODAY
FACTS = [
    CompanyFacts(date(2018, 1, 1), True, date(2019, 1, 1)),
    CompanyFacts(date(2018, 1, 1), False, None),
    CompanyFacts(date(2018, 1, 1), True, date(2026, 7, 21)),
    CompanyFacts(date(2026, 7, 21), True, date(2026, 7, 21)),
    CompanyFacts(None, False, None),
]

answers = st.builds(
    WizardAnswers,
    purpose=st.sampled_from(
        ["EQUIPMENT", "GOODS", "ORDER", "GAP", "GROWTH", "OTHER", "UNKNOWN", None]
    ),
    amount_rub=st.one_of(st.none(), st.integers(min_value=1, max_value=200_000_000)),
    frequency=st.sampled_from(["ONCE", "REGULAR", "UNKNOWN", None]),
    payback_horizon=st.sampled_from(
        ["DAYS", "WEEKS", "MONTHS_1_3", "MONTHS_3_12", "OVER_YEAR", "UNKNOWN", None]
    ),
    gov_contract=st.sampled_from(["YES", "NO", "UNKNOWN", None]),
    urgency=st.sampled_from(["NOW", "WEEK", "NO_RUSH", "UNKNOWN", None]),
    term_months=st.one_of(st.none(), st.integers(min_value=1, max_value=120)),
    collateral=st.sampled_from(["NONE", "NOT_SURE", "UNKNOWN", None]),
)


@given(answers, st.sampled_from(FACTS))
def test_always_product_or_catalog_hint(a: WizardAnswers, facts: CompanyFacts) -> None:
    policy = cp.load_policy()
    result = recommend(policy, a, facts, TODAY)
    if result.outcome is WizardOutcome.RECOMMENDED:
        assert result.primary is not None
        ctx = product_context(facts, TODAY)
        for card in (result.primary, result.alternative):
            if card is not None:
                assert evaluate(policy, card.product_code, ctx, a.amount_rub, a.term_months).ok
        if result.alternative is not None:
            assert result.alternative.product_code != result.primary.product_code
    else:
        assert result.primary is None
        assert result.alternative is None
        assert result.hint


@given(answers, st.sampled_from(FACTS))
def test_result_does_not_depend_on_urgency_or_call_order(
    a: WizardAnswers, facts: CompanyFacts
) -> None:
    """Срочность меняет порядок показа, но не продукт (10-07); повтор даёт то же самое."""
    policy = cp.load_policy()
    other = a.model_copy(update={"urgency": "NOW"})
    first = recommend(policy, a, facts, TODAY)
    assert first == recommend(policy, a, facts, TODAY)
    assert first == recommend(policy, other, facts, TODAY)
