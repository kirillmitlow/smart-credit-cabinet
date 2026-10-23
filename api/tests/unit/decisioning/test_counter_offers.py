"""Встречные предложения (T-297, 30-10): три карточки, границы, продукты, залог, полномочия.

Числа СнабКонтракта сверяются с оракулом 30-17 в `test_oracle_30_17.py`; здесь — поведение
оптимизатора на других входах и его пределы.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.modules.decisioning import add_months, counter_offers, decide
from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.counter_offers import CounterOfferSearch
from app.modules.decisioning.policy import Policy
from app.modules.decisioning.types import DecisionInput, Grade, Outcome, Product
from tests.fixtures import core_personas as cp
from tests.fixtures.counter_offers import PASSING, resubmit

pytestmark = pytest.mark.unit

D = Decimal
SNAB = cp.snabkontrakt()


def snab(**changes: object) -> DecisionInput:
    return cp.with_application(SNAB, **changes)


def with_low_auto_limits(inp: DecisionInput, limit_b: int) -> DecisionInput:
    """Авто-лимит каждого продукта (колонка грейда B) заменён на `limit_b`."""
    policy: Policy = inp.policy
    products = {
        code: cfg.model_copy(update={"auto_limit_b_rub": limit_b})
        for code, cfg in policy.catalog.products.items()
    }
    catalog = policy.catalog.model_copy(update={"products": products})
    return replace(inp, policy=policy.model_copy(update={"catalog": catalog}))


# ---------------------------------------------------------------- набор карточек


def test_request_that_passes_has_no_counter_offers() -> None:
    result = decide(cp.sokolova())
    assert result.outcome == Outcome.APPROVED
    assert result.variants == ()
    assert result.variants_status == "NOT_APPLICABLE"


def test_snabkontrakt_set_is_three_different_cards_with_one_recommended() -> None:
    result = decide(SNAB)
    keys = {(v.product, v.amount_rub, v.term_months, v.security_required) for v in result.variants}
    assert len(result.variants) == len(keys) == 3
    assert [v.recommended for v in result.variants] == [True, False, False]
    nearest = min(result.variants, key=lambda v: v.distance or D(99))
    assert nearest.recommended


def test_every_snabkontrakt_card_resubmitted_is_not_worse_than_manual_review() -> None:
    for variant in decide(SNAB).variants:
        again = resubmit(SNAB, variant)
        assert again.outcome in PASSING, variant.kind
        assert again.variants == ()


def test_less_amount_is_the_largest_step_that_keeps_the_margin_over_gray_zones() -> None:
    """30-11: 3,45 млн на 12 мес — DSCR 1,306 и стресс 1,045 (серая зона), поэтому 3,4 млн."""
    flow, existing, shock = 1_200_000, 600_000, D("0.2")
    rate = D("0.195")
    low = lm.annuity_payment(3_450_000, rate, 12)
    assert lm.dscr(flow, existing, low) < D("1.31")
    assert lm.stress_dscr(flow, existing, low, shock) < D("1.05")
    card = next(v for v in decide(SNAB).variants if v.kind == "LESS_AMOUNT")
    assert card.amount_rub == 3_400_000
    assert card.stress_dscr is not None
    assert card.stress_dscr >= D("1.05")


def test_longer_term_skips_the_gray_zone_node_of_the_grid() -> None:
    """30 мес. даёт DSCR 1,278 (серая зона), поэтому срок 36, а не математический минимум 34."""
    card = next(v for v in decide(SNAB).variants if v.kind == "LONGER_TERM")
    assert card.term_months == 36
    assert card.dscr is not None
    assert card.dscr >= D("1.3125")


# ---------------------------------------------------------------- продукты и пределы


def test_credit_line_request_gets_the_product_cap_and_the_contract_card() -> None:
    """Линия: платёж не зависит от срока, а сумма ограничена половиной месячной выручки."""
    result = decide(snab(product=Product.CREDIT_LINE, term_months=24))
    assert result.reason_codes == ("LIMIT_ABOVE_CAP",)
    kinds = {v.kind: v for v in result.variants}
    assert set(kinds) == {"LESS_AMOUNT", "OTHER_PRODUCT"}
    assert (kinds["LESS_AMOUNT"].amount_rub, kinds["LESS_AMOUNT"].term_months) == (7_500_000, 24)
    assert kinds["OTHER_PRODUCT"].product == Product.CONTRACT


def without_contracts(inp: DecisionInput) -> DecisionInput:
    """Компания без своих контрактов в ЕИС."""
    snapshot = replace(inp.snapshot, contracts=replace(inp.snapshot.contracts, contracts=()))
    return replace(inp, snapshot=snapshot)


def test_own_contract_without_number_still_gives_the_contract_card() -> None:
    """Q-148: заявка на оборотный без номера, но свой контракт в ЕИС есть — карточка `CONTRACT`."""
    result = decide(snab(contract_registry_number=None))
    other = next(v for v in result.variants if v.kind == "OTHER_PRODUCT")
    assert (other.product, other.amount_rub, other.term_months) == (Product.CONTRACT, 8_000_000, 4)
    number = SNAB.snapshot.contracts.contracts[0].registry_number
    assert any(number in r for r in other.requirements)


def test_without_a_registered_contract_the_third_card_is_another_product() -> None:
    result = decide(without_contracts(snab(contract_registry_number=None)))
    other = next(v for v in result.variants if v.kind == "OTHER_PRODUCT")
    assert other.product == Product.CREDIT_LINE  # контракта нет, продукт под контракт не предлагаем
    assert other.requirements == ()


def test_term_outside_the_product_range_gives_a_card_with_another_term() -> None:
    result = decide(snab(term_months=48))
    assert result.reason_codes == ("AMOUNT_OUT_OF_RANGE",)
    card = next(v for v in result.variants if v.kind == "OTHER_TERM")
    assert (card.amount_rub, card.term_months) == (8_000_000, 36)  # короче запрошенного
    assert card.distance == 0  # срок не вырос, сумма и продукт те же


def test_express_request_gets_cards_inside_the_express_limits() -> None:
    result = decide(snab(product=Product.EXPRESS, amount_rub=3_000_000, term_months=6))
    assert result.outcome == Outcome.COUNTER_OFFER
    longer = next(v for v in result.variants if v.kind == "LONGER_TERM")
    assert (longer.amount_rub, longer.term_months, longer.rate) == (3_000_000, 12, D("0.215"))
    less = next(v for v in result.variants if v.kind == "LESS_AMOUNT")
    assert less.term_months == 6
    assert less.amount_rub < 3_000_000
    assert all(v.amount_rub <= 3_000_000 for v in result.variants if v.product == Product.EXPRESS)


def test_no_offer_when_current_payments_leave_no_room_for_any_loan() -> None:
    inp = SNAB
    report = cp.company_subject(inp).report
    assert report is not None
    heavy = cp.with_company_report(inp, replace(report, monthly_payments_rub=1_000_000))
    result = decide(heavy)
    assert result.outcome == Outcome.REJECTED
    assert result.reasons[0].code == "NO_OFFER_FOUND"
    assert result.variants == ()


def test_variants_above_the_auto_limit_go_to_a_human_not_to_the_client() -> None:
    """C-04: проходящие встречные есть, но выше полномочий автомата — `MANUAL_REVIEW`."""
    result = decide(with_low_auto_limits(SNAB, 20_000))
    assert result.outcome == Outcome.MANUAL_REVIEW
    assert result.variants == ()
    assert "AMOUNT_ABOVE_AUTO_LIMIT" in result.reason_codes
    assert result.recommendation is not None
    assert result.recommendation.outcome == Outcome.COUNTER_OFFER


def test_auto_limit_cuts_the_amount_of_a_card() -> None:
    """Лимит грейда A у оборотного 10 млн, у экспресса 6 млн: карточки не выше лимита продукта."""
    result = decide(with_low_auto_limits(SNAB, 2_000_000))  # A: 4 млн
    assert result.outcome == Outcome.COUNTER_OFFER
    assert result.numbers.grade == Grade.A
    assert all(v.amount_rub <= 4_000_000 for v in result.variants)


# ---------------------------------------------------------------- молодой бизнес и залог


@pytest.fixture
def searched(monkeypatch: pytest.MonkeyPatch) -> Callable[[DecisionInput], CounterOfferSearch]:
    """Итог поиска встречных для входа: `decide` отдаёт карточки только при автоматическом исходе."""
    real = counter_offers.search_counter_offers
    box: list[CounterOfferSearch] = []

    def spy(*args: Any, **kwargs: Any) -> CounterOfferSearch:
        box.append(real(*args, **kwargs))
        return box[-1]

    monkeypatch.setattr(counter_offers, "search_counter_offers", spy)

    def run(inp: DecisionInput) -> CounterOfferSearch:
        box.clear()
        decide(inp)
        return box[-1]

    return run


def young_hard() -> DecisionInput:
    """Бизнесу 3 месяца, просит оборотный (нужен год): запрос не проходит по правилу продукта."""
    base = cp.t_base()
    registry = replace(base.snapshot.registry, registration_date=add_months(cp.TODAY, -3))
    inp = cp.with_snapshot(base, registry=registry)
    return cp.with_application(inp, product=Product.WORKING_CAPITAL, amount_rub=1_000_000)


def test_young_business_needs_security_in_every_candidate(
    searched: Callable[[DecisionInput], CounterOfferSearch],
) -> None:
    """Бизнес моложе 6 мес. без обеспечения: вариант без залога снова стал бы условным встречным."""
    inp = young_hard()
    search = searched(inp)
    result = decide(inp)
    assert search.feasible
    assert result.outcome == Outcome.MANUAL_REVIEW  # молодой бизнес — грейд C, решает человек
    assert result.recommendation is not None
    assert result.recommendation.outcome == Outcome.COUNTER_OFFER
    # Проходящий вариант есть только выше полномочий автомата (грейд C) и только с залогом
    assert search.above_authority
    assert search.variants == ()


def test_added_collateral_card_is_marked_priced_and_explained(
    searched: Callable[[DecisionInput], CounterOfferSearch],
) -> None:
    """Штраф за залог 0: ближайшая связка «тот же продукт, но с залогом» (в политике штраф 1,5)."""
    inp = without_contracts(
        cp.with_application(SNAB, contract_registry_number=None, amount_rub=12_000_000)
    )
    policy: Policy = inp.policy
    free = policy.counter_offers.weights.model_copy(update={"security": D(0)})
    counter = policy.counter_offers.model_copy(update={"weights": free})
    inp = replace(inp, policy=policy.model_copy(update={"counter_offers": counter}))
    third = searched(inp).variants[-1]
    assert third.kind == "WITH_SECURITY"
    assert third.security_required
    assert (third.product, third.amount_rub, third.term_months) == (
        Product.WORKING_CAPITAL,
        8_500_000,  # наибольшая сумма с запасом над серыми зонами на 36 мес.
        36,
    )
    assert third.rate == D("0.195")  # A с залогом: 15 + 0,35 + 2 + 2 = 19,35 → 19,5%
    assert "залог" in third.requirements[0].lower()
    assert resubmit(inp, third).outcome in PASSING


# ---------------------------------------------------------------- быстродействие


def test_search_takes_tens_of_milliseconds() -> None:
    inp = SNAB
    decide(inp)  # прогрев
    started = time.perf_counter()
    for _ in range(10):
        decide(inp)
    assert (time.perf_counter() - started) / 10 < 0.05
