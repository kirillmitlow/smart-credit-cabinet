"""Числовая проверка спецрежимов синтетического сценария, не налоговая декларация.

Проверяем модельную выручку последних 12 полных месяцев; для ПСН дополнительно
доход прошлого календарного года и с начала текущего до последнего полного месяца.
Прочие ограничения (регион, лицензии, активы) здесь не моделируются.
"""

from __future__ import annotations

from datetime import date

from app.common.clock import last_full_month
from app.common.reldate import add_months
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.finance_series import monthly_revenue
from app.roles.scenarios.schemas import FinanceSpec


def check_regime(
    finance: FinanceSpec,
    regime: str,
    form: str,
    code: str,
    today: date,
    headcount: int,
    settings: ScenarioSettings,
) -> None:
    if regime not in {"AUSN", "USN_INCOME", "USN_INCOME_MINUS_EXPENSES", "PSN"}:
        return
    anchor = last_full_month(today)
    annual = sum(
        monthly_revenue(finance, code, add_months(anchor, -i), anchor, settings) for i in range(12)
    )
    if regime == "AUSN":
        revenue_limit, staff_limit = settings.ausn_revenue_limit_rub, settings.ausn_headcount_limit
    elif regime.startswith("USN_"):
        revenue_limit, staff_limit = settings.usn_revenue_limit_rub, settings.usn_headcount_limit
    else:
        if form != "IP":
            raise ValueError("PSN: патент доступен только ИП")
        years = [year for year in settings.psn_revenue_limit_schedule if year <= today.year]
        if not years:
            raise ValueError("PSN_REVENUE_LIMIT_SCHEDULE не покрывает год сценария")
        revenue_limit = settings.psn_revenue_limit_schedule[max(years)]
        staff_limit = settings.psn_headcount_limit
        previous = sum(
            monthly_revenue(finance, code, date(today.year - 1, m, 1), anchor, settings)
            for m in range(1, 13)
        )
        current = sum(
            monthly_revenue(finance, code, date(today.year, m, 1), anchor, settings)
            for m in range(1, today.month)
        )
        annual = max(annual, previous, current)
    if annual > revenue_limit:
        raise ValueError(f"{regime}: годовая выручка {annual} ₽ превышает лимит {revenue_limit} ₽")
    if headcount > staff_limit:
        raise ValueError(f"{regime}: численность {headcount} превышает лимит {staff_limit}")
