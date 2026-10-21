"""T-121: согласованность финансовых фактов между ФНС, отчётностью и АБС."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.roles.bank_core.admin import BankCoreAdminHandler
from app.roles.bank_core.schemas import BankCoreBody
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.expand import expand, resolved_spec
from app.roles.scenarios.finance import expand_finance
from app.roles.scenarios.schemas import ScenarioSpec
from app.roles.tax.admin import TaxHandler
from app.roles.tax.schemas import TaxBody

TODAY = date(2026, 10, 21)


def scenario(**overrides: Any) -> ScenarioSpec:
    values: dict[str, Any] = {
        "code": "finance-test",
        "title": "Согласованные финансы",
        "company": {"form": "LLC", "ageMonths": 84},
        "finance": {
            "avgMonthlyRevenueRub": 10000000,
            "netMarginPercent": 10,
            "noisePercent": 0,
            "hasStatements": True,
            "taxRegime": "OSNO",
            "headcount": 10,
        },
        "bank": {"isCustomer": True, "customerSinceMonths": 36, "balanceRub": 300000},
    }
    for key, value in overrides.items():
        values[key] = values[key] | value if isinstance(value, dict) and key in values else value
    return ScenarioSpec.model_validate(values)


def checked(spec: ScenarioSpec, today: date = TODAY) -> dict[str, Any]:
    result = expand(spec, today)
    inn = result["identity"]["inn"]
    tax = TaxBody.model_validate(result["tax"])
    bank = BankCoreBody.model_validate(result["bankCore"])
    TaxHandler().check(inn, tax)
    BankCoreAdminHandler().check(inn, bank)
    return result


def test_sokolova_exact_cash_flow_uses_explicit_persona_parameters() -> None:
    spec = scenario(
        company={"form": "IP", "ageMonths": 42, "okved": "56.10"},
        finance={
            "avgMonthlyRevenueRub": 905000,
            "netMarginPercent": 10,
            "minMonthlySurplusRub": 110000,
            "hasStatements": False,
            "taxRegime": "USN_INCOME",
        },
        bank={"customerSinceMonths": 41, "balanceRub": 412300},
    )
    result = checked(spec)
    rows = result["bankCore"]["turnover"]
    assert [row["month"] for row in rows] == [
        "2025-10",
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    assert {(r["incomingRub"], r["incomingNetRub"], r["outgoingRub"]) for r in rows} == {
        (911800, 905000, 795000)
    }
    assert result["bankCore"]["accounts"][0]["balanceRub"] == 412300
    assert result["tax"]["financials"] == []
    assert result["tax"]["taxProfile"]["incomeExpenses"] is None


def test_ip_healthy_preserves_generic_preset_instead_of_sokolova_numbers() -> None:
    spec = ScenarioSpec.model_validate(
        {"code": "plain-ip", "title": "ИП", "preset": "IP_HEALTHY", "finance": {"noisePercent": 0}}
    )
    result = checked(spec)
    rows = result["bankCore"]["turnover"]
    assert len(rows) == 12
    assert {r["incomingNetRub"] for r in rows} == {800000}
    assert {r["incomingNetRub"] - r["outgoingRub"] for r in rows} == {96000}


@pytest.mark.parametrize("rate", [0, 5, 7, 10, 20, 22])
def test_flat_revenue_reconciles_for_explicit_vat_rate(rate: int) -> None:
    result = checked(scenario(finance={"vatRatePercent": rate}))
    statement = next(f for f in result["tax"]["financials"] if f["year"] == 2025)
    year_rows = [r for r in result["bankCore"]["turnover"] if r["month"].startswith("2025-")]
    assert len(year_rows) == 12
    revenue = statement["lines"]["2110"]
    assert revenue == 120000000
    assert sum(r["incomingNetRub"] for r in year_rows) == revenue * (100 + rate) // 100
    assert statement["lines"]["2400"] == 12000000
    assert result["tax"]["taxProfile"]["incomeExpenses"]["incomeRub"] == revenue


def test_osno_vat_uses_each_month_date_and_override_has_priority() -> None:
    rows = checked(scenario())["bankCore"]["turnover"]
    assert len(rows) == 24
    assert rows[0]["month"] == "2024-10"
    assert rows[-1]["month"] == "2026-09"
    assert {r["incomingNetRub"] for r in rows if r["month"] < "2026-01"} == {12000000}
    assert {r["incomingNetRub"] for r in rows if r["month"] >= "2026-01"} == {12200000}
    overridden = checked(scenario(finance={"vatRatePercent": 7}))["bankCore"]["turnover"]
    assert {r["incomingNetRub"] for r in overridden} == {10700000}


@pytest.mark.parametrize("regime", ["USN_INCOME", "USN_INCOME_MINUS_EXPENSES", "ESHN", "AUSN"])
def test_non_osno_defaults_to_zero_vat(regime: str) -> None:
    rows = checked(scenario(finance={"taxRegime": regime, "avgMonthlyRevenueRub": 1000000}))[
        "bankCore"
    ]["turnover"]
    assert {r["incomingNetRub"] for r in rows} == {1000000}


@pytest.mark.parametrize(
    ("today", "years"),
    [(date(2026, 3, 31), [2024, 2023]), (date(2026, 4, 1), [2025, 2024])],
)
def test_reporting_year_changes_on_first_april(today: date, years: list[int]) -> None:
    tax = checked(scenario(), today)["tax"]
    assert sorted((r["year"] for r in tax["financials"]), reverse=True) == years
    assert tax["taxProfile"]["avgHeadcount"]["year"] == years[0]
    assert tax["taxProfile"]["incomeExpenses"]["year"] == years[0]
    assert all(date.fromisoformat(r["submittedAt"]) <= today for r in tax["financials"])


@pytest.mark.parametrize(
    ("registered", "years"),
    [("2026-07-21", []), ("2025-10-21", []), ("2024-01-01", [2025])],
)
def test_statements_require_complete_year_after_registration(
    registered: str, years: list[int]
) -> None:
    spec = scenario(company={"ageMonths": None, "registrationDate": registered}, bank=None)
    tax = checked(spec)["tax"]
    assert sorted((r["year"] for r in tax["financials"]), reverse=True) == years
    if not years:
        assert tax["taxProfile"]["incomeExpenses"] is None


@pytest.mark.parametrize(("months", "expected"), [(0, 0), (3, 3), (12, 12), (36, 24)])
def test_turnover_window_is_limited_by_service_and_excludes_current_month(
    months: int, expected: int
) -> None:
    rows = checked(scenario(bank={"customerSinceMonths": months}))["bankCore"]["turnover"]
    assert len(rows) == expected
    if rows:
        assert rows[-1]["month"] == "2026-09"
    if months == 3:
        assert [r["month"] for r in rows] == ["2026-07", "2026-08", "2026-09"]


def test_without_statements_turnover_is_twelve_months() -> None:
    result = checked(scenario(finance={"hasStatements": False}))
    assert len(result["bankCore"]["turnover"]) == 12
    assert result["tax"]["financials"] == []


def test_service_before_registration_is_rejected_instead_of_clamped() -> None:
    with pytest.raises(ValueError, match="регистрац|customerSince"):
        expand(scenario(company={"ageMonths": 3}, bank={"customerSinceMonths": 4}), TODAY)


def test_customer_default_service_does_not_precede_young_company_registration() -> None:
    spec = scenario(company={"ageMonths": 3}, bank={"customerSinceMonths": None})
    result = checked(spec)
    assert result["bankCore"]["customer"]["customerSince"] == "2026-07-21"
    assert len(result["bankCore"]["turnover"]) == 3


@pytest.mark.parametrize("form", ["LLC", "JSC", "IP", "SELF_EMPLOYED"])
def test_forms_get_compatible_financial_bodies(form: str) -> None:
    spec = ScenarioSpec.model_validate(
        {"code": "form-" + form.lower().replace("_", "-"), "title": form, "company": {"form": form}}
    )
    result = checked(spec)
    assert result["tax"]["financials"] == []
    assert result["bankCore"]["customer"] is None
    assert result["bankCore"]["accounts"] == result["bankCore"]["turnover"] == []
    if form == "SELF_EMPLOYED":
        assert result["tax"]["npd"] is not None
        assert result["tax"]["sme"] is None


@pytest.mark.parametrize("balance", [0, 1])
def test_non_customer_rejects_even_explicit_zero_balance(balance: int) -> None:
    spec = ScenarioSpec.model_validate(
        {
            "title": "Не клиент",
            "company": {"form": "LLC"},
            "bank": {"isCustomer": False, "balanceRub": balance},
        }
    )
    with pytest.raises(ValueError, match="клиент|isCustomer|balanceRub"):
        expand(spec, TODAY)


@pytest.mark.parametrize("subject", ["company", "director", "owner"])
def test_non_customer_rejects_our_bank_obligation(subject: str) -> None:
    spec = ScenarioSpec.model_validate(
        {
            "title": "Чужой клиент",
            "company": {"form": "LLC"},
            "bank": {"isCustomer": False},
            "bki": {
                subject: {
                    "activeLoans": [
                        {"kind": "LOAN", "amountRub": 100000, "termMonths": 12, "ourBank": True}
                    ]
                }
            },
        }
    )
    with pytest.raises(ValueError, match="клиент|isCustomer|ourBank"):
        expand(spec, TODAY)


def test_minimum_surplus_is_floor_and_impossible_floor_is_rejected() -> None:
    rows = checked(scenario(finance={"minMonthlySurplusRub": 1}))["bankCore"]["turnover"]
    assert {r["incomingNetRub"] - r["outgoingRub"] for r in rows} == {1000000}
    with pytest.raises(ValueError, match="остат|Surplus|списан|поступлен"):
        expand(scenario(finance={"minMonthlySurplusRub": 13000000}), TODAY)


def test_negative_margin_preserves_loss_without_negative_turnover_fields() -> None:
    result = checked(scenario(finance={"netMarginPercent": -10}))
    assert {r["lines"]["2400"] for r in result["tax"]["financials"]} == {-12000000}
    assert all(r["outgoingRub"] > r["incomingNetRub"] for r in result["bankCore"]["turnover"])


@pytest.mark.parametrize(
    ("annual", "headcount", "category"),
    [
        (120000000, 15, "MICRO"),
        (120000012, 15, "SMALL"),
        (120000000, 16, "SMALL"),
        (799999992, 100, "SMALL"),
        (800000004, 100, "MEDIUM"),
        (120000000, 101, "MEDIUM"),
        (1999999992, 250, "MEDIUM"),
        (2000000004, 250, None),
        (120000000, 251, None),
    ],
)
def test_sme_category_requires_both_revenue_and_headcount(
    annual: int, headcount: int, category: str | None
) -> None:
    # Целочисленная месячная выручка: соседние границы проверяются с точностью до 12 ₽.
    assert annual % 12 == 0
    monthly = annual // 12
    sme = checked(scenario(finance={"avgMonthlyRevenueRub": monthly, "headcount": headcount}))[
        "tax"
    ]["sme"]
    assert (sme["category"] if sme else None) == category


@pytest.mark.parametrize(
    ("today", "included"), [(date(2026, 10, 9), False), (date(2026, 10, 10), True)]
)
def test_sme_inclusion_waits_until_tenth_of_next_month(today: date, included: bool) -> None:
    spec = ScenarioSpec.model_validate(
        {"title": "Новая компания", "company": {"form": "LLC", "registrationDate": "2026-09-30"}}
    )
    sme = checked(spec, today)["tax"]["sme"]
    assert (sme is not None) is included
    if sme:
        assert sme["includedAt"] == "2026-10-10"
        assert sme["isNewlyCreated"] is True


def test_sme_new_status_expires_at_twelve_month_anniversary() -> None:
    spec = ScenarioSpec.model_validate(
        {"title": "Годовщина", "company": {"form": "LLC", "registrationDate": "2025-10-21"}}
    )
    assert checked(spec, date(2026, 10, 20))["tax"]["sme"]["isNewlyCreated"] is True
    assert checked(spec, TODAY)["tax"]["sme"]["isNewlyCreated"] is False


def test_noise_is_repeatable_and_overlapping_months_do_not_depend_on_window_length() -> None:
    spec = scenario(finance={"noisePercent": 5})
    first = checked(spec)
    assert first == checked(spec)
    rows = first["bankCore"]["turnover"]
    assert len({r["incomingNetRub"] for r in rows}) > 1
    short_rows = checked(scenario(finance={"noisePercent": 5, "hasStatements": False}))["bankCore"][
        "turnover"
    ]
    assert rows[-12:] == short_rows


@given(
    revenue=st.integers(min_value=10000, max_value=200000000),
    margin=st.integers(min_value=-25, max_value=50),
    vat=st.sampled_from([0, 5, 7, 10, 20, 22]),
    noise=st.integers(min_value=0, max_value=50),
)
def test_random_finances_keep_balance_and_annual_reconciliation(
    revenue: int, margin: int, vat: int, noise: int
) -> None:
    result = checked(
        scenario(
            finance={
                "avgMonthlyRevenueRub": revenue,
                "netMarginPercent": margin,
                "vatRatePercent": vat,
                "noisePercent": noise,
            }
        )
    )
    tax, rows = result["tax"], result["bankCore"]["turnover"]
    for statement in tax["financials"]:
        lines = statement["lines"]
        assert lines["1600"] == lines["1100"] + lines["1200"]
        assert lines["1600"] == lines["1300"] + lines["1400"] + lines["1500"]
    statement = next(f for f in tax["financials"] if f["year"] == 2025)
    annual = statement["lines"]["2110"]
    assert tax["taxProfile"]["incomeExpenses"]["incomeRub"] == annual
    incoming = sum(r["incomingNetRub"] for r in rows if r["month"].startswith("2025-"))
    expected = Decimal(annual) * (Decimal(1) + Decimal(vat) / 100)
    assert abs(Decimal(incoming) - expected) <= expected * Decimal("0.03")


def test_explicit_null_can_clear_inherited_bank_parameters() -> None:
    spec = ScenarioSpec.model_validate(
        {
            "title": "ИП в другом банке",
            "preset": "IP_HEALTHY",
            "bank": {"isCustomer": False, "balanceRub": None, "customerSinceMonths": None},
        }
    )
    result = checked(spec)
    assert result["bankCore"]["customer"] is None
    assert result["bankCore"]["accounts"] == result["bankCore"]["turnover"] == []


def test_vat_schedule_injection_handles_rate_change_inside_calendar_year() -> None:
    spec = scenario()
    identity = expand(spec, TODAY)["identity"]
    settings = ScenarioSettings(
        vat_rate_schedule={date(1990, 1, 1): Decimal(5), date(2025, 7, 1): Decimal(7)}
    )
    result = expand_finance(resolved_spec(spec), identity, "finance-test", TODAY, settings)
    body = BankCoreBody.model_validate(result["bankCore"])
    BankCoreAdminHandler().check(identity["inn"], body)
    year_rows = [r for r in result["bankCore"]["turnover"] if r["month"].startswith("2025-")]
    assert sum(r["incomingNetRub"] for r in year_rows) == 127200000
    assert {r["incomingNetRub"] for r in year_rows[:6]} == {10500000}
    assert {r["incomingNetRub"] for r in year_rows[6:]} == {10700000}


def test_money_half_ruble_rounds_up_before_cash_flow_subtraction() -> None:
    result = checked(scenario(finance={"avgMonthlyRevenueRub": 105, "vatRatePercent": 10}))
    rows = result["bankCore"]["turnover"]
    assert {r["incomingNetRub"] for r in rows} == {116}
    assert {r["outgoingRub"] for r in rows} == {105}
