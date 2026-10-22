"""T-132, T-134: входы vektor, orlov, romashka, garipov и quick-start сверены с оракулом 30-17.

Проверяется развёрнутое состояние (`expand`) без сети: те же числа, что записаны в ручных входах
ядра `api/tests/fixtures/core_personas.py`. Живое чтение через четыре настоящих мока — в
`test_scenarios_personas_simple_integration.py`.
"""

from datetime import date, timedelta
from typing import Any

import pytest

from app.roles.bki.calc import months_between
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.builtin_simple import (
    GARIPOV_INN,
    LEBEDEV_INN,
    MOROZOV_INN,
    ORLOV_INN,
    QUICK_START_INN,
    ROMASHKA_INN,
    SOKOLOV_INN,
    VEKTOR_INN,
    simple_personas,
)
from app.roles.scenarios.expand import expand
from app.roles.scenarios.schemas import ScenarioSpec

TODAY = date(2026, 10, 21)
CODES = ("vektor", "orlov", "romashka", "garipov", "quick-start")


def spec_of(code: str, today: date = TODAY) -> ScenarioSpec:
    return next(s for s in builtin_scenarios(today) if s.code == code)


def data_of(code: str, today: date = TODAY) -> dict[str, Any]:
    return expand(spec_of(code, today), today)


def bki_of(data: dict[str, Any], inn: str) -> dict[str, Any]:
    return next(e["body"] for e in data["bki"] if e["inn"] == inn)


def active(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in body["obligations"] if o["closedAt"] is None]


def closed(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in body["obligations"] if o["closedAt"] is not None]


def history_months(body: dict[str, Any], today: date = TODAY) -> int:
    return months_between(
        min(date.fromisoformat(o["openedAt"]) for o in body["obligations"]), today
    )


def test_list_has_unique_codes_inns_and_stable_order() -> None:
    specs = builtin_scenarios(TODAY)
    assert [s.code for s in specs] == ["sokolova", *CODES]
    assert len({s.code for s in specs}) == len(specs)
    inns = [s.company.inn for s in specs if s.company]
    assert len(inns) == len(set(inns))
    assert all(s.builtin_version == 1 for s in specs)
    assert [s.model_dump() for s in simple_personas(TODAY)] == [
        s.model_dump() for s in simple_personas(TODAY)
    ]


def test_vektor_is_liquidating_with_unreliable_address_and_clean_everything_else() -> None:
    data = data_of("vektor")
    entity = data["registry"]["entity"]
    assert entity["inn"] == VEKTOR_INN == "0018889990"
    assert entity["status"]["code"] == "LIQUIDATING"
    assert entity["address"]["unreliable"] is not None
    assert entity["okvedMain"]["code"] == "47.19"
    assert months_between(date.fromisoformat(entity["registrationDate"]), TODAY) == 48
    assert entity["director"]["inn"] == entity["founders"][0]["inn"] == LEBEDEV_INN
    tax = data["tax"]
    assert tax["taxProfile"]["taxRegimes"][0]["code"] == "USN_INCOME"
    assert tax["taxProfile"]["debts"]["taxDebtRub"] == 0
    assert tax["taxProfile"]["riskFlags"] == {
        "massAddress": False,
        "massDirector": False,
        "massFounder": False,
        "disqualifiedManagement": False,
        "noReportsOverYear": False,
    }
    assert tax["financials"] == []
    assert data["bankCore"]["customer"] is None
    assert data["bankSubjects"] == []
    assert data["bankCore"]["compliance"]["aml"] is None
    assert data["bankCore"]["compliance"]["internalStopList"] is None


