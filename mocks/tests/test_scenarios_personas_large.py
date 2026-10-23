"""T-133: snabkontrakt, stankoprom и zarya сверены с оракулом 30-17 и ручными входами ядра.

Проверяется развёрнутое состояние (`expand`) без сети. Ряды и суммы те же, что в
`api/tests/fixtures/core_personas.py` (функции snabkontrakt, stankoprom, zarya).
"""

import math
from datetime import date
from typing import Any

import pytest

from app.common.inn import inn_is_valid
from app.roles.bki.calc import months_between
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.builtin_large import (
    GROMOV_INN,
    KUZNETSOV_INN,
    ORLOV_INN,
    SNABKONTRAKT_INN,
    STANKOPROM_INN,
    ZARYA_INN,
    large_personas,
)
from app.roles.scenarios.expand import expand
from app.roles.scenarios.schemas import ScenarioSpec

TODAY = date(2026, 10, 21)
CODES = ("snabkontrakt", "stankoprom", "zarya")


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


def lines_of(data: dict[str, Any], year: int) -> dict[str, int]:
    record = next(r for r in data["tax"]["financials"] if r["year"] == year)
    lines: dict[str, int] = record["lines"]
    return lines


def test_list_has_unique_codes_and_inns_and_stable_order() -> None:
    assert [s.code for s in large_personas()] == list(CODES)
    assert [s.model_dump() for s in large_personas()] == [s.model_dump() for s in large_personas()]
    specs = builtin_scenarios(TODAY)
    assert len({s.code for s in specs}) == len(specs)
    inns = [s.company.inn for s in specs if s.company]
    assert len(inns) == len(set(inns))
    assert all(s.builtin_version == 1 for s in specs if s.code in CODES)


def test_all_identifiers_have_valid_checksums() -> None:
    for inn in (SNABKONTRAKT_INN, STANKOPROM_INN, ZARYA_INN, ORLOV_INN, KUZNETSOV_INN, GROMOV_INN):
        assert inn_is_valid(inn), inn


def test_snabkontrakt_turnover_is_the_exact_oracle_series() -> None:
    data = data_of("snabkontrakt")
    months = data["bankCore"]["turnover"]
    assert [m["month"] for m in months][0] == "2024-10"
    assert [m["month"] for m in months][-1] == "2026-09"
    assert len(months) == 24
    for m in months:
        expected = 18_000_000 if m["month"] < "2026-01" else 18_300_000
        assert m["incomingNetRub"] == expected, m["month"]
        assert m["incomingNetRub"] - m["outgoingRub"] == 1_100_000
        assert m["counterpartiesIn"] > 2  # правило «один плательщик» (D-076) не срабатывает
    assert data["tax"]["taxProfile"]["taxRegimes"][0]["code"] == "OSNO"
    assert data["bankCore"]["customer"]["customerSince"] <= "2023-10-21"


def test_snabkontrakt_statements_give_flow_of_exactly_1_2_million() -> None:
    data = data_of("snabkontrakt")
    lines = lines_of(data, 2025)
    assert (lines["2110"], lines["2400"], lines["2330"]) == (180_000_000, 13_200_000, 1_200_000)
    assert (lines["2400"] + lines["2330"]) / 12 == 1_200_000
    assert lines_of(data, 2024)["2110"] == 180_000_000
    for year in (2024, 2025):
        row = lines_of(data, year)
        assert row["1600"] == row["1100"] + row["1200"] == row["1300"] + row["1400"] + row["1500"]
    assert data["tax"]["sme"]["category"] == "SMALL"
    assert data["tax"]["taxProfile"]["incomeExpenses"]["incomeRub"] == 180_000_000


def test_snabkontrakt_bki_two_active_loans_600k_and_8m_without_overdue() -> None:
    data = data_of("snabkontrakt")
    company = bki_of(data, SNABKONTRAKT_INN)
    loans = active(company)
    assert len(loans) == 2
    assert closed(company) == []
    assert sum(o["monthlyPaymentRub"] for o in loans) == 600_000
    assert sum(o["balanceRub"] for o in loans) == 8_000_000
    assert all(o["overdueRub"] == 0 and not o["overduePeriods"] for o in loans)
    assert all(months_between(date.fromisoformat(o["openedAt"]), TODAY) >= 24 for o in loans)
    owner = bki_of(data, ORLOV_INN)
    assert len(active(owner)) == len(closed(owner)) == 1
    assert sum(o["balanceRub"] for o in owner["obligations"]) == 0


