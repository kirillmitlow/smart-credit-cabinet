"""Клиентские модели предложения и договора (50-07): без баллов, DSCR и внутренних кодов."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel

# Проценты на границе API числом (`ratePercent: 21.5`); внутри всюду Decimal, float только здесь
Percent = Annotated[
    Decimal,
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ScheduleRowOut(Camel):
    number: int
    payment_rub: int
    principal_rub: int
    interest_rub: int
    balance_rub: int


class VariantOut(Camel):
    id: UUID
    kind: str
    label: str
    product_code: str
    product_title: str
    amount_rub: int
    term_months: int
    rate_percent: Percent
    payment_rub: int
    last_payment_rub: int
    overpayment_rub: int
    collateral_required: bool
    recommended: bool
    what_changed: dict[str, Any]
    note: str
    schedule_preview: list[ScheduleRowOut] = Field(
        description="Первые три платежа и последний; полный график — в договоре"
    )


class OfferOut(Camel):
    id: UUID
    application_id: UUID
    kind: str
    status: str
    variants_status: str = Field(
        description="`PENDING`: встречные варианты ещё готовятся (оптимизатор T-297), выбирать нечего"
    )
    expires_at: datetime
    accepted_variant_id: UUID | None
    contract_id: UUID | None
    variants: list[VariantOut]


class AcceptIn(Camel):
    variant_id: UUID | None = Field(
        default=None, description="Обязателен, если в предложении больше одного варианта"
    )


class SignerOut(Camel):
    role: str
    name: str
    signed: bool
    signed_at: datetime | None


class ProgressOut(Camel):
    signed: int
    required: int


class ContractOut(Camel):
    id: UUID
    application_id: UUID
    application_status: str
    contract_uid: str
    number: str
    status: str
    content_hash: str
    template_version: str
    created_at: datetime
    signed_at: datetime | None
    product_code: str
    amount_rub: int
    term_months: int
    rate_percent: Percent
    payment_rub: int
    signers: list[SignerOut]
    progress: ProgressOut
    can_sign: bool = Field(description="Текущий пользователь может подписать прямо сейчас")
    can_pass_to_director: bool = Field(description="Показать «Передать руководителю на подпись»")


class AcceptedOut(Camel):
    application_status: str
    offer: OfferOut
    contract: ContractOut


class DeclinedOut(Camel):
    application_status: str
    offer: OfferOut


class SignStartIn(Camel):
    agree: bool = Field(
        description="Галочка «Ознакомлен, согласен»; открывать документ не обязательно"
    )
    accept_pep_rules: bool = Field(
        default=False, description="«Принимаю правила простой подписи»; нужна один раз на человека"
    )


class SignChallengeOut(Camel):
    request_id: str
    expires_in_seconds: int
    demo_code: str | None = Field(default=None, description="Только в демо-режиме: код вместо SMS")


class SignConfirmIn(Camel):
    request_id: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^\d{6}$")


class ContractSignedOut(Camel):
    contract: ContractOut
    just_signed: bool = Field(description="`false` — повторное нажатие: вторая подпись не создана")


class PassedOut(Camel):
    contract_id: UUID
    requested_at: datetime
    repeated: bool
