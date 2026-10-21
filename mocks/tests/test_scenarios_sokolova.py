"""T-131: фиксируем входы Соколовой из 30-17; решение ядра проверит T-141."""

from datetime import date

from app.common.accounts import account_is_valid
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.expand import expand

TODAY = date(2026, 10, 21)


def test_sokolova_exact_identity_finance_and_request_pass_all_rules() -> None:
    spec = builtin_scenarios(TODAY)[0]
    data = expand(spec, TODAY)
    entity = data["registry"]["entity"]
    assert entity["inn"] == "001234567887"
    assert entity["ogrnip"] == "323000000123450"
    assert entity["registrationDate"] == "2023-04-12"
    assert entity["person"]["fullName"] == "Соколова Анна Сергеевна"
    assert entity["okvedMain"]["code"] == "56.10"
    assert data["tax"]["financials"] == []
    assert data["tax"]["sme"]["category"] == "MICRO"
    assert data["tax"]["taxProfile"]["taxRegimes"][0]["code"] == "USN_INCOME"
    bank = data["bankCore"]
    assert bank["customer"]["customerSince"] == "2023-05-02"
    assert bank["accounts"][0]["openedAt"] == "2023-05-02"
    assert bank["accounts"][0]["balanceRub"] == 412300
    assert len(bank["turnover"]) == 12
    assert bank["turnover"][0]["month"] == "2025-10"
    assert bank["turnover"][-1]["month"] == "2026-09"
    assert {
        (r["incomingNetRub"], r["outgoingRub"], r["counterpartiesIn"]) for r in bank["turnover"]
    } == {(905000, 795000, 2)}
    obligations = data["bki"][0]["body"]["obligations"]
    assert len(obligations) == 2
    card = next(o for o in obligations if o["kind"] == "CREDIT_CARD")
    assert (card["limitRub"], card["balanceRub"], card["monthlyPaymentRub"]) == (
        100000,
        60000,
        3000,
    )
    assert min(o["openedAt"] for o in obligations) == "2024-04-21"
    assert data["bki"][0]["body"]["inquiries"] == []
    assert spec.application.model_dump(by_alias=True) == {
        "productCode": "EXPRESS",
        "amountRub": 500000,
        "termMonths": 12,
        "collateral": None,
        "guarantor": None,
    }
    assert spec.expected_outcome == "APPROVED"
    assert spec.expected_reason_codes == []
    assert len(spec.users) == 1
    assert spec.users[0].role == "DIRECTOR"


def test_sokolova_rolls_months_and_uses_configured_bank_without_mutating_previous_call() -> None:
    original = builtin_scenarios(TODAY)[0]
    before = original.model_dump()
    spec = builtin_scenarios(date(2026, 11, 21), "040000111")[0]
    data = expand(spec, date(2026, 11, 21), settings=ScenarioSettings(bank_bik="040000111"))
    assert data["bankCore"]["turnover"][0]["month"] == "2025-11"
    assert data["bankCore"]["turnover"][-1]["month"] == "2026-10"
    assert account_is_valid("040000111", data["bankCore"]["accounts"][0]["number"])
    assert data["bankCore"]["customer"]["customerSince"] == "2023-05-02"
    assert original.model_dump() == before