@pytest.mark.parametrize("today", [date(2026, 10, 21), date(2026, 10, 22), date(2026, 12, 31)])
def test_snabkontrakt_and_zarya_debt_does_not_drift_with_the_date(today: date) -> None:
    for code, payments, debt in (
        ("snabkontrakt", 600_000, 8_000_000),
        ("zarya", 1_500_000, 40_000_000),
    ):
        data = data_of(code, today)
        company = bki_of(data, data["identity"]["inn"])
        loans = active(company)
        assert sum(o["monthlyPaymentRub"] for o in loans) == payments, (code, today)
        assert sum(o["balanceRub"] for o in loans) == debt, (code, today)


def test_snabkontrakt_has_a_government_contract_for_the_contract_card() -> None:
    contracts = data_of("snabkontrakt")["tax"]["contracts"]
    running = [c for c in contracts if c["status"] == "IN_PROGRESS"]
    done = [c for c in contracts if c["status"] == "EXECUTED"]
    assert len(running) == len(done) == 1
    assert (running[0]["priceRub"], running[0]["paidRub"]) == (12_000_000, 0)
    assert running[0]["paymentDeadline"] == "2027-01-21"  # paymentIn: +3M
    assert done[0]["paidRub"] == done[0]["priceRub"]


def test_stankoprom_matches_example_10_5() -> None:
    data = data_of("stankoprom")
    entity = data["registry"]["entity"]
    assert entity["inn"] == STANKOPROM_INN
    assert entity["registrationDate"] == "2017-03-14"
    assert entity["okvedMain"]["code"] == "25.62"
    assert entity["director"]["inn"] == entity["founders"][0]["inn"] == KUZNETSOV_INN
    assert entity["founders"][0]["sharePercent"] == 100
    new, old = lines_of(data, 2025), lines_of(data, 2024)
    assert (new["2110"], new["2400"], new["2330"], new["1400"]) == (
        420_000_000,
        30_700_000,
        1_900_000,
        22_000_000,
    )
    assert (old["2110"], old["2400"], old["2330"], old["1400"]) == (
        388_000_000,
        27_400_000,
        3_100_000,
        31_000_000,
    )
    assert sorted(r["year"] for r in data["tax"]["financials"]) == [2024, 2025]
    assert data["tax"]["sme"]["category"] == "SMALL"
    assert data["bankCore"]["customer"] is None
    assert data["bankCore"]["turnover"] == []


def test_stankoprom_bki_two_closed_loans_and_director_card() -> None:
    data = data_of("stankoprom")
    company = bki_of(data, STANKOPROM_INN)
    assert active(company) == []
    assert sorted(o["amountRub"] for o in closed(company)) == [9_000_000, 22_000_000]
    assert {o["closedAt"] for o in closed(company)} == {"2026-03-20", "2025-06-12"}
    # директор и владелец — один субъект БКИ
    assert [e["inn"] for e in data["bki"]].count(KUZNETSOV_INN) == 1
    person = bki_of(data, KUZNETSOV_INN)
    (card,) = active(person)
    assert (card["limitRub"], card["balanceRub"], card["monthlyPaymentRub"]) == (
        300_000,
        90_000,
        4_500,
    )
    (loan,) = closed(person)
    assert months_between(date.fromisoformat(loan["openedAt"]), TODAY) > 24


def test_zarya_is_a_joint_stock_company_without_founders() -> None:
    data = data_of("zarya")
    entity = data["registry"]["entity"]
    assert entity["inn"] == ZARYA_INN == "0014443330"
    assert entity["okvedMain"]["code"] == "01.11"
    assert entity["founders"] == []
    assert entity["director"]["inn"] == GROMOV_INN
    assert data["identity"]["subjectRefs"].get("owner") is None
    assert data["tax"]["taxProfile"]["taxRegimes"][0]["code"] == "ESHN"
    assert data["tax"]["sme"]["category"] == "SMALL"
    assert data["tax"]["taxProfile"]["avgHeadcount"]["value"] == 90
    assert data["bankCore"]["customer"] is not None
    assert spec_of("zarya").application is not None
    assert spec_of("zarya").application.guarantor is None  # type: ignore[union-attr]


