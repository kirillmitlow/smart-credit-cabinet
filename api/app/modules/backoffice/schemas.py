"""Отдельные банковские представления, без расширения клиентских ответов (50-07)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

ProductCode = Annotated[
    str, Field(pattern=r"^(EXPRESS|WORKING_CAPITAL|CONTRACT|CREDIT_LINE|OVERDRAFT|INVESTMENT)$")
]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BankReason(Camel):
    code: str
    title: str
    detail: str


class BankRecommendation(Camel):
    outcome: str
    hint: str


class BankCompany(Camel):
    id: UUID
    name: str
    inn: str
    is_bank_customer: bool | None


class BankQueueItem(Camel):
    id: UUID
    number: str
    status: str
    version: int
    company: BankCompany
    product_code: str | None
    amount_rub: int | None
    term_months: int | None
    waiting_since: datetime
    waiting_seconds: int = Field(ge=0)
    overdue: bool = Field(description="Ожидание больше 24 часов по будним дням; выходные исключены")
    manual_reasons: list[BankReason]
    recommendation: BankRecommendation | None
    required_level: str | None
    badges: list[Literal["CLIENT_ANSWERED", "SOURCE_UNAVAILABLE", "PIPELINE_ERROR"]]
    document_received: bool | None = Field(
        description="null: сервис документов ещё не подключён; наличие файла не предполагается"
    )


class BankQueuePage(Camel):
    items: list[BankQueueItem]
    next_cursor: str | None
