"""Property-тесты встречных предложений (T-297, 70-02): INV-40…43 и INV-50.

Вход — хороший клиент, который просит больше, чем тянет (`counter_offer_params`): запрос часто не
проходит, и оптимизатор строит карточки. Нарушение инварианта чинится в оптимизаторе или в
политике, а не подгонкой теста.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 — запуск того же интерпретатора с другим PYTHONHASHSEED
import sys
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.modules.decisioning import counter_offers, decide
from app.modules.decisioning.products import auto_limit
from app.modules.decisioning.types import DecisionInput, DecisionResult, Outcome, Product
from tests.fixtures import core_personas as cp
from tests.fixtures.counter_offers import PASSING, resubmit
from tests.strategies.decisioning import RequestParams, counter_offer_params

pytestmark = pytest.mark.property

D = Decimal
POLICY = cp.load_policy()
no_deadline = settings(deadline=None)
GRID = set(POLICY.counter_offers.term_grid_months.value)
STEP = POLICY.counter_offers.amount_step_rub.value
API_DIR = Path(__file__).resolve().parents[2]


def counter(params: RequestParams) -> tuple[DecisionInput, DecisionResult]:
    inp = params.to_input()
    result = decide(inp)
    assume(result.outcome == Outcome.COUNTER_OFFER and result.variants_status == "READY")
    return inp, result


# ---------------------------------------------------------------- INV-40


@no_deadline
@given(counter_offer_params())
def test_inv_40_every_card_resubmitted_as_a_request_is_not_worse_than_manual_review(
    params: RequestParams,
) -> None:
    inp, result = counter(params)
    for variant in result.variants:
        again = resubmit(inp, variant)
        assert again.outcome in PASSING, (variant, again.reason_codes)


# ---------------------------------------------------------------- INV-41


@no_deadline
@given(counter_offer_params())
def test_inv_41_at_most_three_distinct_cards_inside_product_limits_and_margins(
    params: RequestParams,
) -> None:
    inp, result = counter(params)
    app, feats, numbers = inp.application, result.features, result.numbers
    assert feats is not None
    assert 1 <= len(result.variants) <= POLICY.counter_offers.max_cards.value
    keys = [(v.product, v.amount_rub, v.term_months, v.security_required) for v in result.variants]
    assert len(set(keys)) == len(keys)
    assert len({v.kind for v in result.variants}) == len(keys)  # каждая карточка — свой тип
    for v in result.variants:
        cfg = POLICY.product_config(v.product.value)
        assert cfg.amount_min_rub <= v.amount_rub <= min(cfg.amount_max_rub, app.amount_rub)
        assert cfg.term_min_months <= v.term_months <= cfg.term_max_months
        assert v.amount_rub % STEP == 0 or v.amount_rub == app.amount_rub
        assert v.term_months in GRID or v.term_months == app.term_months  # CONTRACT — ниже
        # запас над серыми зонами 30-11 и тест на «сильнее серой зоны» стресса
        assert v.dscr is not None
        assert v.stress_dscr is not None
        assert v.dscr >= D("1.30")
        assert v.stress_dscr >= D("1.05")
        flow = feats.flow_model_rub or 0
        shock = numbers.stress_shock
        assert shock is not None
        assert D(flow) * (1 - shock) / (feats.existing_payments_rub + v.payment_rub) >= D("1.0499")
        if feats.revenue_annual_rub:
            assert D(feats.total_debt_rub + v.amount_rub) / D(feats.revenue_annual_rub) < D("0.95")
        assert numbers.grade is not None
        limit = auto_limit(POLICY, v.product, numbers.grade)
        assert limit is None or v.amount_rub <= limit


# ---------------------------------------------------------------- INV-42


@no_deadline
@given(counter_offer_params())
def test_inv_42_if_the_request_passes_there_are_no_counter_offers(params: RequestParams) -> None:
    inp = params.to_input()
    result = decide(inp)
    if result.outcome == Outcome.APPROVED:
        assert result.variants == ()
        assert result.variants_status == "NOT_APPLICABLE"
    for (
        variant
    ) in result.variants:  # условия любой карточки, поданные как запрос, встречных не дают
        again = resubmit(inp, variant)
        if again.outcome == Outcome.APPROVED:
            assert again.variants == ()


# ---------------------------------------------------------------- INV-43


@no_deadline
@given(counter_offer_params())
def test_inv_43_exactly_one_recommended_card_and_it_is_the_nearest(params: RequestParams) -> None:
    _, result = counter(params)
    marked = [v for v in result.variants if v.recommended]
    assert len(marked) == 1
    assert marked[0] in result.variants
    distances = [v.distance for v in result.variants]
    assert all(d is not None for d in distances)
    assert marked[0].distance == min(d for d in distances if d is not None)


# ---------------------------------------------------------------- INV-50


@no_deadline
@given(counter_offer_params())
def test_inv_50_counter_offers_are_deterministic_on_the_same_input(params: RequestParams) -> None:
    inp = params.to_input()
    first, second = decide(inp), decide(inp)
    assert first.variants == second.variants
    assert repr(first) == repr(second)


def _variants_under_hash_seed(seed: str) -> str:
    code = (
        "from app.modules.decisioning import decide\n"
        "from tests.fixtures.core_personas import PERSONAS\n"
        "print(repr(decide(PERSONAS['snabkontrakt']()).variants))\n"
    )
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(API_DIR)}
    done = subprocess.run(  # noqa: S603 — свой интерпретатор и фиксированный код
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=API_DIR,
    )
    return done.stdout


def test_inv_50_cards_do_not_depend_on_the_hash_seed() -> None:
    assert _variants_under_hash_seed("1") == _variants_under_hash_seed("2718")


# ---------------------------------------------------------------- СнабКонтракт: все продукты, включая контракт

SNAB_BOUNDS = {
    Product.EXPRESS: (100_000, 3_000_000, 6, 36),
    Product.WORKING_CAPITAL: (500_000, 30_000_000, 3, 36),
    Product.CREDIT_LINE: (1_000_000, 50_000_000, 12, 36),
    Product.CONTRACT: (100_000, 100_000_000, 1, 12),
}


@st.composite
def snab_requests(draw: st.DrawFn) -> DecisionInput:
    product = draw(st.sampled_from(sorted(SNAB_BOUNDS, key=lambda p: p.value)))
    lo, hi, tlo, thi = SNAB_BOUNDS[product]
    amount = draw(st.integers(lo // STEP, min(hi, 40_000_000) // STEP)) * STEP
    term = draw(st.integers(tlo, thi))
    return cp.with_application(
        cp.snabkontrakt(), product=product, amount_rub=amount, term_months=term
    )


@no_deadline
@given(snab_requests())
def test_inv_40_41_43_on_snabkontrakt_across_products(inp: DecisionInput) -> None:
    result = decide(inp)
    assume(result.outcome == Outcome.COUNTER_OFFER and result.variants_status == "READY")
    assert 1 <= len(result.variants) <= 3
    assert len({v.kind for v in result.variants}) == len(result.variants)
    assert sum(v.recommended for v in result.variants) == 1
    for variant in result.variants:
        assert resubmit(inp, variant).outcome in PASSING, variant
        if variant.product == Product.CONTRACT:  # срок не из сетки: не дольше оплаты контракта + 1
            assert variant.term_months <= 4
            assert variant.requirements


# ---------------------------------------------------------------- оптимизатор против полного перебора


def _spied_search(inp: DecisionInput) -> counter_offers._Search:
    """Поиск, настроенный теми же входами, что получил `decide` (авто-лимит включён)."""
    real = counter_offers.search_counter_offers
    seen: dict[str, Any] = {}

    def spy(policy: Any, app: Any, rate: Any, feats: Any, **kw: Any) -> Any:
        seen.update(policy=policy, app=app, feats=feats, kw=kw)
        return real(policy, app, rate, feats, **kw)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(counter_offers, "search_counter_offers", spy)
        decide(inp)
    assume(bool(seen))
    kw = seen["kw"]
    return counter_offers._Search(
        seen["policy"],
        seen["app"],
        seen["feats"],
        kw["grade"],
        kw["product_ctx"],
        kw["contract"],
        kw["inflow_average"],
        kw["request"],
        limit_on=True,
    )


def _amounts(search: counter_offers._Search) -> Iterator[int]:
    asked = search.app.amount_rub
    yield from range(STEP, asked, STEP)
    yield asked


@settings(deadline=None, max_examples=20)
@given(counter_offer_params().map(lambda p: replace(p, amount_rub=min(p.amount_rub, 4_000_000))))
def test_bisection_and_distance_choice_agree_with_a_full_scan(params: RequestParams) -> None:
    """Проходящие суммы связки — отрезок снизу, а ближе всего к запросу — его верхний конец."""
    # До 80 сумм на связку задаём конструктивно: отбрасывание больших запросов
    # вместе с отсутствием запуска поиска превышало лимит фильтрации Hypothesis.
    search = _spied_search(params.to_input())
    for product in (search.app.product, Product.EXPRESS, Product.WORKING_CAPITAL):
        for term in search.terms(product):
            group = search.group(product, term, added=False)
            passing = [a for a in _amounts(search) if search.passes(group, a)]
            found = search.best_amount(group, search.app.amount_rub)
            assert found == (max(passing) if passing else None)
            if passing:
                best = min(
                    (search.candidate(group, a) for a in passing),
                    key=lambda c: (c.distance, -c.amount),
                )
                assert best.amount == found
