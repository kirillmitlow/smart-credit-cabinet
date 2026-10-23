from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.backoffice.schemas import Camel


class BankOutboxItem(Camel):
    id: int
    application_id: UUID | None
    target_system: str
    event_type: str
    status: Literal["FAILED"] = "FAILED"
    attempts: int
    created_at: datetime
    last_error: str | None
    can_retry: bool
    blocked_reason: Literal["EXPIRED", "APPLICATION_MISSING"] | None


class BankOutboxPage(Camel):
    items: list[BankOutboxItem]
    next_cursor: str | None


class BankOutboxRetried(Camel):
    id: int
    application_id: UUID
    status: Literal["PENDING"] = "PENDING"


class BankOutboxRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
