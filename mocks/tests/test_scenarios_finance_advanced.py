"""T-122: тренд/сезонность сохраняют общий источник; нарушения только явные."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.common.reldate import add_months
from app.roles.bank_core.admin import BankCoreAdminHandler
from app.roles.bank_core.schemas import BankCoreBody
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.finance import expand_finance
from app.roles.scenarios.finance_series import monthly_revenue
from app.roles.scenarios.identity import expand_identity
from app.roles.scenarios.schemas import FinanceSpec, ScenarioSpec
from app.roles.tax.admin import TaxHandler
from app.roles.tax.schemas import TaxBody

TODAY = date(2026, 10, 21)
ANCHOR = date(2026, 9, 1)


def result(
    finance: dict[str, Any] | None = None,
    *,
    form: str = "LLC",
    today: date = TODAY,
    bank: bool = True,
    settings: ScenarioSettings | None = None,
    code: str = "advanced-finance",
) -> dict[str, Any]:
    spec = ScenarioSpec.model_validate(
        {
            "code": code,
            "title": "Тренд и сезонность",
            "company": {"form": form, "ageMonths": 120},
            "finance": {
                "avgMonthlyRevenueRub": 1000000,
                "hasStatements": form in {"LLC", "JSC"},
                "noisePercent": 0,
                "netMarginPercent": 10,
                "headcount": 5,
                "taxRegime": "OSNO",
                **(finance or {}),
            },
            "bank": {"isCustomer": bank, **({"customerSinceMonths": 36} if bank else {})},
        }
    )
    identity = expand_identity(spec, code, today, set())["identity"]
    data = expand_finance(spec, identity, code, today, settings)
    TaxHandler().check(identity["inn"], TaxBody.model_validate(data["tax"]))
    BankCoreAdminHandler().check(identity["inn"], BankCoreBody.model_validate(data["bankCore"]))
    return data


@pytest.mark.parametrize(
    ("trend", "percent", "factor"),
    [
        ("GROWTH", 20, Decimal("1.2")),
        ("GROWTH", -20, Decimal("1.2")),
        ("DECLINE", 20, Decimal("0.8")),
        ("DECLINE", -20, Decimal("0.8")),
    ],
)
def test_trend_is_annual_geometric_change_with_normalized_recent_average(
    trend: str,
    percent: int,
    factor: Decimal,
) -> None:
    finance = FinanceSpec(
        avg_monthly_revenue_rub=1000000, revenue_trend=trend, trend_percent=percent, noise_percent=0
    )
    rows = [monthly_revenue(finance, "trend", add_months(ANCHOR, -i), ANCHOR) for i in range(12)]
    assert abs(sum(rows) - 12000000) <= 6
    assert rows == sorted(rows, reverse=trend == "GROWTH")
    previous = monthly_revenue(finance, "trend", add_months(ANCHOR, -12), ANCHOR)
    assert abs(Decimal(rows[0]) - Decimal(previous) * factor) <= 1


def test_default_trend_percentage_is_configurable() -> None:
    finance = FinanceSpec(avg_monthly_revenue_rub=1000000, revenue_trend="GROWTH", noise_percent=0)
    settings = ScenarioSettings(default_trend_percent=25)
    now = monthly_revenue(finance, "trend", ANCHOR, ANCHOR, settings)
    previous = monthly_revenue(finance, "trend", add_months(ANCHOR, -12), ANCHOR, settings)
    assert abs(Decimal(now) - Decimal(previous) * Decimal("1.25")) <= 1


def test_agro_calendar_snapshot_and_zarya_peaks() -> None:
    finance = FinanceSpec(avg_monthly_revenue_rub=54166667, seasonality="AGRO", noise_percent=0)
    months = [
        monthly_revenue(finance, "arbitrary-code", date(2025, m, 1), ANCHOR) for m in range(1, 13)
    ]
    assert months == [
        37916667,
        26020841,
        21666667,
        26020841,
        37916667,
        54166667,
        70416667,
        82312493,
        86666667,
        82312493,
        70416667,
        54166667,
    ]
    assert sum(months) == 650000004
    assert months.index(max(months)) == 8
    assert months.index(min(months)) == 2
    data = result(
        {"avgMonthlyRevenueRub": 54166667, "seasonality": "AGRO", "taxRegime": "ESHN"}, form="JSC"
    )
    statement = next(s for s in data["tax"]["financials"] if s["year"] == 2025)
    turnovers = [r for r in data["bankCore"]["turnover"] if r["month"].startswith("2025-")]
    assert [r["incomingNetRub"] for r in turnovers] == months
    assert statement["lines"]["2110"] == sum(months)


def test_retail_q4_weights_do_not_change_annual_average() -> None:
    data = result({"seasonality": "RETAIL_Q4", "vatRatePercent": 0})
    rows = [r for r in data["bankCore"]["turnover"] if r["month"].startswith("2025-")]
    assert [r["incomingNetRub"] for r in rows] == [800000] * 9 + [1600000] * 3
    statement = next(s for s in data["tax"]["financials"] if s["year"] == 2025)
    assert statement["lines"]["2110"] == 12000000


def test_mismatch_changes_reporting_but_preserves_cash_and_other_invariants() -> None:
    clean = result({"avgMonthlyRevenueRub": 15000000})
    bad = result({"avgMonthlyRevenueRub": 15000000, "statementsMismatchPercent": 40})
    assert bad["bankCore"] == clean["bankCore"]
    for statement in bad["tax"]["financials"]:
        lines = statement["lines"]
        assert lines["2110"] == 108000000
        assert lines["2400"] == 10800000
        assert lines["1600"] == lines["1100"] + lines["1200"]
        assert lines["1600"] == lines["1300"] + lines["1400"] + lines["1500"]
    assert bad["tax"]["taxProfile"]["incomeExpenses"]["incomeRub"] == 108000000
    assert bad["tax"]["sme"]["category"] == "MICRO"
    assert clean["tax"]["sme"]["category"] == "SMALL"
    statement = next(s for s in bad["tax"]["financials"] if s["year"] == 2025)
    incoming = sum(
        r["incomingNetRub"] for r in bad["bankCore"]["turnover"] if r["month"].startswith("2025-")
    )
    mismatch = (Decimal(incoming) / Decimal("1.2") / statement["lines"]["2110"] - 1) * 100
    assert abs(mismatch - Decimal("66.6666666667")) < Decimal("0.000001")


@pytest.mark.parametrize("age_months", [0, 6, 12, 21])
def test_mismatch_requires_an_actual_full_reporting_year(age_months: int) -> None:
    spec = ScenarioSpec.model_validate(
        {
            "title": "Молодая компания без полного отчётного года",
            "company": {"form": "LLC", "ageMonths": age_months},
            "finance": {"hasStatements": True, "statementsMismatchPercent": 40},
        }
    )
    identity = expand_identity(spec, "young-mismatch", TODAY, set())["identity"]
    with pytest.raises(ValueError, match="statementsMismatchPercent.*отчётный год"):
        expand_finance(spec, identity, "young-mismatch", TODAY)
    # Без намеренного расхождения молодая компания остаётся допустимой.
    clean = spec.model_copy(
        update={"finance": FinanceSpec(has_statements=True, statements_mismatch_percent=0)}
    )
    assert expand_finance(clean, identity, "young-mismatch", TODAY)["tax"]["financials"] == []


@pytest.mark.parametrize(
    ("regime", "monthly", "staff", "form"),
    [
        ("AUSN", 5000000, 5, "LLC"),
        ("USN_INCOME", 40875000, 130, "LLC"),
        ("USN_INCOME_MINUS_EXPENSES", 40875000, 130, "IP"),
        ("PSN", 1666666, 15, "IP"),
    ],
)
def test_regime_boundaries_accept_inclusive_and_reject_next_monthly_ruble_or_employee(
    regime: str,
    monthly: int,
    staff: int,
    form: str,
) -> None:
    finance = {"taxRegime": regime, "avgMonthlyRevenueRub": monthly, "headcount": staff}
    result(finance, form=form)
    with pytest.raises(ValueError, match=regime):
        result({**finance, "avgMonthlyRevenueRub": monthly + 1}, form=form)
    with pytest.raises(ValueError, match=regime):
        result({**finance, "headcount": staff + 1}, form=form)


@pytest.mark.parametrize(
    ("year", "monthly", "limit"),
    [
        (2025, 5000000, 60000000),
        (2026, 1666666, 20000000),
        (2027, 1250000, 15000000),
        (2028, 833333, 10000000),
        (2029, 833333, 10000000),
    ],
)
def test_psn_uses_year_specific_limits(year: int, monthly: int, limit: int) -> None:
    result(
        {"taxRegime": "PSN", "avgMonthlyRevenueRub": monthly}, form="IP", today=date(year, 10, 21)
    )
    with pytest.raises(ValueError, match=str(limit)):
        result(
            {"taxRegime": "PSN", "avgMonthlyRevenueRub": monthly + 1},
            form="IP",
            today=date(year, 10, 21),
        )


def test_psn_also_checks_previous_calendar_year() -> None:
    # Последние12месяцев18млн, но при спаде прошлый календарный год превысил20млн.
    with pytest.raises(ValueError, match="PSN"):
        result(
            {
                "taxRegime": "PSN",
                "avgMonthlyRevenueRub": 1500000,
                "revenueTrend": "DECLINE",
                "trendPercent": 50,
            },
            form="IP",
        )


def test_mismatch_cannot_hide_excess_revenue_from_regime_check() -> None:
    with pytest.raises(ValueError, match="AUSN"):
        result(
            {"taxRegime": "AUSN", "avgMonthlyRevenueRub": 6000000, "statementsMismatchPercent": 50}
        )


def test_regime_settings_are_injected_instead_of_hardcoded() -> None:
    with pytest.raises(ValueError, match="AUSN.*1200"):
        result({"taxRegime": "AUSN"}, settings=ScenarioSettings(ausn_revenue_limit_rub=1200))
    result(
        {"taxRegime": "PSN", "avgMonthlyRevenueRub": 2000000},
        form="IP",
        settings=ScenarioSettings(psn_revenue_limit_schedule={2026: 24000000}),
    )


@pytest.mark.parametrize(
    ("finance", "message", "form"),
    [
        ({"revenueTrend": "DECLINE", "trendPercent": 100}, "DECLINE", "LLC"),
        ({"revenueTrend": "DECLINE", "trendPercent": 120}, "DECLINE", "LLC"),
        ({"revenueTrend": "STABLE", "trendPercent": 5}, "GROWTH", "LLC"),
        ({"trendPercent": 5}, "GROWTH", "LLC"),
        ({"hasStatements": False, "statementsMismatchPercent": 40}, "hasStatements", "LLC"),
        ({"taxRegime": "PSN"}, "только ИП", "LLC"),
    ],
)
def test_inconsistent_parameters_are_rejected(
    finance: dict[str, Any], message: str, form: str
) -> None:
    with pytest.raises(ValueError, match=message):
        result(finance, form=form)


@given(
    revenue=st.integers(10000, 20000000),
    trend=st.sampled_from(["GROWTH", "DECLINE"]),
    percent=st.integers(0, 75),
    season=st.sampled_from(["NONE", "AGRO", "RETAIL_Q4"]),
)
def test_trend_and_season_keep_monthly_and_annual_source_consistent(
    revenue: int,
    trend: str,
    percent: int,
    season: str,
) -> None:
    finance = {
        "avgMonthlyRevenueRub": revenue,
        "revenueTrend": trend,
        "trendPercent": percent,
        "seasonality": season,
        "vatRatePercent": 0,
    }
    data = result(finance)
    rows = data["bankCore"]["turnover"]
    assert abs(sum(r["incomingNetRub"] for r in rows[-12:]) - revenue * 12) <= 6
    for statement in data["tax"]["financials"]:
        matching = [r for r in rows if r["month"].startswith(str(statement["year"]) + "-")]
        if len(matching) == 12:
            assert sum(r["incomingNetRub"] for r in matching) == statement["lines"]["2110"]
    assert all(0 <= r["incomingNetRub"] <= r["incomingRub"] for r in rows)


def test_shared_months_do_not_depend_on_turnover_window() -> None:
    finance = {
        "revenueTrend": "GROWTH",
        "trendPercent": 20,
        "seasonality": "RETAIL_Q4",
        "noisePercent": 5,
    }
    long = result(finance)["bankCore"]["turnover"]
    short = result({**finance, "hasStatements": False})["bankCore"]["turnover"]
    assert long[-12:] == short


def test_generated_finance_does_not_special_case_scenario_codes() -> None:
    first = result(code="t-anomaly")["bankCore"]["turnover"]
    second = result(code="any-other-code")["bankCore"]["turnover"]
    keys = ("month", "incomingRub", "incomingNetRub", "outgoingRub")
    assert len(first) == 24
    assert [{key: row[key] for key in keys} for row in first] == [
        {key: row[key] for key in keys} for row in second
    ]


@pytest.mark.parametrize(
    ("okved", "minimum", "maximum"),
    [
        ("47.19", 1, 3),
        ("56.10", 1, 3),
        ("55.10", 1, 3),
        ("96.01", 1, 3),
        ("01.11", 3, 12),
        ("02.20", 3, 12),
        ("03.10", 3, 12),
        ("62.01", 5, 60),
    ],
)
def test_counterparty_ranges_follow_industry(okved: str, minimum: int, maximum: int) -> None:
    from app.roles.scenarios.finance_series import turnover_month

    finance = FinanceSpec(avg_monthly_revenue_rub=1000000, noise_percent=0)
    row = turnover_month(finance, "industry", ANCHOR, "USN_INCOME", okved, ScenarioSettings())
    assert minimum <= row["counterpartiesIn"] <= maximum
    assert 10 <= row["counterpartiesOut"] <= 40


def test_psn_schedule_must_cover_scenario_year() -> None:
    with pytest.raises(ValueError, match="PSN_REVENUE_LIMIT_SCHEDULE"):
        result(
            {"taxRegime": "PSN"},
            form="IP",
            settings=ScenarioSettings(psn_revenue_limit_schedule={2027: 15000000}),
        )