def test_vektor_bki_has_one_closed_loan_and_a_clean_director() -> None:
    data = data_of("vektor")
    company = bki_of(data, VEKTOR_INN)
    assert active(company) == []
    assert len(closed(company)) == 1
    assert history_months(company) == 40
    assert all(not o["overduePeriods"] for o in company["obligations"])
    assert company["inquiries"] == company["applications"] == []
    director = bki_of(data, LEBEDEV_INN)
    assert len(active(director)) == len(closed(director)) == 1
    assert history_months(director) == 60
    assert sum(o["balanceRub"] for o in director["obligations"]) == 0


def test_orlov_is_not_in_registry_but_is_a_taxpayer_of_npd() -> None:
    data = data_of("orlov")
    assert data["registry"]["entity"] is None
    assert data["identity"]["inn"] == ORLOV_INN == "001211122200"
    assert data["identity"]["form"] == "SELF_EMPLOYED"
    assert data["tax"]["npd"]["deregisteredAt"] is None
    assert data["tax"]["taxProfile"] is None
    assert data["tax"]["financials"] == []
    assert data["bki"] == []
    assert data["bankCore"]["customer"] is None
    assert data["bankCore"]["accounts"] == data["bankCore"]["turnover"] == []
    spec = spec_of("orlov")
    assert spec.users == []
    assert spec.expected_outcome == "NOT_ELIGIBLE"
    assert spec.expected_reason_codes == ["SELF_EMPLOYED"]
    assert spec.application is not None
    assert spec.application.amount_rub == 300000
    assert spec.application.product_code is None


def test_romashka_tax_numbers_make_debt_more_than_ten_percent_of_monthly_revenue() -> None:
    data = data_of("romashka")
    profile = data["tax"]["taxProfile"]
    assert profile["taxRegimes"][0]["code"] == "USN_INCOME_MINUS_EXPENSES"
    assert profile["debts"]["taxDebtRub"] == 1150000
    assert profile["debts"]["penaltiesRub"] == 42000
    assert profile["taxOffenses"]["count"] == 1
    latest = max(data["tax"]["financials"], key=lambda r: r["year"])
    assert latest["year"] == 2025
    lines = latest["lines"]
    assert latest["formType"] == "SIMPLIFIED"
    assert (lines["2110"], lines["2330"], lines["1400"], lines["2400"]) == (
        95000000,
        600000,
        500000,
        4000000,
    )
    monthly = lines["2110"] / 12
    assert round(monthly) == 7916667
    share = profile["debts"]["taxDebtRub"] / monthly
    assert round(share * 100, 2) == 14.53
    assert share > 0.10
    assert profile["incomeExpenses"] == {
        "year": 2025,
        "incomeRub": 95000000,
        "expensesRub": 91000000,
    }
    assert data["tax"]["sme"]["category"] == "SMALL"
    assert data["bankCore"]["customer"] is None
    entity = data["registry"]["entity"]
    assert entity["status"]["code"] == "ACTIVE"
    assert entity["registrationDate"] == "2019-10-01"
    assert entity["ogrn"] == "1190000007890"
    assert entity["okvedMain"]["code"] == "46.73"
    assert entity["director"]["inn"] == MOROZOV_INN


def test_romashka_bki_reproduces_example_6_1_arithmetic() -> None:
    company = bki_of(data_of("romashka"), ROMASHKA_INN)
    loans = sorted(active(company), key=lambda o: o["openedAt"])
    assert len(loans) == 2
    assert len(closed(company)) == 3
    first, second = loans
    assert (first["amountRub"], first["monthlyPaymentRub"], first["balanceRub"]) == (
        3000000,
        113000,
        837000,
    )
    assert first["overdueRub"] == 452000 == 4 * first["monthlyPaymentRub"]
    assert first["overduePeriods"] == [{"since": "2026-07-19", "until": None}]
    assert (TODAY - date.fromisoformat(first["overduePeriods"][0]["since"])).days == 94
    assert (second["amountRub"], second["monthlyPaymentRub"], second["balanceRub"]) == (
        4000000,
        205500,
        976000,
    )
    assert second["secured"] is True
    assert second["overdueRub"] == 0
    assert sum(o["balanceRub"] for o in loans) == 1813000
    assert sum(o["monthlyPaymentRub"] for o in loans) == 318500
    assert history_months(company) == 84
    assert len(company["inquiries"]) == 6
    assert not any(i["isOwn"] for i in company["inquiries"])
    assert len(company["applications"]) == 2
    assert {a["decision"] for a in company["applications"]} == {"REJECTED"}
    director = bki_of(data_of("romashka"), MOROZOV_INN)
    assert len(active(director)) == len(closed(director)) == 1


