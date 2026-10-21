"""Скоркарта, потолки грейда и PD (T-291, 30-07).

Скоринг даёт только риск; решение принимают правила продукта (D-031). Интервалы закрыты
слева («10–25%» значит `10 ≤ x < 25`), баллы лежат в политике, код только ищет интервал.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.modules.decisioning.policy import Band, Policy, TaxBand
from app.modules.decisioning.reasons import make
from app.modules.decisioning.types import FactorScore, Features, Grade, Mode, ReasonCode

_GRADE_ORDER = ["A", "B", "C", "D", "E"]


@dataclass(frozen=True, slots=True)
class ScoreResult:
    points: int
    grade: Grade
    pd: Decimal
    factors: tuple[FactorScore, ...]
    capped: ReasonCode | None  # GRADE_CAPPED, если потолок реально понизил грейд


def band_points(value: Decimal, bands: tuple[Band, ...]) -> int:
    """Интервалы «закрыты слева»: первый, у которого `value < upto`; последний — без границы."""
    for band in bands:
        if band.upto is None or value < band.upto:
            return band.points
    raise ValueError("пустая таблица интервалов")


def _tax_points(feats: Features, policy: Policy) -> int:
    cfg = policy.scorecard.tax
    if not feats.tax_known:
        return cfg.no_data
    if feats.account_block_active:
        return cfg.blocked_points
    if feats.tax_debt_rub == 0 and feats.tax_penalties_rub == 0:
        points = cfg.clean_points
    elif feats.revenue_cautious_rub is None or feats.revenue_cautious_rub <= 0:
        points = cfg.no_data
    else:
        ratio = Decimal(feats.tax_debt_rub + feats.tax_penalties_rub) / Decimal(
            feats.revenue_cautious_rub
        )
        points = _inclusive_points(ratio, cfg.bands)
    if feats.tax_offenses >= cfg.offenses_threshold:
        points -= cfg.offenses_penalty
    return max(points, 0)


def _inclusive_points(value: Decimal, bands: tuple[TaxBand, ...]) -> int:
    for band in bands:
        if band.max_ratio is None or value <= band.max_ratio:
            return band.points
    raise ValueError("пустая таблица интервалов")


def score(feats: Features, policy: Policy, mode: Mode) -> ScoreResult:
    sc = policy.scorecard
    cautious = mode == Mode.PREVIEW or not feats.bki_known
    factors: list[FactorScore] = []

    def add(code: str, value: str, points: int, maximum: int) -> None:
        factors.append(FactorScore(code, value, points, maximum))

    # SC_AGE
    if feats.business_age_months is None:
        add("SC_AGE", "нет данных", sc.age.no_data, sc.age.max_points)
    else:
        age = feats.business_age_months
        add("SC_AGE", str(age), band_points(Decimal(age), sc.age.bands), sc.age.max_points)

    # SC_CREDIT_HISTORY
    hist = sc.credit_history
    if cautious:
        history_points = hist.preview
    else:
        history_points = hist.points[feats.credit_history_class]
        if feats.restructurings_24m > 0:
            history_points = min(history_points, hist.restructuring_cap)
    add("SC_CREDIT_HISTORY", feats.credit_history_class, history_points, hist.max_points)

    # SC_INQUIRIES
    inq = sc.inquiries
    if cautious:
        inquiry_points = inq.preview
    else:
        inquiry_points = band_points(Decimal(feats.inquiries_30d), inq.inquiry_bands) + band_points(
            Decimal(feats.rejected_90d), inq.reject_bands
        )
    add(
        "SC_INQUIRIES",
        f"{feats.inquiries_30d}/{feats.rejected_90d}",
        inquiry_points,
        inq.max_points,
    )

    # SC_DEBT_LOAD
    debt = sc.debt_load
    if cautious or feats.debt_to_revenue is None:
        debt_points = debt.preview if cautious else debt.no_data
        debt_value = "нет данных"
    elif feats.total_debt_rub == 0:
        debt_points, debt_value = debt.zero_points, "0"
    else:
        debt_points = band_points(feats.debt_to_revenue, debt.bands)
        debt_value = str(feats.debt_to_revenue.quantize(Decimal("0.0001")))
    add("SC_DEBT_LOAD", debt_value, debt_points, debt.max_points)

    # SC_TREND
    if feats.revenue_trend_pct is None:
        add("SC_TREND", "нет данных", sc.trend.no_data, sc.trend.max_points)
    else:
        add(
            "SC_TREND",
            str(feats.revenue_trend_pct.quantize(Decimal("0.0001"))),
            band_points(feats.revenue_trend_pct, sc.trend.bands),
            sc.trend.max_points,
        )

    # SC_VOLATILITY
    vol = sc.volatility
    if feats.is_seasonal:
        add("SC_VOLATILITY", "сезонный", vol.seasonal_points, vol.max_points)
    elif feats.revenue_cv is None:
        add("SC_VOLATILITY", "нет данных", vol.no_data, vol.max_points)
    else:
        add(
            "SC_VOLATILITY",
            str(feats.revenue_cv.quantize(Decimal("0.0001"))),
            band_points(feats.revenue_cv, vol.bands),
            vol.max_points,
        )

    # SC_TAX
    add("SC_TAX", str(feats.tax_debt_rub), _tax_points(feats, policy), sc.tax.max_points)

    # SC_CLIENT
    cl = sc.client
    if not feats.is_bank_customer or feats.customer_tenure_months is None:
        add("SC_CLIENT", "не клиент", cl.not_client_points, cl.max_points)
    else:
        tenure = feats.customer_tenure_months
        add("SC_CLIENT", str(tenure), band_points(Decimal(tenure), cl.bands), cl.max_points)

    # SC_COVERAGE: платежей нет или запас большой — максимум
    cov = sc.coverage
    if feats.coverage_existing is None:
        add("SC_COVERAGE", "платежей нет", cov.no_data, cov.max_points)
    else:
        add(
            "SC_COVERAGE",
            str(feats.coverage_existing.quantize(Decimal("0.01"))),
            band_points(feats.coverage_existing, cov.bands),
            cov.max_points,
        )

    total = sum(f.points for f in factors)
    row = policy.grade_of(total)
    grade = row.grade
    pd = row.pd

    # Потолок грейда C: молодой бизнес, просрочка ≥ 60 дн. за 24 мес., реструктуризация
    caps = sc.caps
    reasons: list[str] = []
    if (
        feats.business_age_months is not None
        and feats.business_age_months < caps.min_business_age_months
    ):
        reasons.append("возраст бизнеса")
    if feats.max_overdue_24m_days >= caps.overdue_days:
        reasons.append("просрочка за 24 мес.")
    if feats.restructurings_24m > 0:
        reasons.append("реструктуризация за 24 мес.")
    capped: ReasonCode | None = None
    if reasons and _GRADE_ORDER.index(grade) < _GRADE_ORDER.index(caps.max_grade):
        capped = make("GRADE_CAPPED", cap=caps.max_grade, because="; ".join(reasons))
        grade = caps.max_grade
        pd = policy.grade_row(grade).pd
    return ScoreResult(total, Grade(grade), pd, tuple(factors), capped)
