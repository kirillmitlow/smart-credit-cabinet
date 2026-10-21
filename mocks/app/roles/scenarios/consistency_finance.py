"""Отчётность, обороты, МСП и числовые пределы спецрежимов (10.3)."""

from datetime import date
from decimal import Decimal
from typing import Any

from app.common.clock import last_full_month, last_reporting_year, month_start
from app.common.reldate import add_months
from app.roles.scenarios.consistency_common import Context, require
from app.roles.scenarios.debt_history import debt_totals
from app.roles.scenarios.finance_limits import check_regime
from app.roles.scenarios.finance_series import monthly_revenue, vat_rate
from app.roles.scenarios.schemas import FinanceSpec


def report_years(c: Context) -> None:
    registered = date.fromisoformat(c.identity["registrationDate"])
    latest = last_reporting_year(c.today)
    for record in c.tax["financials"]:
        year = record["year"]
        require(
            registered.year < year <= latest,
            f"Отчётный год {year}: допустимы полные годы после {registered.year}, не позже {latest}",
        )
        submitted = date.fromisoformat(record["submittedAt"])
        require(
            date(year + 1, 1, 1) <= submitted <= c.today,
            f"Дата сдачи {submitted} для отчётности {year} вне допустимого периода",
        )


def report_balance(c: Context) -> None:
    for record in c.tax["financials"]:
        lines = record["lines"]
        require(
            lines["1600"]
            == lines["1100"] + lines["1200"]
            == lines["1300"] + lines["1400"] + lines["1500"],
            f"Баланс {record['year']} не сходится: 1600={lines['1600']}, "
            f"актив={lines['1100'] + lines['1200']}, "
            f"пассив={lines['1300'] + lines['1400'] + lines['1500']}",
        )


def pb_revenue(c: Context) -> None:
    if not c.tax["financials"]:
        return
    profile = c.tax["taxProfile"]
    income = profile and profile["incomeExpenses"]
    if income is None:
        raise ValueError("При отчётности нужен доход Прозрачного бизнеса")
    statement = next((r for r in c.tax["financials"] if r["year"] == income["year"]), None)
    if statement is None:
        raise ValueError(f"Для дохода ПБ за {income['year']} нет отчётности")
    revenue = statement["lines"]["2110"]
    require(
        income["incomeRub"] == revenue,
        f"Доход ПБ {income['incomeRub']} не равен строке 2110 {revenue} за {income['year']}",
    )


def _net_revenue(c: Context, row: dict[str, Any]) -> Decimal:
    finance = c.spec.finance or FinanceSpec()
    regime = finance.tax_regime or (
        "OSNO" if c.identity["form"] in {"LLC", "JSC"} else "USN_INCOME"
    )
    month = date.fromisoformat(row["month"] + "-01")
    return Decimal(row["incomingNetRub"]) / (1 + vat_rate(finance, regime, month, c.settings) / 100)


def turnover_revenue(c: Context) -> None:
    if c.spec.finance and c.spec.finance.statements_mismatch_percent:
        return  # Единственное разрешённое исключение относится только к этой сверке.
    for record in c.tax["financials"]:
        rows = [r for r in c.bank["turnover"] if r["month"].startswith(f"{record['year']}-")]
        if len(rows) != 12:
            continue
        actual = sum((_net_revenue(c, row) for row in rows), Decimal(0))
        revenue = record["lines"]["2110"]
        require(
            abs(actual - revenue) <= abs(Decimal(revenue)) * Decimal("0.03"),
            f"Обороты без НДС {actual:.2f} и 2110={revenue} за {record['year']} расходятся больше 3%",
        )


def turnover_window(c: Context) -> None:
    if c.bank["customer"] is None:
        return
    since = date.fromisoformat(c.bank["customer"]["customerSince"])
    last = last_full_month(c.today)
    window = 24 if c.spec.finance and c.spec.finance.has_statements else 12
    first = max(add_months(last, 1 - window), month_start(since))
    expected = []
    while first <= last:
        expected.append(first.strftime("%Y-%m"))
        first = add_months(first, 1)
    actual = sorted(r["month"] for r in c.bank["turnover"])
    require(
        actual == expected,
        f"Окно оборотов {actual} не совпадает с полными месяцами обслуживания {expected}",
    )


