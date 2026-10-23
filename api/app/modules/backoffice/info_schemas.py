"""Запрос сведений, повтор проверки и банковское чтение отправленных ответов (T-363)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.modules.backoffice.schemas import Camel

UwReason = Literal[
    "UW_NEW_INFO",
    "UW_COLLATERAL_ASSESSED",
    "UW_FLAG_CLEARED",
    "UW_POLICY_EXCEPTION",
    "UW_RISK_HIGHER",
    "UW_DOCUMENT_ISSUE",
    "UW_OTHER",
]


class BankInfoItem(Camel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal[
        "DOCUMENT", "EXPLANATION", "COLLATERAL", "CONFIRM_REVENUE", "SIGNATURE", "GUARANTOR"
    ]
    title: str = Field(min_length=1, max_length=200)
    why_text: str = Field(min_length=1, max_length=4000)
    what: str = Field(default="", max_length=4000)
    where: str = Field(default="", max_length=4000)
    assignee_user_id: UUID | None = None
    assignee_person_inn: str | None = Field(default=None, pattern=r"^\d{12}$")


class BankInfoRequest(Camel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1, strict=True)
    reason_code: UwReason
    items: list[BankInfoItem] = Field(min_length=1, max_length=10)


class BankInfoRequested(Camel):
    application_id: UUID
    version: int
    status: Literal["NEEDS_INFO"] = "NEEDS_INFO"
    round: int
    task_ids: list[UUID]


class BankRecheckRequest(Camel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1, strict=True)


class BankRecheckStarted(Camel):
    application_id: UUID
    version: int
    status: Literal["CHECKING"] = "CHECKING"
    run_id: UUID


class BankClientTask(Camel):
    id: UUID
    round: int
    kind: str
    title: str
    why_text: str
    what: str
    where: str
    status: str
    expires_at: datetime | None
    assignee_user_id: UUID | None
    assignee_person_inn: str | None
    answer: str | None = Field(description="Только отправленный ответ; черновик банку недоступен")
    answered_by: UUID | None
    answered_at: datetime | None
    created_at: datetime