def test_zarya_statements_match_the_oracle() -> None:
    data = data_of("zarya")
    new, old = lines_of(data, 2025), lines_of(data, 2024)
    assert (new["2110"], new["2400"], new["2330"]) == (650_000_000, 65_000_000, 4_000_000)
    assert (old["2110"], old["2400"], old["2330"]) == (650_000_000, 65_000_000, 4_500_000)


def test_zarya_turnover_follows_the_seasonal_formula_of_30_17() -> None:
    months = data_of("zarya")["bankCore"]["turnover"]
    assert len(months) == 24
    for row in months:
        number = int(row["month"][5:])
        formula = 650_000_000 / 12 * (1 + 0.6 * math.sin(2 * math.pi * (number - 6) / 12))
        assert abs(row["incomingNetRub"] - formula) <= 1, row["month"]
        assert abs(row["incomingNetRub"] - row["outgoingRub"] - 0.1 * row["incomingNetRub"]) <= 1
        assert row["counterpartiesIn"] > 2
    by_month = {r["month"]: r["incomingNetRub"] for r in months}
    assert by_month["2025-09"] == by_month["2026-09"] == 86_666_667
    assert by_month["2026-03"] == 21_666_667
    assert abs(sum(v for k, v in by_month.items() if k.startswith("2025")) - 650_000_000) <= 10


def test_zarya_bki_payments_1_5m_and_debt_40m_without_overdue() -> None:
    data = data_of("zarya")
    company = bki_of(data, ZARYA_INN)
    loans = active(company)
    credits = [o for o in loans if o["kind"] == "LOAN"]
    lines = [o for o in loans if o["kind"] == "CREDIT_LINE"]
    assert sum(o["monthlyPaymentRub"] for o in credits) == 900_000
    assert sum(o["monthlyPaymentRub"] for o in lines) == 600_000
    assert sum(o["balanceRub"] for o in lines) * 5 // 100 == 600_000
    assert sum(o["balanceRub"] for o in loans) == 40_000_000
    assert len(closed(company)) == 6
    assert all(not o["overduePeriods"] for o in company["obligations"])
    director = bki_of(data, GROMOV_INN)
    assert len(active(director)) == len(closed(director)) == 1


@pytest.mark.parametrize(
    ("code", "outcome", "final", "codes"),
    [
        ("snabkontrakt", "COUNTER_OFFER", "APPROVED", ["DSCR_LOW"]),
        (
            "stankoprom",
            "MANUAL_REVIEW",
            "APPROVED",
            ["AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"],
        ),
        ("zarya", "MANUAL_REVIEW", "APPROVED", ["AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"]),
    ],
)
def test_expected_outcomes_come_from_30_17(
    code: str, outcome: str, final: str, codes: list[str]
) -> None:
    spec = spec_of(code)
    assert (spec.expected_outcome, spec.expected_final_outcome) == (outcome, final)
    assert spec.expected_reason_codes == codes


def test_applications_match_the_oracle() -> None:
    wanted = {
        "snabkontrakt": ("WORKING_CAPITAL", 8_000_000, 12, None),
        "stankoprom": ("INVESTMENT", 15_000_000, 60, 25_000_000),
        "zarya": ("CREDIT_LINE", 20_000_000, 12, 30_000_000),
    }
    for code, (product, amount, term, collateral) in wanted.items():
        application = spec_of(code).application
        assert application is not None
        assert (application.product_code, application.amount_rub, application.term_months) == (
            product,
            amount,
            term,
        )
        assert application.guarantor is None
        if collateral is None:
            assert application.collateral is None
        else:
            assert application.collateral is not None
            assert application.collateral.value_rub == collateral


def test_stankoprom_has_two_users_and_the_accountant_has_power_of_attorney() -> None:
    users = spec_of("stankoprom").users
    assert [(u.login, u.role) for u in users] == [
        ("kuznetsov", "DIRECTOR"),
        ("belova", "ACCOUNTANT"),
    ]
    assert users[1].power_of_attorney is True
    assert users[1].full_name == "Белова Ольга Николаевна"
    assert [u.login for u in spec_of("snabkontrakt").users] == ["orlov-p"]
    assert [u.login for u in spec_of("zarya").users] == ["gromov"]


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("today", [date(2026, 10, 21), date(2026, 10, 22), date(2026, 12, 31)])
def test_every_persona_passes_all_consistency_rules_on_several_dates(
    code: str, today: date
) -> None:
    spec = spec_of(code, today)
    assert spec.company is not None
    assert data_of(code, today)["identity"]["inn"] == spec.company.inn