def customer_age(c: Context) -> None:
    customer = c.bank["customer"]
    if customer is not None:
        since = customer["customerSince"]
        require(
            c.identity["registrationDate"] <= since <= c.today.isoformat(),
            f"Обслуживание с {since}, регистрация {c.identity['registrationDate']}, сегодня {c.today}",
        )


def non_customer_data(c: Context) -> None:
    if not (c.spec.bank and c.spec.bank.is_customer):
        require(
            c.bank["customer"] is None
            and not any(c.bank[k] for k in ("accounts", "turnover", "loans")),
            "У не-клиента не должно быть счёта, оборотов или кредитов нашего банка",
        )
    else:
        require(c.bank["customer"] is not None, "У клиента отсутствует карточка АБС")


def sme_category(c: Context) -> None:
    if c.identity["form"] == "SELF_EMPLOYED":
        return
    finance = c.spec.finance or FinanceSpec()
    if c.tax["financials"]:
        annual = max(c.tax["financials"], key=lambda r: r["year"])["lines"]["2110"]
    else:
        year = last_reporting_year(c.today)
        annual = sum(
            monthly_revenue(finance, c.code, date(year, m, 1), last_full_month(c.today), c.settings)
            for m in range(1, 13)
        )
    profile = c.tax["taxProfile"]
    require(
        profile is not None and profile["avgHeadcount"] is not None,
        "Для МСП нужна численность сотрудников",
    )
    staff = profile["avgHeadcount"]["value"]
    band = next(
        (b for b in c.settings.sme_thresholds if annual <= b.revenue_rub and staff <= b.headcount),
        None,
    )
    included = add_months(
        month_start(date.fromisoformat(c.identity["registrationDate"])), 1
    ).replace(day=10)
    expected = band.category if band and included <= c.today else None
    actual = c.tax["sme"]["category"] if c.tax["sme"] else None
    require(
        actual == expected,
        f"МСП={actual}, при выручке {annual} и штате {staff} требуется {expected}",
    )


def regime_limits(c: Context) -> None:
    profile = c.tax["taxProfile"]
    if profile is None:
        return
    staff = (profile["avgHeadcount"] or {}).get("value", 1)
    revenue = max((r["lines"]["2110"] for r in c.tax["financials"]), default=0)
    rows = sorted(c.bank["turnover"], key=lambda r: r["month"])[-12:]
    if len(rows) == 12:
        revenue = max(revenue, int(sum((_net_revenue(c, r) for r in rows), Decimal(0))))
    finance = c.spec.finance or FinanceSpec()
    regimes = {r["code"] for r in profile["taxRegimes"]}
    if finance.tax_regime:
        regimes.add(finance.tax_regime)
    for regime in regimes:
        check_regime(
            finance,
            regime,
            c.identity["form"],
            c.code,
            c.today,
            staff,
            c.settings,
            annual_override=revenue,
        )


def statement_debt(c: Context) -> None:
    if not c.tax["financials"]:
        return
    record = max(c.tax["financials"], key=lambda r: r["year"])
    totals = debt_totals(c.data, c.history, record["year"])
    lines = record["lines"]
    low, high = totals.interest_bounds
    require(
        0 <= lines["1400"] <= totals.year_end,
        f"1400={lines['1400']}, долг на 31.12.{record['year']}={totals.year_end}",
    )
    require(
        low <= lines["2330"] <= high,
        f"2330={lines['2330']}, средний долг {totals.average:.2f}, допустимые целые проценты 2–25%: {low}…{high}",
    )
    require(
        totals.year_end == 0 or lines["2330"] > 0,
        "При долге на конец года проценты 2330 должны быть положительными",
    )
