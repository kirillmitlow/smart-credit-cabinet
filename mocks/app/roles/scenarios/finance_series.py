"""Один месячный источник выручки для оборотов и отчётности, целые рубли с HALF_UP."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.identity_people import rng_for
from app.roles.scenarios.schemas import FinanceSpec


def rub(value: Decimal | int, quantum: int = 1) -> int:
    return int((Decimal(value) / quantum).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * quantum


def monthly_revenue(finance: FinanceSpec, code: str, month: date) -> int:
    revenue = Decimal(finance.avg_monthly_revenue_rub or 0)
    amplitude = Decimal(str(finance.noise_percent if finance.noise_percent is not None else 5))
    rng = rng_for(code, f"revenue:{month:%Y-%m}")
    noise = Decimal(rng.randint(-1_000_000, 1_000_000)) / Decimal(1_000_000)
    return rub(revenue * (1 + noise * amplitude / 100))


def vat_rate(finance: FinanceSpec, regime: str, month: date, settings: ScenarioSettings) -> Decimal:
    if finance.vat_rate_percent is not None:
        return Decimal(str(finance.vat_rate_percent))
    if regime != "OSNO":
        return Decimal(0)
    dates = [d for d in settings.vat_rate_schedule if d <= month]
    if not dates:
        raise ValueError("VAT_RATE_SCHEDULE не покрывает месяц расчёта")
    return settings.vat_rate_schedule[max(dates)]


def turnover_month(
    finance: FinanceSpec,
    code: str,
    month: date,
    regime: str,
    okved: str,
    settings: ScenarioSettings,
) -> dict[str, Any]:
    revenue = monthly_revenue(finance, code, month)
    with_vat = Decimal(revenue) * (1 + vat_rate(finance, regime, month, settings) / 100)
    rng = rng_for(code, f"turnover:{month:%Y-%m}")
    if finance.noise_percent == 0:
        incoming_net = rub(with_vat)
        incoming = max(incoming_net, rub(Decimal(incoming_net) * Decimal("1.0075"), 100))
    else:
        incoming = rub(with_vat)
        clean_factor = 1 - Decimal(rng.randint(5000, 10000)) / 1_000_000
        incoming_net = rub(Decimal(incoming) * clean_factor)
    margin = Decimal(
        str(finance.net_margin_percent if finance.net_margin_percent is not None else 10)
    )
    surplus = rub(Decimal(revenue) * margin / 100)
    if finance.min_monthly_surplus_rub is not None:
        surplus = max(surplus, finance.min_monthly_surplus_rub)
    outgoing = incoming_net - surplus
    if outgoing < 0:
        raise ValueError(f"minMonthlySurplusRub/маржа превышает поступления месяца {month:%Y-%m}")
    industry = int(okved[:2])
    if industry in (47, 55, 56, 96):
        counterparties_in = rng.randint(1, 3)
    elif 1 <= industry <= 3:
        counterparties_in = rng.randint(3, 12)
    else:
        counterparties_in = max(5, min(60, revenue // 500_000))
    return {
        "month": month.strftime("%Y-%m"),
        "incomingRub": incoming,
        "incomingNetRub": incoming_net,
        "outgoingRub": outgoing,
        "counterpartiesIn": counterparties_in if incoming else 0,
        "counterpartiesOut": max(10, min(40, 10 + revenue // 500_000)) if outgoing else 0,
    }
