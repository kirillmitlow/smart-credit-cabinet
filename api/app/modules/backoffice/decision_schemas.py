"""Команды банка: уровень сотрудника берётся из сессии, расчёт — только из ядра."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.modules.backoffice.schemas import Camel, ProductCode


class BankDecisionTerms(Camel):
    model_config = ConfigDict(extra="forbid")

    product_code: ProductCode
    amount_rub: int = Field(gt=0, strict=True)
    term_months: int = Field(gt=0, strict=True)
    rate_percent: Decimal | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)


class BankDecisionRequest(Camel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1, strict=True)
    engine_decision_id: UUID | None = None
    outcome: Literal["APPROVED", "COUNTER_OFFER", "REJECTED"]
    terms: BankDecisionTerms | None = None
    reason_code: str | None = Field(default=None, max_length=100)
    comment: str | None = Field(default=None, max_length=4000)


class BankDecisionSaved(Camel):
    application_id: UUID
    decision_id: UUID
    engine_decision_id: UUID
    status: Literal["APPROVED", "COUNTER_OFFER", "REJECTED"]
    version: int
    outcome: Literal["APPROVED", "COUNTER_OFFER", "REJECTED"]
    deviation: bool
    exception_used: bool
    offer_id: UUID | None
