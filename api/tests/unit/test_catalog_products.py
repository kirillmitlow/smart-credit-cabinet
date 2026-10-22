"""T-240: каталог и доступность продуктов компании; те же требования, что в ядре (D-018)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import date

import pytest
import yaml

from app.modules.catalog import CompanyFacts
from app.modules.catalog.facts import product_context
from app.modules.catalog.service import evaluate, get_product, list_products
from app.modules.decisioning import (
    DecisionInput,
    Product,
    ProductContext,
    check_product,
    decide,
    parse_policy,
)
from app.shared.errors import AppError
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

TODAY = cp.TODAY
COMPANY_LEVEL = {"PRODUCT_AGE_MIN", "NOT_BANK_CLIENT"}


def facts_for_persona(inp: DecisionInput) -> CompanyFacts:
    snap = inp.snapshot
    return CompanyFacts(
        registration_date=snap.registry.registration_date,
        is_bank_customer=snap.customer.is_customer,
        customer_since=snap.customer.customer_since,
    )


def test_six_products_with_bounds_and_documents() -> None:
    items = list_products(
        cp.load_policy(), CompanyFacts(date(2015, 1, 1), True, date(2020, 1, 1)), TODAY
    )
    assert [p.code for p in items] == [
        "EXPRESS",
        "WORKING_CAPITAL",
        "CONTRACT",
        "CREDIT_LINE",
        "OVERDRAFT",
        "INVESTMENT",
    ]
    express = items[0]
    assert (express.amount_min_rub, express.amount_max_rub) == (100_000, 3_000_000)
    assert (express.term_min_months, express.term_max_months) == (6, 36)
    assert express.title == "Экспресс-кредит"
    assert express.documents == []
    assert str(express.rate_percent_from) == "24.00"
    assert items[5].documents == ["Договор или счёт от продавца"]
    assert all(p.available for p in items)


def test_overdraft_unavailable_to_non_customer_with_hint() -> None:
    inp = cp.garipov()
    product = get_product(cp.load_policy(), "OVERDRAFT", facts_for_persona(inp), TODAY)
    assert not product.available
    assert [r.code for r in product.unavailable_reasons] == ["NOT_BANK_CLIENT"]
    assert product.hint == "Овердрафт станет доступен после 6 мес. обслуживания у нас"


def test_overdraft_unavailable_to_customer_with_short_history_and_gives_date() -> None:
    inp = cp.quick_start()  # клиент с 21.07.2026: три месяца
    product = get_product(cp.load_policy(), "OVERDRAFT", facts_for_persona(inp), TODAY)
    assert not product.available
    reason = product.unavailable_reasons[0]
    assert reason.code == "NOT_BANK_CLIENT"
    assert reason.available_from == date(2027, 1, 21)


def test_young_business_sees_age_hints_not_dead_end() -> None:
    inp = cp.quick_start()
    items = {p.code: p for p in list_products(cp.load_policy(), facts_for_persona(inp), TODAY)}
    assert items["EXPRESS"].available
    assert items["EXPRESS"].requires_security
    for code in ("WORKING_CAPITAL", "CREDIT_LINE", "INVESTMENT"):
        assert not items[code].available
        assert items[code].unavailable_reasons[0].code == "PRODUCT_AGE_MIN"
        assert items[code].hint is not None
        assert "станет доступен" in items[code].hint
    assert items["CREDIT_LINE"].unavailable_reasons[0].available_from == date(2028, 7, 21)


def test_sokolova_sees_everything_available() -> None:
    items = list_products(cp.load_policy(), facts_for_persona(cp.sokolova()), TODAY)
    assert all(p.available for p in items)
    assert not any(p.requires_security for p in items)


def test_unknown_product_is_404() -> None:
    with pytest.raises(AppError) as caught:
        get_product(cp.load_policy(), "MAGIC", CompanyFacts(), TODAY)
    assert caught.value.status == 404


PERSONAS: list[Callable[[], DecisionInput]] = [
    cp.sokolova,
    cp.snabkontrakt,
    cp.stankoprom,
    cp.garipov,
    cp.romashka,
    cp.zarya,
    cp.quick_start,
    cp.t_base,
    cp.t_young_collateral,
]


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda f: f.__name__)
def test_catalog_availability_equals_core_product_rules(
    persona: Callable[[], DecisionInput],
) -> None:
    """Для каждой персоны и каждого продукта: каталог и ядро видят одни и те же нарушения."""
    inp = persona()
    policy = inp.policy
    facts = facts_for_persona(inp)
    snap = inp.snapshot
    core_ctx = ProductContext(
        app_today=inp.context.app_today,
        business_age_months=_age(snap.registry.registration_date, inp.context.app_today),
        registration_date=snap.registry.registration_date,
        is_bank_customer=snap.customer.is_customer,
        customer_turnover_months=len(snap.turnover.months),
        collateral_provided=False,
        security_confirmed=False,
    )
    catalog_ctx = product_context(facts, inp.context.app_today)
    for code, cfg in policy.catalog.products.items():
        in_catalog = {r.code for r in evaluate(policy, code, catalog_ctx).blocking}
        in_core = {
            r.code
            for r in check_product(
                policy,
                Product(code),
                cfg.amount_min_rub,
                max(cfg.term_min_months, min(12, cfg.term_max_months)),
                core_ctx,
            )
        } & COMPANY_LEVEL
        assert in_catalog == in_core, (persona.__name__, code)


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda f: f.__name__)
def test_requested_product_is_not_shown_unavailable_if_decide_accepts_it(
    persona: Callable[[], DecisionInput],
) -> None:
    """«Показали, а потом отказали» невозможно: нет нарушений в каталоге ⇔ их нет в decide()."""
    inp = persona()
    result = decide(inp)
    in_decide = {r.code for r in result.reasons} & COMPANY_LEVEL
    product = get_product(
        inp.policy, inp.application.product.value, facts_for_persona(inp), inp.context.app_today
    )
    in_catalog = {r.code for r in product.unavailable_reasons}
    assert in_catalog == in_decide, persona.__name__


def test_new_requirement_is_a_config_change_not_a_code_change() -> None:
    from tests.fixtures.core_personas import POLICY_PATH

    data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(data)
    changed["catalog"]["products"]["EXPRESS"]["min_business_age_months"] = 24
    facts = CompanyFacts(registration_date=date(2025, 10, 21))  # 12 месяцев
    before = get_product(parse_policy(data), "EXPRESS", facts, TODAY)
    after = get_product(parse_policy(changed), "EXPRESS", facts, TODAY)
    assert before.available
    assert not after.available
    assert after.unavailable_reasons[0].code == "PRODUCT_AGE_MIN"


def _age(registered: date | None, today: date) -> int | None:
    if registered is None:
        return None
    months = (today.year - registered.year) * 12 + today.month - registered.month
    return months - (1 if today.day < registered.day else 0)
