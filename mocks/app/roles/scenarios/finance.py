"""T-121: согласованные налоговые данные и часть АБС, без кредитов и raw."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.common.accounts import SETTLEMENT_IP, SETTLEMENT_LEGAL, generate_account
from app.common.clock import last_full_month, last_reporting_year, month_start
from app.common.reldate import add_months
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.finance_series import monthly_revenue, rub, turnover_month
from app.roles.scenarios.identity_people import rng_for
from app.roles.scenarios.schemas import BankSpec, FinanceSpec, ScenarioSpec, TaxSpec


def _annual(finance: FinanceSpec, code: str, year: int) -> int:
    return sum(monthly_revenue(finance, code, date(year, m, 1)) for m in range(1, 13))


def _statements(
    finance: FinanceSpec, code: str, today: date, registered: date, legal: bool
) -> list[dict[str, Any]]:
    if not finance.has_statements:
        return []
    if not legal:
        raise ValueError("У ИП и самозанятого нет бухотчётности")
    # Техническое допущение: текущий и предыдущий отчётные годы, если оба полные.
    last_year = last_reporting_year(today)
    years = range(max(registered.year + 1, last_year - 1, 1990), last_year + 1)
    margin = Decimal(
        str(finance.net_margin_percent if finance.net_margin_percent is not None else 10)
    )
    records: list[dict[str, Any]] = []
    for year in years:
        revenue = _annual(finance, code, year)
        profit = rub(Decimal(revenue) * margin / 100)
        # Балансовые доли — явное допущение синтетики. Долг/проценты добавятся после T-123.
        assets = max(10000, rub(Decimal(revenue) / 2))
        fixed = rub(Decimal(assets) * Decimal("0.4"))
        equity = rub(Decimal(assets) * Decimal("0.6"))
        records.append(
            {
                "year": year,
                "formType": "SIMPLIFIED",
                "submittedAt": date(year + 1, 3, 28).isoformat(),
                "lines": {
                    "1100": fixed,
                    "1200": assets - fixed,
                    "1300": equity,
                    "1400": 0,
                    "1500": assets - equity,
                    "1600": assets,
                    "2110": revenue,
                    "2200": profit,
                    "2330": 0,
                    "2400": profit,
                },
            }
        )
    return records


def _bank(
    spec: ScenarioSpec,
    identity: dict[str, Any],
    code: str,
    today: date,
    finance: FinanceSpec,
    regime: str,
    settings: ScenarioSettings,
) -> dict[str, Any]:
    bank = spec.bank or BankSpec()
    base: dict[str, Any] = {
        "customer": None,
        "accounts": [],
        "turnover": [],
        "loans": [],
        "compliance": None,
    }
    own_loans = (
        spec.active_loans
        + (spec.bki.company.active_loans or [] if spec.bki and spec.bki.company else [])
        + (spec.bki.owner.active_loans or [] if spec.bki and spec.bki.owner else [])
        + (spec.bki.director.active_loans or [] if spec.bki and spec.bki.director else [])
    )
    if not bank.is_customer:
        if (
            bank.balance_rub is not None
            or bank.customer_since_months is not None
            or any(x.our_bank for x in own_loans)
        ):
            raise ValueError(
                "Без клиента банка нельзя задавать balanceRub, customerSinceMonths или кредит ourBank"
            )
        return base
    if identity["form"] == "SELF_EMPLOYED":
        raise ValueError("Самозанятый не может быть клиентом банка в сценарии")
    registered = date.fromisoformat(identity["registrationDate"])
    if bank.customer_since_months is None:
        since = max(registered, add_months(today, -24))
    else:
        since = add_months(today, -bank.customer_since_months)
        if since < registered:
            raise ValueError(
                "customerSinceMonths: обслуживание не может начаться раньше регистрации"
            )
    customer_type = "INDIVIDUAL_ENTREPRENEUR" if identity["form"] == "IP" else "LEGAL_ENTITY"
    account = generate_account(
        rng_for(code, "settlement"),
        settings.bank_bik,
        SETTLEMENT_IP if identity["form"] == "IP" else SETTLEMENT_LEGAL,
    )
    base["customer"] = {
        "type": customer_type,
        "name": identity["shortName"],
        "customerSince": since.isoformat(),
    }
    base["accounts"] = [
        {
            "number": account,
            "type": "SETTLEMENT",
            "status": "OPEN",
            "openedAt": since.isoformat(),
            "balanceRub": bank.balance_rub if bank.balance_rub is not None else 0,
        }
    ]
    window = 24 if finance.has_statements else 12
    last = last_full_month(today)
    first = max(add_months(last, 1 - window), month_start(since))
    month = first
    while month <= last:
        base["turnover"].append(
            turnover_month(finance, code, month, regime, identity["okved"], settings)
        )
        month = add_months(month, 1)
    return base


def expand_finance(
    spec: ScenarioSpec,
    identity: dict[str, Any],
    code: str,
    today: date,
    settings: ScenarioSettings | None = None,
) -> dict[str, Any]:
    settings = settings or ScenarioSettings()
    finance = spec.finance or FinanceSpec()
    tax_spec = spec.tax or TaxSpec()
    legal = identity["form"] in ("LLC", "JSC")
    registered = date.fromisoformat(identity["registrationDate"])
    regime = finance.tax_regime or (
        "OSNO" if legal else "NPD" if identity["form"] == "SELF_EMPLOYED" else "USN_INCOME"
    )
    if regime not in (
        "OSNO",
        "USN_INCOME",
        "USN_INCOME_MINUS_EXPENSES",
        "PSN",
        "ESHN",
        "AUSN",
        "NPD",
    ):
        raise ValueError("Неизвестный taxRegime")
    records = _statements(finance, code, today, registered, legal)
    year = last_reporting_year(today)
    annual = _annual(finance, code, year)
    headcount = finance.headcount if finance.headcount is not None else 1
    latest = records[-1] if records else None
    profile: dict[str, Any] | None = {
        "inn": identity["inn"],
        "taxRegimes": [{"code": regime, "year": year}],
        "avgHeadcount": {"value": headcount, "year": year},
        "taxesPaid": [{"year": year, "totalRub": 0}],
        "debts": {
            "asOf": today.isoformat(),
            "taxDebtRub": tax_spec.tax_debt_rub or 0,
            "penaltiesRub": 0,
            "finesRub": 0,
        },
        "incomeExpenses": {
            "year": latest["year"],
            "incomeRub": latest["lines"]["2110"],
            "expensesRub": latest["lines"]["2110"] - latest["lines"]["2400"],
        }
        if latest and latest["lines"]["2400"] <= latest["lines"]["2110"]
        else None,
        "taxOffenses": {"year": year, "count": 0, "finesRub": 0},
        "riskFlags": {
            "massAddress": tax_spec.mass_address or False,
            "massDirector": tax_spec.mass_director or False,
            "massFounder": False,
            "disqualifiedManagement": tax_spec.disqualified_management or False,
            "noReportsOverYear": False,
        },
    }
    included = add_months(month_start(registered), 1).replace(day=10)
    band = next(
        (
            x
            for x in settings.sme_thresholds
            if annual <= x.revenue_rub and headcount <= x.headcount
        ),
        None,
    )
    sme = (
        {
            "category": band.category,
            "includedAt": included.isoformat(),
            "isNewlyCreated": today < add_months(registered, 12),
            "isSocialEnterprise": False,
        }
        if band and included <= today
        else None
    )
    npd = None
    if identity["form"] == "SELF_EMPLOYED":
        profile, sme = None, None
        npd = {"registeredAt": registered.isoformat(), "deregisteredAt": None}
    return {
        "tax": {
            "taxProfile": profile,
            "financials": records,
            "sme": sme,
            "npd": npd,
            "accountBlocks": [],
            "contracts": [],
        },
        "bankCore": _bank(spec, identity, code, today, finance, regime, settings),
    }
