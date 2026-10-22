"""Порт `bank_core` на запись: открыть расчётный счёт и выдать кредит (моки 7.3, 7.4, T-236).

Оба запроса идут с обязательным `Idempotency-Key`, который строит вызывающий из заявки (ASCII,
заголовок HTTP не терпит кириллицы), а не из попытки: повтор после обрыва или `LOST_RESPONSE` даёт
сохранённый ответ, и деньги не выдаются дважды. Повторы делает outbox, внутри вызова адаптер
только ждёт `409 IDEMPOTENCY_IN_PROGRESS`.

Коды отказа АБС приходят как `SourceUnavailable.error_code`; разбор по таблице 20-05 — в
`classify_failure`, чтобы вызывающий не сравнивал строки сам.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.modules.integrations._dto import Dto
from app.modules.integrations.bank_core import BankAccount
from app.modules.integrations.client import IntegrationClient
from app.modules.integrations.policy import BANK_CORE_WRITE
from app.modules.integrations.results import Reason, Result, SourceUnavailable

type LoanKindCode = Literal["LOAN", "CREDIT_LINE", "OVERDRAFT"]
type RepaymentCode = Literal["ANNUITY", "BULLET", "REVOLVING"]
type CustomerKind = Literal["LEGAL_ENTITY", "INDIVIDUAL_ENTREPRENEUR"]

# --- входные и внутренние модели ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DisbursementRequest:
    """Всё, что уходит в `POST /disbursements`. Одна заявка = одно и то же тело при любом повторе."""

    application_ref: str
    customer_inn: str
    contract_number: str
    contract_uid: str
    contract_signed_at: datetime
    product_code: str
    kind: LoanKindCode
    amount_rub: int
    limit_rub: int | None
    term_months: int
    rate_percent: float
    repayment_type: RepaymentCode
    settlement_account: str
    product_name: str | None = None


@dataclass(frozen=True, slots=True)
class OpenedAccount:
    account: BankAccount
    customer_id: str


@dataclass(frozen=True, slots=True)
class Disbursed:
    disbursement_id: str
    loan_id: str
    loan_account: str
    settlement_account: str
    amount_rub: int
    value_date: date
    settlement_balance_rub: int


class Failure(StrEnum):
    """Что делать после отказа АБС (таблица в 20-05)."""

    RETRY = "RETRY"  # сбой источника: повторит outbox с тем же ключом
    DEFER = "DEFER"  # предохранитель открыт: подождать без траты попытки
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"  # сначала открыть счёт
    ACCOUNT_PROBLEM = "ACCOUNT_PROBLEM"  # ACCOUNT_NOT_OWNED / ACCOUNT_BLOCKED: андеррайтеру
    ALREADY_DISBURSED = "ALREADY_DISBURSED"  # выдача уже была под другим ключом: сверить
    ACCOUNT_EXISTS = "ACCOUNT_EXISTS"  # счёт уже открыт: считаем успехом и читаем клиента
    DEFECT = "DEFECT"  # 422 и прочие 4xx: ошибка нашего запроса, остановка


ACCOUNT_ALREADY_EXISTS = "ACCOUNT_ALREADY_EXISTS"
CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
ACCOUNT_NOT_OWNED = "ACCOUNT_NOT_OWNED"
ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"
ALREADY_DISBURSED = "ALREADY_DISBURSED"


def classify_failure(failure: SourceUnavailable) -> Failure:
    code = failure.error_code
    if code == ACCOUNT_ALREADY_EXISTS:
        return Failure.ACCOUNT_EXISTS
    if code == CUSTOMER_NOT_FOUND:
        return Failure.CUSTOMER_NOT_FOUND
    if code in (ACCOUNT_NOT_OWNED, ACCOUNT_BLOCKED):
        return Failure.ACCOUNT_PROBLEM
    if code == ALREADY_DISBURSED:
        return Failure.ALREADY_DISBURSED
    if failure.reason is Reason.CIRCUIT_OPEN:
        return Failure.DEFER
    if failure.retryable_later:
        return Failure.RETRY
    return Failure.DEFECT


# --- DTO под JSON мока ----------------------------------------------------------------------------


class _AccountDto(Dto):
    number: str
    type: str
    currency: str
    status: str
    opened_at: date
    balance_rub: int


class _OpenedAccountDto(_AccountDto):
    customer_id: str


class _DisbursedDto(Dto):
    disbursement_id: str
    status: str
    loan_id: str
    loan_account: str
    settlement_account: str
    amount_rub: int
    value_date: date
    settlement_balance_rub: int = Field(default=0)


def map_opened_account(payload: object) -> OpenedAccount:
    dto = _OpenedAccountDto.model_validate(payload)
    account = BankAccount(
        dto.number, dto.type, dto.currency, dto.status, dto.opened_at, dto.balance_rub
    )
    return OpenedAccount(account, dto.customer_id)


def map_disbursed(payload: object) -> Disbursed:
    dto = _DisbursedDto.model_validate(payload)
    if dto.status != "COMPLETED":
        raise ValueError(f"Выдача в статусе {dto.status}")
    return Disbursed(
        dto.disbursement_id,
        dto.loan_id,
        dto.loan_account,
        dto.settlement_account,
        dto.amount_rub,
        dto.value_date,
        dto.settlement_balance_rub,
    )


def disbursement_body(request: DisbursementRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "applicationRef": request.application_ref,
        "customerInn": request.customer_inn,
        "contract": {
            "number": request.contract_number,
            "uid": request.contract_uid,
            "signedAt": request.contract_signed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "product": {"code": request.product_code},
        "kind": request.kind,
        "amountRub": request.amount_rub,
        "limitRub": request.limit_rub,
        "termMonths": request.term_months,
        "ratePercent": request.rate_percent,
        "repaymentType": request.repayment_type,
        "settlementAccount": request.settlement_account,
    }
    if request.product_name:
        body["product"]["name"] = request.product_name
    return body


# --- порт ----------------------------------------------------------------------------------------


class BankCoreWriteAdapter:
    def __init__(self, client: IntegrationClient) -> None:
        self._client = client

    def open_account(
        self,
        inn: str,
        customer_type: CustomerKind,
        customer_name: str,
        *,
        idempotency_key: str,
        application_id: UUID | None = None,
    ) -> Result[OpenedAccount]:
        """Расчётный счёт клиенту (не-клиента АБС создаёт вместе со счётом).

        `409 ACCOUNT_ALREADY_EXISTS` приходит как `SourceUnavailable(error_code=...)`:
        `classify_failure` даёт `ACCOUNT_EXISTS`, вызывающий читает клиента и берёт счёт.
        """
        return self._client.call(
            policy=BANK_CORE_WRITE,
            method="POST",
            path=f"/api/v1/customers/{inn}/accounts",
            json_body={
                "type": "SETTLEMENT",
                "currency": "RUB",
                "customer": {"type": customer_type, "name": customer_name},
            },
            idempotency_key=idempotency_key,
            parse=map_opened_account,
            subject_inn=inn,
            application_id=application_id,
            resource="bank_core:open_account",
        )

    def disburse(
        self,
        request: DisbursementRequest,
        *,
        idempotency_key: str,
        application_id: UUID | None = None,
    ) -> Result[Disbursed]:
        """Выдача. Повтор с тем же ключом и телом возвращает тот же ответ (`replayed`), деньги не дублируются."""
        return self._client.call(
            policy=BANK_CORE_WRITE,
            method="POST",
            path="/api/v1/disbursements",
            json_body=disbursement_body(request),
            idempotency_key=idempotency_key,
            parse=map_disbursed,
            subject_inn=request.customer_inn,
            application_id=application_id,
            resource="bank_core:disbursement",
        )