@pytest.mark.parametrize("days", range(0, 160, 3))
def test_romashka_overdue_is_at_least_90_days_on_452_thousand_for_any_day(days: int) -> None:
    today = TODAY + timedelta(days=days)
    company = bki_of(data_of("romashka", today), ROMASHKA_INN)
    first = min(active(company), key=lambda o: o["openedAt"])
    since = date.fromisoformat(first["overduePeriods"][0]["since"])
    assert 94 <= (today - since).days <= 97
    assert since.day <= 28
    assert (first["monthlyPaymentRub"], first["balanceRub"], first["overdueRub"]) == (
        113000,
        837000,
        452000,
    )


def test_garipov_is_a_patent_ip_with_no_turnover_statements_or_bank_data() -> None:
    data = data_of("garipov")
    entity = data["registry"]["entity"]
    assert entity["inn"] == GARIPOV_INN == "001298765490"
    assert entity["okvedMain"]["code"] == "96.02"
    assert months_between(date.fromisoformat(entity["registrationDate"]), TODAY) == 61
    assert data["tax"]["taxProfile"]["taxRegimes"][0]["code"] == "PSN"
    assert data["tax"]["financials"] == []
    assert data["tax"]["sme"]["category"] == "MICRO"
    bank = data["bankCore"]
    assert bank["customer"] is None
    assert bank["accounts"] == []
    assert bank["turnover"] == []
    company = bki_of(data, GARIPOV_INN)
    assert active(company) == []
    assert len(closed(company)) == 1
    loan = closed(company)[0]
    assert (loan["openedAt"], loan["closedAt"]) == ("2022-10-21", "2023-10-21")
    assert history_months(company) == 48


def test_garipov_statement_inputs_are_flat_700_thousand_with_100_thousand_surplus() -> None:
    finance = spec_of("garipov").finance
    assert finance is not None
    assert (finance.avg_monthly_revenue_rub, finance.noise_percent) == (700000, 0)
    assert finance.min_monthly_surplus_rub == 100000
    assert finance.tax_regime == "PSN"
    assert finance.has_statements is False
    assert finance.net_margin_percent is not None
    # поток по оракулу: 700 000 × 13% = 91 000; остаток выписки задаёт больший из двух
    assert max(700000 * finance.net_margin_percent / 100, 100000) == 100000
    assert 700000 * 12 <= 20_000_000  # предел патента 2026 (10.3)


def test_quick_start_is_three_months_old_customer_with_flat_turnover() -> None:
    data = data_of("quick-start")
    entity = data["registry"]["entity"]
    assert entity["inn"] == QUICK_START_INN == "0012221117"
    assert entity["registrationDate"] == "2026-07-21"
    assert entity["okvedMain"]["code"] == "62.01"
    assert data["tax"]["taxProfile"]["taxRegimes"][0]["code"] == "AUSN"
    assert data["tax"]["financials"] == []
    assert data["tax"]["sme"]["isNewlyCreated"] is True
    bank = data["bankCore"]
    assert bank["customer"]["customerSince"] == "2026-07-21"
    assert bank["accounts"][0]["balanceRub"] == 300000
    assert [r["month"] for r in bank["turnover"]] == ["2026-07", "2026-08", "2026-09"]
    assert {
        (r["incomingNetRub"], r["outgoingRub"], r["counterpartiesIn"]) for r in bank["turnover"]
    } == {(700000, 595000, 10)}
    assert {r["incomingNetRub"] - r["outgoingRub"] for r in bank["turnover"]} == {105000}


