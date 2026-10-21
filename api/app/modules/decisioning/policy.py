"""Схема политики (T-281, 30-13): пороги, баллы и ставки приходят в ядро данными.

Файл `policy/vN.yaml` читает `pipeline`; сюда попадает уже словарь. Правило схемы: каждый
узел с числами (параметр, строка таблицы, таблица) несёт `source` и `note`; число без источника
не проходит проверку. Деньги — целые рубли, доли и ставки — строки (`"0.24"`), не `float`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

_SOURCE_RE = re.compile(r"^(?:\d{2}-\d{2}|D-\d{3}|R-\d{3}|допущение: \S.*)")


class PolicyError(ValueError):
    """Политика не прошла проверку схемы."""


def _no_float(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError('число задаётся строкой ("0.24"), а не float/bool')
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(str(value))
    raise ValueError("ожидалась строка с десятичным числом")


Dec = Annotated[Decimal, BeforeValidator(_no_float)]
Rub = StrictInt


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Cited(_Strict):
    """Узел с числами: источник и комментарий обязательны."""

    source: str = Field(min_length=1)
    note: str = Field(min_length=1)

    @field_validator("source")
    @classmethod
    def _source_is_traceable(cls, value: str) -> str:
        if not _SOURCE_RE.match(value):
            raise ValueError(
                "source — раздел плана NN-NN (30-18, 10-06…), решение D-NNN или «допущение: …», "
                f"получено: {value!r}"
            )
        return value


class DecParam(Cited):
    value: Dec


class IntParam(Cited):
    value: StrictInt


# ---------------------------------------------------------------- meta


class Meta(_Strict):
    version: StrictInt
    effective_from: date
    key_rate_date: date
    description: str
    parent_hash: str | None = None


# ---------------------------------------------------------------- catalog


class Repayment(StrEnum):
    ANNUITY = "ANNUITY"
    BULLET = "BULLET"
    LINE = "LINE"
    OVERDRAFT = "OVERDRAFT"


class GradeAccess(StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    NO = "NO"


class ProductConfig(Cited):
    repayment: Repayment
    amount_min_rub: Rub
    amount_max_rub: Rub
    term_min_months: StrictInt
    term_max_months: StrictInt
    # None — залог не требуется никогда; 0 — требуется всегда
    collateral_required_above_rub: Rub | None
    min_business_age_months: StrictInt
    requires_bank_customer: bool
    min_customer_turnover_months: StrictInt
    requires_contract: bool
    base_rate: Dec
    expense_rate: Dec
    # Авто-решение для грейда B; None — без предела (овердрафт ограничен 30% поступлений)
    auto_limit_b_rub: Rub | None
    grade_access: dict[str, GradeAccess]
    # Для грейда D: что обязательно и до какой доли максимума продукта (30-07)
    grade_d_requires: str | None = None
    grade_d_max_share_of_max: Dec | None = None

    @model_validator(mode="after")
    def _check(self) -> ProductConfig:
        if set(self.grade_access) != {"A", "B", "C", "D", "E"}:
            raise ValueError("grade_access должен покрывать грейды A–E")
        if self.grade_d_requires not in (None, "SECURITY", "COLLATERAL"):
            raise ValueError("grade_d_requires: SECURITY | COLLATERAL | null")
        if self.amount_min_rub > self.amount_max_rub or self.term_min_months > self.term_max_months:
            raise ValueError("границы суммы/срока перепутаны")
        return self


class Catalog(_Strict):
    products: dict[str, ProductConfig]
    rate_corridor: DecParam  # ± от базовой ставки продукта (доля: 0.04 = 4 п.п.)

    @field_validator("products")
    @classmethod
    def _all_six(cls, value: dict[str, ProductConfig]) -> dict[str, ProductConfig]:
        expected = {
            "EXPRESS",
            "WORKING_CAPITAL",
            "CONTRACT",
            "CREDIT_LINE",
            "OVERDRAFT",
            "INVESTMENT",
        }
        if set(value) != expected:
            raise ValueError(f"в каталоге должны быть ровно продукты {sorted(expected)}")
        return value


# ---------------------------------------------------------------- eligibility, stop factors


class Toggle(Cited):
    enabled: bool


class NotActiveRule(Toggle):
    legal_entity_statuses: tuple[str, ...]
    entrepreneur_statuses: tuple[str, ...]


class BankruptcyRule(Toggle):
    window_months: StrictInt
    founder_share_percent: Dec


class ForbiddenIndustryRule(Toggle):
    okved_prefixes: tuple[str, ...]


class TaxArrearsRule(Toggle):
    max_ratio: Dec


class OverdueRule(Toggle):
    days: StrictInt
    min_rub: Rub


class Eligibility(_Strict):
    self_employed: Toggle


class StopFactors(_Strict):
    company_not_active: NotActiveRule
    aml_list: Toggle
    bankruptcy: BankruptcyRule
    forbidden_industry: ForbiddenIndustryRule
    duplicate_application: Toggle
    tax_arrears_high: TaxArrearsRule
    current_overdue_90: OverdueRule


class Restrictions(_Strict):
    business_too_young: IntParam  # месяцев


# ---------------------------------------------------------------- features


class VatRow(_Strict):
    since: date
    rate: Dec


class Vat(Cited):
    regime_code: str
    schedule: tuple[VatRow, ...]


class IndustryRange(_Strict):
    group: str
    from_prefix: StrictInt
    to_prefix: StrictInt


class Industry(Cited):
    ranges: tuple[IndustryRange, ...]
    default_group: str
    margins: dict[str, Dec]


class RevenueParams(Cited):
    window_long_months: StrictInt
    window_short_months: StrictInt
    short_history_months: StrictInt
    short_history_factor: Dec
    fresh_financials_months: StrictInt


class Seasonality(Cited):
    min_months: StrictInt
    min_correlation: Dec
    min_cv: Dec
    okved_prefixes: tuple[str, ...]


class TrendParams(Cited):
    min_points: StrictInt
    max_points: StrictInt


class StressParams(Cited):
    shock_min: Dec
    shock_max: Dec


class DebtParams(Cited):
    contingent_weight: Dec
    overdue_min_rub: Rub


class HistoryParams(Cited):
    thin_min_obligations: StrictInt
    clean_min_history_months: StrictInt


class BadMonthParams(Cited):
    share_of_median: Dec


class FeatureParams(_Strict):
    vat: Vat
    industry: Industry
    revenue: RevenueParams
    seasonality: Seasonality
    trend: TrendParams
    stress: StressParams
    debt: DebtParams
    history: HistoryParams
    bad_month: BadMonthParams


# ---------------------------------------------------------------- scorecard, master scale


class Band(_Strict):
    """Интервал «закрыт слева»: `x < upto` → `points`; последний интервал без `upto`."""

    upto: Dec | None = None
    points: StrictInt


def _check_bands(bands: tuple[Band, ...]) -> None:
    if not bands or bands[-1].upto is not None:
        raise ValueError("последний интервал должен быть без upto")
    uptos = [b.upto for b in bands[:-1]]
    if any(u is None for u in uptos):
        raise ValueError("upto задан у всех интервалов, кроме последнего")
    values = [u for u in uptos if u is not None]
    if values != sorted(values) or len(set(values)) != len(values):
        raise ValueError("границы интервалов должны строго возрастать")


class BandFactor(Cited):
    max_points: StrictInt
    no_data: StrictInt
    bands: tuple[Band, ...]

    @model_validator(mode="after")
    def _bands_ok(self) -> BandFactor:
        _check_bands(self.bands)
        return self


class DebtLoadFactor(BandFactor):
    zero_points: StrictInt
    preview: StrictInt


class VolatilityFactor(BandFactor):
    seasonal_points: StrictInt


class HistoryFactor(Cited):
    max_points: StrictInt
    no_data: StrictInt
    preview: StrictInt
    points: dict[str, StrictInt]
    restructuring_cap: StrictInt


class InquiriesFactor(Cited):
    max_points: StrictInt
    no_data: StrictInt
    preview: StrictInt
    inquiry_bands: tuple[Band, ...]
    reject_bands: tuple[Band, ...]

    @model_validator(mode="after")
    def _bands_ok(self) -> InquiriesFactor:
        _check_bands(self.inquiry_bands)
        _check_bands(self.reject_bands)
        return self


class TaxBand(_Strict):
    """Интервал «не более»: `ratio <= max_ratio` → `points`; последний без `max_ratio`."""

    max_ratio: Dec | None = None
    points: StrictInt


class TaxFactor(Cited):
    max_points: StrictInt
    no_data: StrictInt
    clean_points: StrictInt
    bands: tuple[TaxBand, ...]
    offenses_threshold: StrictInt
    offenses_penalty: StrictInt
    blocked_points: StrictInt


class ClientFactor(Cited):
    max_points: StrictInt
    not_client_points: StrictInt
    no_data: StrictInt
    bands: tuple[Band, ...]  # по месяцам обслуживания

    @model_validator(mode="after")
    def _bands_ok(self) -> ClientFactor:
        _check_bands(self.bands)
        return self


class CoverageFactor(BandFactor):
    pass


class GradeCaps(Cited):
    max_grade: str
    min_business_age_months: StrictInt
    overdue_days: StrictInt


class Scorecard(_Strict):
    age: BandFactor
    credit_history: HistoryFactor
    inquiries: InquiriesFactor
    debt_load: DebtLoadFactor
    trend: BandFactor
    volatility: VolatilityFactor
    tax: TaxFactor
    client: ClientFactor
    coverage: CoverageFactor
    caps: GradeCaps

    @model_validator(mode="after")
    def _sum_is_100(self) -> Scorecard:
        total = (
            self.age.max_points
            + self.credit_history.max_points
            + self.inquiries.max_points
            + self.debt_load.max_points
            + self.trend.max_points
            + self.volatility.max_points
            + self.tax.max_points
            + self.client.max_points
            + self.coverage.max_points
        )
        if total != 100:
            raise ValueError(f"сумма максимумов скоркарты должна быть 100, получено {total}")
        return self


class GradeRow(Cited):
    grade: str
    min_points: StrictInt
    max_points: StrictInt
    pd: Dec


class MasterScale(_Strict):
    grades: tuple[GradeRow, ...]

    @model_validator(mode="after")
    def _covers_0_100(self) -> MasterScale:
        rows = self.grades
        if [r.grade for r in rows] != ["A", "B", "C", "D", "E"]:
            raise ValueError("грейды по порядку A, B, C, D, E")
        if rows[0].max_points != 100 or rows[-1].min_points != 0:
            raise ValueError("грейды должны покрывать 0–100")
        for upper, lower in zip(rows, rows[1:], strict=False):
            if upper.min_points != lower.max_points + 1:
                raise ValueError("между грейдами дыра или пересечение")
        if any(r.min_points > r.max_points for r in rows):
            raise ValueError("min_points > max_points")
        pds = [r.pd for r in rows]
        if pds != sorted(pds):
            raise ValueError("PD должна расти от A к E")
        return self


# ---------------------------------------------------------------- pricing, affordability


class Pricing(_Strict):
    key_rate: DecParam
    spread: DecParam
    lgd_unsecured: DecParam
    lgd_secured: DecParam
    capital_charge: DecParam
    rounding_step: DecParam


class Affordability(_Strict):
    dscr_min: DecParam
    stress_dscr_min: DecParam
    debt_to_revenue_max: DecParam
    line_share_of_monthly_revenue: DecParam
    overdraft_share_of_inflows: DecParam
    contract_share_of_unpaid: DecParam
    investment_share_of_collateral: DecParam
    amount_step_rub: IntParam
    p_def12_yellow: DecParam
    p_def12_red: DecParam


class AuthorityRow(Cited):
    up_to_rub: Rub | None  # None — «выше предыдущего порога»
    grade_ab: str
    grade_c: str
    grade_d: str


class GrayZones(Cited):
    points_b_low: StrictInt
    points_b_high: StrictInt
    points_e_low: StrictInt
    points_e_high: StrictInt
    dscr_upto: Dec  # [dscr_min; dscr_upto)
    stress_upto: Dec  # [stress_min; stress_upto)
    debt_from: Dec  # [debt_from; debt_max]


class Routing(_Strict):
    grade_a_auto_multiplier: IntParam
    gray: GrayZones
    authority: tuple[AuthorityRow, ...]

    @model_validator(mode="after")
    def _authority_sorted(self) -> Routing:
        rows = self.authority
        if not rows or rows[-1].up_to_rub is not None:
            raise ValueError("последняя строка матрицы полномочий без up_to_rub")
        limits = [r.up_to_rub for r in rows[:-1] if r.up_to_rub is not None]
        if limits != sorted(limits):
            raise ValueError("пороги матрицы полномочий по возрастанию")
        return self


class TermGrid(Cited):
    value: tuple[StrictInt, ...]


class Weights(Cited):
    amount: Dec
    term: Dec
    overpayment: Dec
    product_change: Dec
    security: Dec


class CounterOffers(_Strict):
    term_grid_months: TermGrid
    amount_step_rub: IntParam
    dscr_min: DecParam
    stress_dscr_min: DecParam
    debt_to_revenue_below: DecParam
    max_cards: IntParam
    weights: Weights


class Timing(_Strict):
    client_reply_days: IntParam
    offer_valid_days: IntParam
    bki_reuse_days: IntParam
    consent_months: IntParam


class Policy(_Strict):
    meta: Meta
    catalog: Catalog
    eligibility: Eligibility
    stop_factors: StopFactors
    restrictions: Restrictions
    features: FeatureParams
    scorecard: Scorecard
    master_scale: MasterScale
    pricing: Pricing
    affordability: Affordability
    routing: Routing
    counter_offers: CounterOffers
    timing: Timing

    def product_config(self, product: str) -> ProductConfig:
        return self.catalog.products[product]

    def grade_of(self, points: int) -> GradeRow:
        for row in self.master_scale.grades:
            if row.min_points <= points <= row.max_points:
                return row
        raise ValueError(f"баллы вне 0–100: {points}")

    def grade_row(self, grade: str) -> GradeRow:
        for row in self.master_scale.grades:
            if row.grade == grade:
                return row
        raise ValueError(f"нет грейда {grade}")


def parse_policy(data: Mapping[str, Any]) -> Policy:
    """Словарь (из YAML) → типы ядра. Файл не читает."""
    try:
        return Policy.model_validate(dict(data))
    except ValidationError as exc:
        raise PolicyError(str(exc)) from exc
