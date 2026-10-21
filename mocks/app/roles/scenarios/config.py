"""Настройки синтетических финансов: параметры из 10.3, отдельно от кредитной политики."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SmeBand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    category: str
    revenue_rub: int = Field(ge=0)
    headcount: int = Field(ge=0)


class ScenarioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    bank_bik: str = Field(default="040000999", pattern=r"^\d{9}$")

    # ФНС, 425-ФЗ: с января 2026 — 22%. Синтетическое упрощение до 2026 — 20% (10.3).
    vat_rate_schedule: dict[date, Decimal] = Field(
        default_factory=lambda: {date(1990, 1, 1): Decimal(20), date(2026, 1, 1): Decimal(22)}
    )
    # Общие пороги прототипа: 209-ФЗ / ПП265; отраслевые исключения в MVP не моделируются.
    sme_thresholds: list[SmeBand] = Field(
        default_factory=lambda: [
            SmeBand(category="MICRO", revenue_rub=120_000_000, headcount=15),
            SmeBand(category="SMALL", revenue_rub=800_000_000, headcount=100),
            SmeBand(category="MEDIUM", revenue_rub=2_000_000_000, headcount=250),
        ]
    )

    # Числа 2026 года из ФНС; УСН после 2026 требует явного обновления настройки.
    default_trend_percent: Decimal = Field(default=Decimal(10), ge=0, lt=100)
    ausn_revenue_limit_rub: int = Field(default=60_000_000, ge=0)
    ausn_headcount_limit: int = Field(default=5, ge=0)
    usn_revenue_limit_rub: int = Field(default=490_500_000, ge=0)
    usn_headcount_limit: int = Field(default=130, ge=0)
    psn_revenue_limit_schedule: dict[int, int] = Field(
        default_factory=lambda: {
            1900: 60_000_000,
            2026: 20_000_000,
            2027: 15_000_000,
            2028: 10_000_000,
        }
    )
    psn_headcount_limit: int = Field(default=15, ge=0)

    @field_validator("psn_revenue_limit_schedule")
    @classmethod
    def _psn_limits(cls, value: dict[int, int]) -> dict[int, int]:
        if not value or any(
            year < 1 or year > 9999 or amount < 0 for year, amount in value.items()
        ):
            raise ValueError(
                "PSN_REVENUE_LIMIT_SCHEDULE: нужна непустая шкала годов и неотрицательных лимитов"
            )
        return value

    @field_validator("vat_rate_schedule")
    @classmethod
    def _rates(cls, value: dict[date, Decimal]) -> dict[date, Decimal]:
        if not value or any(not r.is_finite() or r < 0 or r > 100 for r in value.values()):
            raise ValueError("VAT_RATE_SCHEDULE: нужна непустая шкала ставок от 0 до 100")
        if any(day.day != 1 for day in value):
            raise ValueError("VAT_RATE_SCHEDULE: ставка меняется с первого числа месяца")
        return value

    @model_validator(mode="after")
    def _bands(self) -> Self:
        if [x.category for x in self.sme_thresholds] != ["MICRO", "SMALL", "MEDIUM"]:
            raise ValueError("SME_THRESHOLDS: категории MICRO, SMALL, MEDIUM в этом порядке")
        for previous, current in zip(self.sme_thresholds, self.sme_thresholds[1:], strict=False):
            if previous.revenue_rub > current.revenue_rub or previous.headcount > current.headcount:
                raise ValueError("SME_THRESHOLDS: пороги должны возрастать")
        return self
