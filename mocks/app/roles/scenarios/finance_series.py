"""Один месячный источник выручки для оборотов и отчётности, целые рубли с HALF_UP."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from app.common.reldate import add_months
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.identity_people import rng_for
from app.roles.scenarios.schemas import FinanceSpec


def rub(value: Decimal | int, quantum: int = 1) -> int:
    return int((Decimal(value) / quantum).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * quantum


def _season_weight(month: int, season: str | None) -> Decimal:
    if season == "RETAIL_Q4":
        return Decimal("1.6") if month >= 10 else Decimal("0.8")
    if season == "AGRO":
        # 12 точек sin(2π(m−6)/12), без float и зависимости от math/libm.
        root = Decimal(3).sqrt() / 2
        sin = (
            Decimal("-0.5"),
            -root,
            Decimal(-1),
            -root,
            Decimal("-0.5"),
            Decimal(0),
            Decimal("0.5"),
            root,
            Decimal(1),
            root,
            Decimal("0.5"),
            Decimal(0),
        )
        return 1 + Decimal("0.6") * sin[month - 1]
    return Decimal(1)


def _weight(finance: FinanceSpec, month: date, anchor: date, settings: ScenarioSettings) -> Decimal:
    trend = finance.revenue_trend
    percent = (
        Decimal(str(finance.trend_percent))
        if finance.trend_percent is not None
        else settings.default_trend_percent
    )
    if trend in (None, "STABLE"):
        if finance.trend_percent:
            raise ValueError("Для ненулевого trendPercent укажите GROWTH или DECLINE")
        annual_factor = Decimal(1)
    else:
        magnitude = abs(percent) / 100
        if trend == "DECLINE" and magnitude >= 1:
            raise ValueError("DECLINE: годовое снижение должно быть меньше 100%")
        annual_factor = 1 + magnitude if trend == "GROWTH" else 1 - magnitude
    offset = (month.year - anchor.year) * 12 + month.month - anchor.month
    return _season_weight(month.month, finance.seasonality) * annual_factor ** (
        Decimal(offset) / 12
    )


def monthly_revenue(
    finance: FinanceSpec,
    code: str,
    month: date,
    anchor: date | None = None,
    settings: ScenarioSettings | None = None,
) -> int:
    settings = settings or ScenarioSettings()
    if anchor is None:
        if finance.revenue_trend not in (None, "STABLE"):
            raise ValueError("Для тренда нужен общий anchor последнего полного месяца")
        anchor = month
    with localcontext() as context:
        context.prec = 40
        revenue = Decimal(finance.avg_monthly_revenue_rub or 0)
        weights = [
            _weight(finance, add_months(anchor, -index), anchor, settings) for index in range(12)
        ]
        revenue *= _weight(finance, month, anchor, settings) * 12 / sum(weights)
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
    anchor: date | None = None,
) -> dict[str, Any]:
    revenue = monthly_revenue(finance, code, month, anchor, settings)
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
