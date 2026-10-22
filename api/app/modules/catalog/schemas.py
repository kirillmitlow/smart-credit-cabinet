"""Модели запросов и ответов каталога, калькулятора и мастера (50-07: camelCase, рубли целые)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel

# Проценты на границе API числом (`ratePercent: 21.5`); внутри всюду Decimal, float только здесь
Percent = Annotated[
    Decimal,
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
]
ProductCode = Annotated[
    str, Field(pattern=r"^(EXPRESS|WORKING_CAPITAL|CONTRACT|CREDIT_LINE|OVERDRAFT|INVESTMENT)$")
]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------- каталог


class AutoDecisionMode(StrEnum):
    ALWAYS = "ALWAYS"
    UP_TO = "UP_TO"
    NEVER = "NEVER"


class ReasonOut(Camel):
    """Причина по-человечески; машинный код нужен фронту для словаря (60-06)."""

    code: str
    text: str
    action: str
    available_from: date | None = None


class ProductOut(Camel):
    code: str
    title: str
    purpose: str
    repayment: str
    amount_min_rub: int
    amount_max_rub: int
    term_min_months: int
    term_max_months: int
    collateral_required_above_rub: int | None
    rate_percent_from: Percent
    auto_decision_mode: AutoDecisionMode
    auto_decision_up_to_rub: int | None
    requires_bank_customer: bool
    requires_contract: bool
    documents: list[str]
    available: bool
    unavailable_reasons: list[ReasonOut]
    hint: str | None
    requires_security: bool


class ProductList(Camel):
    items: list[ProductOut]


# ---------------------------------------------------------------- калькулятор


class PaymentRequest(Camel):
    product_code: ProductCode
    amount_rub: int = Field(gt=0, le=1_000_000_000)
    term_months: int = Field(ge=1, le=120)
    rate_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=6,
        decimal_places=3,
        description="Итоговая ставка из оферты; без неё считаем по базовой ставке продукта",
    )


class PaymentKind(StrEnum):
    ANNUITY = "ANNUITY"
    INTEREST_ONLY = "INTEREST_ONLY"


class PaymentOut(Camel):
    product_code: str
    amount_rub: int
    term_months: int
    payment_kind: PaymentKind
    payment_rub: int
    last_payment_rub: int
    total_payment_rub: int
    overpayment_rub: int
    rate_percent: Percent
    rate_percent_from: Percent
    effective_rate_percent: Percent
    approximate: bool


# ---------------------------------------------------------------- мастер

Purpose = Literal["EQUIPMENT", "GOODS", "ORDER", "GAP", "GROWTH", "OTHER", "UNKNOWN"]
Frequency = Literal["ONCE", "REGULAR", "UNKNOWN"]
Horizon = Literal["DAYS", "WEEKS", "MONTHS_1_3", "MONTHS_3_12", "OVER_YEAR", "UNKNOWN"]
Urgency = Literal["NOW", "WEEK", "NO_RUSH", "UNKNOWN"]
GovContract = Literal["YES", "NO", "UNKNOWN"]
CollateralAnswer = Literal[
    "PURCHASED_ITEM", "REAL_ESTATE", "OTHER_EQUIPMENT", "NONE", "NOT_SURE", "UNKNOWN"
]


class WizardAnswers(Camel):
    """Ответы по кодам слотов (10-07). «Не знаю» — `UNKNOWN` или `null`: подбор идёт без ответа."""

    purpose: Purpose | None = None
    amount_rub: int | None = Field(default=None, gt=0, le=1_000_000_000)
    frequency: Frequency | None = None
    payback_horizon: Horizon | None = None
    gov_contract: GovContract | None = None
    urgency: Urgency | None = None
    term_months: int | None = Field(default=None, ge=1, le=120)
    collateral: CollateralAnswer | None = None


class WizardRequest(Camel):
    answers: WizardAnswers
    application_id: UUID | None = Field(
        default=None,
        description="Черновик заявки; без него мастер создаёт черновик и возвращает его id",
    )


class ComfortableOption(Camel):
    term_months: int
    payment_rub: int
    overpayment_rub: int
    recommended: bool = Field(description="По силам при известном денежном потоке")


class DecisionTime(StrEnum):
    AUTO = "AUTO"  # за минуты автоматически
    MANUAL = "MANUAL"  # 1–2 дня, смотрит специалист


class Recommended(Camel):
    product_code: str
    title: str
    why: str
    payment_rub: int | None
    payment_kind: PaymentKind | None
    rate_percent_from: Percent
    approximate: bool = True
    decision_time: DecisionTime
    documents: list[str]
    needs_collateral: bool
    needs_contract: bool
    requires_security: bool
    comfortable_options: list[ComfortableOption]


class RejectedCandidate(Camel):
    product_code: str
    title: str
    reasons: list[ReasonOut]


class WizardOutcome(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    CATALOG_HINT = "CATALOG_HINT"


class WizardResult(Camel):
    outcome: WizardOutcome
    rule_id: str | None
    start_path: bool
    primary: Recommended | None
    alternative: Recommended | None
    rejected: list[RejectedCandidate]
    hint: str | None
    ask_collateral: bool
    application_id: UUID | None = None
