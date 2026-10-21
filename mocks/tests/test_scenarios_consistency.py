"""T-126: у каждого правила есть самостоятельный нарушающий пример."""

from copy import deepcopy
from datetime import date
from typing import Any

import pytest

from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.consistency_common import Context
from app.roles.scenarios.debt_history import build_history
from app.roles.scenarios.expand import expand, resolved_spec
from app.roles.scenarios.schemas import ActiveLoan, BankSpec, ScenarioSpec
from app.roles.scenarios.validators import RULES

TODAY = date(2026, 10, 25)


def scenario(**changes: Any) -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {
            "code": "consistency",
            "title": "Сверка систем",
            "company": {"form": "LLC", "ageMonths": 120},
            "finance": {
                "avgMonthlyRevenueRub": 1000000,
                "hasStatements": True,
                "noisePercent": 0,
                "headcount": 5,
            },
            "bank": {"isCustomer": True, "customerSinceMonths": 36},
            "bki": {
                "company": {
                    "activeLoans": [{"kind": "LOAN", "amountRub": 3000000, "termMonths": 36}]
                }
            },
            **changes,
        }
    )


@pytest.fixture
def context() -> Context:
    spec = scenario()
    data = expand(spec, TODAY)
    return Context(
        resolved_spec(spec),
        data,
        TODAY,
        ScenarioSettings(),
        "consistency",
        build_history(spec, data, "consistency"),
    )


# Изменения в готовом снимке изолируют правило от более ранней проверки схемы.
MUTATIONS: dict[str, tuple[tuple[str | int, ...], Any]] = {
    "BODY_SCHEMAS": (("bankCore", "accounts", 0, "number"), "не-счёт"),
    "FORM_DATA": (("identity", "form"), "IP"),
    "COMPANY_CARD": (("registry", "entity", "registrationDate"), "2015-01-01"),
    "LLC_SHARES": (("registry", "entity", "founders", 0, "sharePercent"), 50),
    "ROLE_IDENTITIES": (("registry", "persons", 0, "birthDate"), "1985-01-01"),
    "BKI_IDENTITY": (("bki", 0, "body", "subject", "ogrn"), "1170000004569"),
    "BKI_COMPANY_AGE": (("bki", 0, "body", "obligations", 0, "openedAt"), "2000-01-01"),
    "BANK_SUBJECTS": (("bankSubjects",), [{"inn": "0017654322", "body": {}}]),
    "REPORT_YEARS": (("tax", "financials", 0, "year"), 2026),
    "REPORT_BALANCE": (("tax", "financials", 0, "lines", "1600"), 1),
    "PB_REVENUE": (("tax", "taxProfile", "incomeExpenses", "incomeRub"), 1),
    "TURNOVER_WINDOW": (("bankCore", "turnover"), []),
    "CUSTOMER_AGE": (("bankCore", "customer", "customerSince"), "2000-01-01"),
    "SME_CATEGORY": (("tax", "sme", "category"), "MEDIUM"),
    "LOAN_PAYMENT": (("bki", 0, "body", "obligations", 0, "monthlyPaymentRub"), 3000001),
    "LOAN_UIDS": (("bki", 0, "body", "obligations", 0, "uid"), "не-уид"),
    "LOAN_DATES": (
        ("bki", 0, "body", "obligations", 0, "overduePeriods"),
        [{"since": "2000-01-01", "until": None}],
    ),
    "BANKRUPTCY_MATCH": (
        ("registry", "bankruptcies"),
        [
            {
                "subjectInn": "0017654322",
                "caseNumber": "А00-1/2024",
                "stage": "COMPLETED",
                "startedAt": "2024-01-01",
                "completedAt": "2025-01-01",
            }
        ],
    ),
    "BANKRUPT_STATUS": (("registry", "entity", "status", "code"), "BANKRUPT"),
    "BANKRUPTCY_DATES": (
        ("registry", "bankruptcies"),
        [{"caseNumber": "А00-1/2027", "startedAt": "2027-01-01", "completedAt": None}],
    ),
    "OUR_BANK_UID": (("bankCore", "loans"), [{"contractUid": "неизвестный"}]),
    "ACCOUNT_BLOCK": (("bankCore", "accounts", 0, "status"), "BLOCKED"),
    "CONTRACTS": (
        ("tax", "contracts"),
        [
            {
                "registryNumber": "1",
                "concludedAt": "2025-01-01",
                "executionDeadline": "2024-01-01",
                "paymentDeadline": "2025-02-01",
                "priceRub": 10,
                "paidRub": 0,
            }
        ],
    ),
}
SPECIAL = {
    "TURNOVER_REVENUE",
    "NON_CUSTOMER_DATA",
    "REGIME_LIMITS",
    "STATEMENT_DEBT",
    "LOAN_LOCATION",
}


def test_every_registered_rule_has_a_negative_case() -> None:
    codes = [rule.code for rule in RULES]
    assert len(codes) == len(set(codes))
    assert set(codes) == set(MUTATIONS) | SPECIAL


@pytest.mark.parametrize("code", [rule.code for rule in RULES])
def test_each_rule_rejects_its_own_violation(context: Context, code: str) -> None:
    if code in MUTATIONS:
        path, value = MUTATIONS[code]
        target = context.data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = deepcopy(value)
    elif code == "TURNOVER_REVENUE":
        for row in context.bank["turnover"]:
            row["incomingNetRub"] *= 2
    elif code == "NON_CUSTOMER_DATA":
        context.spec = context.spec.model_copy(update={"bank": BankSpec(is_customer=False)})
    elif code == "REGIME_LIMITS":
        context.tax["taxProfile"]["taxRegimes"][0]["code"] = "AUSN"
        context.tax["taxProfile"]["avgHeadcount"]["value"] = 6
    elif code == "STATEMENT_DEBT":
        context.tax["financials"][-1]["lines"]["1400"] = 3000001
    elif code == "LOAN_LOCATION":
        context.spec = context.spec.model_copy(
            update={"active_loans": [ActiveLoan(kind="LOAN", amount_rub=1000000)]}
        )
    rule = next(rule for rule in RULES if rule.code == code)
    with pytest.raises(ValueError, match=r"[А-Яа-я]"):
        rule.check(context)
