"""T-242: таблица «ответы → продукт» из 10-07 проверяется один в один; персоны; «не знаю»."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.catalog import CompanyFacts
from app.modules.catalog.schemas import DecisionTime, WizardAnswers, WizardOutcome, WizardResult
from app.modules.catalog.wizard import recommend
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

TODAY = cp.TODAY
MILLION = 1_000_000

# Зрелая компания, клиент банка давно: все требования продуктов выполнены
OLD_CLIENT = CompanyFacts(date(2018, 1, 1), True, date(2019, 1, 1))
OLD_NON_CLIENT = CompanyFacts(date(2018, 1, 1), False, None)
NEW_CLIENT = CompanyFacts(date(2018, 1, 1), True, date(2026, 7, 21))  # клиент 3 месяца
YOUNG = CompanyFacts(date(2026, 7, 21), True, date(2026, 7, 21))


def run(facts: CompanyFacts = OLD_CLIENT, **answers: Any) -> WizardResult:
    return recommend(cp.load_policy(), WizardAnswers(**answers), facts, TODAY)


def products(result: WizardResult) -> tuple[str | None, str | None]:
    return (
        result.primary.product_code if result.primary else None,
        result.alternative.product_code if result.alternative else None,
    )


# (строка таблицы 10-07, ответы, факты, основной, альтернатива)
TABLE: list[tuple[str, dict[str, Any], CompanyFacts, str, str | None]] = [
    (
        "Оборудование ≤ 3 млн",
        {"purpose": "EQUIPMENT", "amountRub": 2 * MILLION},
        OLD_CLIENT,
        "EXPRESS",
        "INVESTMENT",
    ),
    (
        "Оборудование = 3 млн",
        {"purpose": "EQUIPMENT", "amountRub": 3 * MILLION},
        OLD_CLIENT,
        "EXPRESS",
        "INVESTMENT",
    ),
    (
        "Оборудование > 3 млн",
        {"purpose": "EQUIPMENT", "amountRub": 15 * MILLION},
        OLD_CLIENT,
        "INVESTMENT",
        None,
    ),
    (
        "Товар, разово",
        {"purpose": "GOODS", "frequency": "ONCE", "amountRub": 8 * MILLION},
        OLD_CLIENT,
        "WORKING_CAPITAL",
        None,
    ),
    (
        "Товар, разово, до 3 млн",
        {"purpose": "GOODS", "frequency": "ONCE", "amountRub": 2 * MILLION},
        OLD_CLIENT,
        "WORKING_CAPITAL",
        "EXPRESS",
    ),
    (
        "Товар, регулярно",
        {"purpose": "GOODS", "frequency": "REGULAR", "amountRub": 5 * MILLION},
        OLD_CLIENT,
        "CREDIT_LINE",
        "WORKING_CAPITAL",
    ),
    (
        "Заказ, госзаказ",
        {"purpose": "ORDER", "govContract": "YES", "amountRub": 8 * MILLION},
        OLD_CLIENT,
        "CONTRACT",
        "WORKING_CAPITAL",
    ),
    (
        "Заказ, регулярно",
        {"purpose": "ORDER", "govContract": "NO", "frequency": "REGULAR", "amountRub": 5 * MILLION},
        OLD_CLIENT,
        "CREDIT_LINE",
        "CONTRACT",
    ),
    (
        "Нехватка, дни, клиент банка",
        {"purpose": "GAP", "paybackHorizon": "DAYS", "amountRub": 300_000},
        OLD_CLIENT,
        "OVERDRAFT",
        "EXPRESS",
    ),
    (
        "Нехватка, дни, не клиент",
        {"purpose": "GAP", "paybackHorizon": "DAYS", "amountRub": 300_000},
        OLD_NON_CLIENT,
        "EXPRESS",
        None,
    ),
    (
        "Нехватка, недели, часто",
        {
            "purpose": "GAP",
            "paybackHorizon": "WEEKS",
            "frequency": "REGULAR",
            "amountRub": 2 * MILLION,
        },
        OLD_CLIENT,
        "CREDIT_LINE",
        "EXPRESS",
    ),
    (
        "Развитие ≤ 3 млн",
        {"purpose": "GROWTH", "amountRub": 2 * MILLION},
        OLD_CLIENT,
        "EXPRESS",
        "WORKING_CAPITAL",
    ),
    (
        "Развитие > 3 млн, окупится за год",
        {"purpose": "GROWTH", "amountRub": 6 * MILLION, "paybackHorizon": "MONTHS_3_12"},
        OLD_CLIENT,
        "WORKING_CAPITAL",
        None,
    ),
    (
        "Развитие > 3 млн, дольше года",
        {"purpose": "GROWTH", "amountRub": 6 * MILLION, "paybackHorizon": "OVER_YEAR"},
        OLD_CLIENT,
        "INVESTMENT",
        None,
    ),
    ("Другое ≤ 3 млн", {"purpose": "OTHER", "amountRub": 2 * MILLION}, OLD_CLIENT, "EXPRESS", None),
    (
        "Бизнесу < 6 мес.: «На запуск»",
        {"purpose": "EQUIPMENT", "amountRub": MILLION},
        YOUNG,
        "EXPRESS",
        None,
    ),
]


@pytest.mark.parametrize(
    ("name", "answers", "facts", "primary", "alternative"), TABLE, ids=[r[0] for r in TABLE]
)
def test_decision_table_row(
    name: str, answers: dict[str, Any], facts: CompanyFacts, primary: str, alternative: str | None
) -> None:
    result = run(facts, **answers)
    assert result.outcome is WizardOutcome.RECOMMENDED, name
    assert products(result) == (primary, alternative), name


def test_not_a_client_gets_express_and_overdraft_hint() -> None:
    result = run(OLD_NON_CLIENT, purpose="GAP", paybackHorizon="DAYS", amountRub=300_000)
    assert result.rule_id == "GAP_DAYS_NOT_CLIENT"
    assert result.hint == "Овердрафт станет доступен после 6 мес. обслуживания у нас"


def test_client_with_short_turnover_loses_overdraft_but_reason_is_available() -> None:
    result = run(NEW_CLIENT, purpose="GAP", paybackHorizon="DAYS", amountRub=300_000)
    assert result.rule_id == "GAP_DAYS_CLIENT"
    assert products(result) == ("EXPRESS", None)  # овердрафт не основной
    assert result.rejected[0].product_code == "OVERDRAFT"
    assert result.rejected[0].reasons[0].code == "NOT_BANK_CLIENT"
    assert result.rejected[0].reasons[0].available_from == date(2027, 1, 21)
    assert result.hint is not None
    assert "станет доступен" in result.hint


def test_other_above_express_limit_is_catalog_with_hint() -> None:
    result = run(purpose="OTHER", amountRub=5 * MILLION)
    assert result.outcome is WizardOutcome.CATALOG_HINT
    assert result.primary is None
    assert result.rejected[0].product_code == "EXPRESS"
    assert result.rejected[0].reasons[0].code == "AMOUNT_OUT_OF_RANGE"
    assert result.hint


def test_start_path_for_young_business_is_manual_with_security() -> None:
    result = run(YOUNG, purpose="OTHER", amountRub=MILLION)
    assert result.start_path
    assert result.rule_id == "START_PATH"
    assert result.primary is not None
    assert result.primary.decision_time is DecisionTime.MANUAL
    assert result.primary.requires_security


@pytest.mark.parametrize(
    ("persona", "answers", "expected"),
    [
        (cp.sokolova, {"purpose": "GROWTH", "amountRub": 500_000}, "EXPRESS"),
        (
            cp.snabkontrakt,
            {"purpose": "GOODS", "frequency": "ONCE", "amountRub": 8 * MILLION},
            "WORKING_CAPITAL",
        ),
        (cp.stankoprom, {"purpose": "EQUIPMENT", "amountRub": 15 * MILLION}, "INVESTMENT"),
        (cp.garipov, {"purpose": "GROWTH", "amountRub": 1_500_000}, "EXPRESS"),
        (
            cp.zarya,
            {"purpose": "GOODS", "frequency": "REGULAR", "amountRub": 20 * MILLION},
            "CREDIT_LINE",
        ),
    ],
    ids=["sokolova", "snabkontrakt", "stankoprom", "garipov", "zarya"],
)
def test_personas_get_their_product(persona: Any, answers: dict[str, Any], expected: str) -> None:
    snap = persona().snapshot
    facts = CompanyFacts(
        snap.registry.registration_date, snap.customer.is_customer, snap.customer.customer_since
    )
    result = run(facts, **answers)
    assert result.primary is not None
    assert result.primary.product_code == expected


def test_quick_start_gets_start_path() -> None:
    snap = cp.quick_start().snapshot
    facts = CompanyFacts(
        snap.registry.registration_date, snap.customer.is_customer, snap.customer.customer_since
    )
    result = run(facts, purpose="OTHER", amountRub=MILLION, termMonths=24)
    assert result.start_path
    assert products(result)[0] == "EXPRESS"


def test_unknown_answers_do_not_block() -> None:
    a = run(purpose="GOODS", frequency="UNKNOWN", amountRub=8 * MILLION, govContract="UNKNOWN")
    b = run(purpose="GOODS", amountRub=8 * MILLION)
    assert a.outcome is WizardOutcome.RECOMMENDED
    assert a.model_dump() == b.model_dump()
    assert products(a)[0] == "WORKING_CAPITAL"


def test_unknown_amount_still_recommends() -> None:
    result = run(purpose="EQUIPMENT")
    assert result.primary is not None
    assert result.primary.payment_rub is None
    assert result.ask_collateral is False


def test_unknown_purpose_gives_catalog_hint() -> None:
    result = run(purpose="UNKNOWN", amountRub=MILLION)
    assert result.outcome is WizardOutcome.CATALOG_HINT
    assert result.hint


def test_same_answers_same_result() -> None:
    answers = {"purpose": "GROWTH", "amountRub": 6 * MILLION, "paybackHorizon": "OVER_YEAR"}
    assert run(**answers).model_dump() == run(**answers).model_dump()


def test_collateral_question_only_above_threshold() -> None:
    assert run(purpose="EQUIPMENT", amountRub=15 * MILLION).ask_collateral is True
    assert run(purpose="EQUIPMENT", amountRub=2 * MILLION).ask_collateral is False
    answered = run(purpose="EQUIPMENT", amountRub=15 * MILLION, collateral="PURCHASED_ITEM")
    assert answered.ask_collateral is False


def test_card_has_payment_decision_time_and_documents() -> None:
    result = run(purpose="GOODS", frequency="ONCE", amountRub=8 * MILLION, termMonths=12)
    assert result.primary is not None
    assert result.primary.payment_rub == 744_910  # тот же расчёт, что в 30-16 (вектор 21%)
    assert result.primary.decision_time is DecisionTime.MANUAL  # 8 млн > 5 млн авто-лимита
    assert result.primary.documents
    invest = run(purpose="EQUIPMENT", amountRub=15 * MILLION).primary
    assert invest is not None
    assert invest.decision_time is DecisionTime.MANUAL
    assert invest.needs_collateral
    express = run(purpose="OTHER", amountRub=MILLION).primary
    assert express is not None
    assert express.decision_time is DecisionTime.AUTO


def test_comfortable_options_mark_the_affordable_one() -> None:
    plain = run(purpose="OTHER", amountRub=500_000).primary
    assert plain is not None
    assert [o.term_months for o in plain.comfortable_options] == [12, 24, 36]
    assert not any(o.recommended for o in plain.comfortable_options)
    assert plain.comfortable_options[0].payment_rub == 47_280

    known_flow = CompanyFacts(
        date(2018, 1, 1), True, date(2019, 1, 1), monthly_cash_flow_rub=36_000
    )
    marked = run(known_flow, purpose="OTHER", amountRub=500_000).primary
    assert marked is not None
    # поток 36 000 / 1,25 = 28 800: 12 мес. (47 280) не по силам, 24 мес. (26 435) — по силам
    assert [o.term_months for o in marked.comfortable_options if o.recommended] == [24]


def test_installment_variants_only_for_annuity_products() -> None:
    line = run(purpose="GOODS", frequency="REGULAR", amountRub=5 * MILLION).primary
    assert line is not None
    assert line.product_code == "CREDIT_LINE"
    assert line.comfortable_options == []


def test_every_rule_points_to_catalog_products_and_has_unique_id() -> None:
    policy = cp.load_policy()
    known = set(policy.catalog.products)
    for rule in policy.wizard.rules:
        assert {
            rule.primary,
            *rule.alternatives,
            *([rule.future_hint] if rule.future_hint else []),
        } <= known
    assert len({r.id for r in policy.wizard.rules}) == len(policy.wizard.rules)
