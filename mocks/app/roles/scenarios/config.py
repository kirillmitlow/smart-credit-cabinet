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