def test_quick_start_company_has_no_history_and_owner_is_director_and_clean() -> None:
    data = data_of("quick-start")
    entity = data["registry"]["entity"]
    assert entity["director"]["inn"] == SOKOLOV_INN
    assert [f["inn"] for f in entity["founders"]] == [SOKOLOV_INN]
    assert entity["founders"][0]["sharePercent"] == 100
    assert data["identity"]["subjectRefs"]["owner"] == SOKOLOV_INN
    # у компании субъекта БКИ нет вовсе (ответ NOT_FOUND); владелец — отдельный субъект-человек
    assert [e["inn"] for e in data["bki"]] == [SOKOLOV_INN]
    owner = data["bki"][0]["body"]
    assert owner["subject"]["type"] == "PERSON"
    assert len(active(owner)) == len(closed(owner)) == 1
    assert history_months(owner) == 60
    assert sum(o["balanceRub"] for o in owner["obligations"]) == 0
    assert not any(o["overduePeriods"] for o in owner["obligations"])
    spec = spec_of("quick-start")
    assert len(spec.users) == 1
    assert spec.users[0].inn == SOKOLOV_INN
    assert spec.users[0].role == "DIRECTOR"


@pytest.mark.parametrize("today", [date(2026, 10, 21), date(2027, 4, 21), date(2027, 5, 31)])
def test_quick_start_stays_three_months_old_when_today_is_shifted(today: date) -> None:
    data = data_of("quick-start", today)
    registered = date.fromisoformat(data["registry"]["entity"]["registrationDate"])
    since = date.fromisoformat(data["bankCore"]["customer"]["customerSince"])
    assert months_between(registered, today) == 3
    assert months_between(since, today) == 3
    assert len(data["bankCore"]["turnover"]) == 3


@pytest.mark.parametrize(
    ("code", "outcome", "final", "codes"),
    [
        ("vektor", "REJECTED", None, ["COMPANY_NOT_ACTIVE"]),
        ("orlov", "NOT_ELIGIBLE", None, ["SELF_EMPLOYED"]),
        ("romashka", "REJECTED", None, ["TAX_ARREARS_HIGH", "CURRENT_OVERDUE_90"]),
        ("garipov", "NEEDS_INFO", "APPROVED", ["REVENUE_UNKNOWN"]),
        ("quick-start", "COUNTER_OFFER", "APPROVED", ["BUSINESS_TOO_YOUNG"]),
    ],
)
def test_expected_outcomes_come_from_30_17(
    code: str, outcome: str, final: str | None, codes: list[str]
) -> None:
    spec = spec_of(code)
    assert (spec.expected_outcome, spec.expected_final_outcome) == (outcome, final)
    assert spec.expected_reason_codes == codes


def test_applications_match_the_oracle_and_quick_start_has_no_guarantor_yet() -> None:
    wanted = {
        "vektor": ("EXPRESS", 2000000, 12),
        "romashka": ("WORKING_CAPITAL", 3000000, 6),
        "garipov": ("EXPRESS", 1500000, 36),
        "quick-start": ("EXPRESS", 1000000, 24),
    }
    for code, (product, amount, term) in wanted.items():
        application = spec_of(code).application
        assert application is not None
        assert (application.product_code, application.amount_rub, application.term_months) == (
            product,
            amount,
            term,
        )
        assert application.collateral is None
        assert application.guarantor is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("today", [date(2026, 10, 21), date(2026, 10, 22), date(2026, 12, 31)])
def test_every_persona_passes_all_consistency_rules_on_several_dates(
    code: str, today: date
) -> None:
    spec = spec_of(code, today)
    assert spec.company is not None
    assert data_of(code, today)["identity"]["inn"] == spec.company.inn
