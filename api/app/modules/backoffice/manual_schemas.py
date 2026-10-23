"""Предпросмотр без записи: только вычисленные ядром числа и ограничения."""

from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.modules.backoffice.card_schemas import Number
from app.modules.backoffice.decision_schemas import BankDecisionTerms
from app.modules.backoffice.schemas import Camel


class BankOfferEvaluationRequest(Camel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1, strict=True)
    engine_decision_id: UUID
    outcome: Literal["APPROVED", "COUNTER_OFFER"] = "COUNTER_OFFER"
    terms: BankDecisionTerms
    reason_code: str | None = Field(default=None, max_length=100)
    comment: str | None = Field(default=None, max_length=4000)


class BankOfferViolation(Camel):
    code: str
    kind: str
    params: dict[str, Any]


class BankOfferEvaluation(Camel):
    application_id: UUID
    version: int
    engine_decision_id: UUID
    allowed: bool
    evaluation_ref: str | None = Field(
        description="Только допустимый расчёт; привязан к версии и сотруднику"
    )
    required_level: str
    min_comment_chars: int
    deviation: bool
    exception_used: bool
    rate_percent: Number | None
    corridor_min_percent: Number | None
    corridor_max_percent: Number | None
    payment_rub: int | None
    last_payment_rub: int | None
    overpayment_rub: int | None
    dscr: Number | None
    stress_dscr: Number | None
    violations: list[BankOfferViolation]
