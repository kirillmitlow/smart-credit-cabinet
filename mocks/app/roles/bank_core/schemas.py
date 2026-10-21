"""Схемы mock-bank-core: ответы бизнес-API (разделы 7.1–7.6) и тело админ-API (8.3).

Тело `PUT /admin/subjects/{inn}` повторяет термины ответов без `meta`: клиент, счета, обороты,
кредиты, комплаенс. Ссудные счета в тело не входят: мок создаёт их сам для каждого кредита.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.common.schemas import CamelModel, Meta

CustomerType = Literal["LEGAL_ENTITY", "INDIVIDUAL_ENTREPRENEUR"]
AccountStatus = Literal["OPEN", "BLOCKED", "CLOSED"]
LoanKind = Literal["LOAN", "CREDIT_LINE", "OVERDRAFT"]
RepaymentType = Literal["ANNUITY", "BULLET", "REVOLVING"]
LoanStatus = Literal["ACTIVE", "CLOSED"]
AccountNumber = Annotated[str, StringConstraints(pattern=r"^\d{20}$")]
Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
ListName = Literal["ROSFINMONITORING_TERRORISM_EXTREMISM", "MVK_FREEZE"]
RiskLevel = Literal["GREEN", "YELLOW", "RED"]
ScreeningRole = Literal["COMPANY", "DIRECTOR", "FOUNDER", "IE"]


# ---- 7.1, 7.5: счета и кредиты ----


class AccountOut(CamelModel):
    number: str
    type: Literal["SETTLEMENT", "LOAN"]
    currency: Literal["RUB"] = "RUB"
    status: AccountStatus
    opened_at: date
    balance_rub: int


class CustomerOut(CamelModel):
    meta: Meta
    customer_id: str
    inn: str
    type: CustomerType
    name: str
    customer_since: date
    accounts: list[AccountOut]


class PostingOut(CamelModel):
    debit: str
    credit: str
    amount_rub: int
    purpose: str
    value_date: date


class AccountDetailOut(AccountOut):
    """`GET /accounts/{number}`: поля счёта как в 7.1 и последние проводки симулятора."""

    meta: Meta
    recent_postings: list[PostingOut]


class LoanOut(CamelModel):
    loan_id: str
    application_ref: str
    contract_number: str
    contract_uid: str
    product_code: str
    kind: LoanKind
    amount_rub: int
    limit_rub: int | None
    outstanding_rub: int
    term_months: int
    rate_percent: float
    repayment_type: RepaymentType
    loan_account: str
    settlement_account: str
    status: LoanStatus
    disbursed_at: date


class LoanDetailOut(LoanOut):
    meta: Meta


class LoansOut(CamelModel):
    meta: Meta
    inn: str
    loans: list[LoanOut]


# ---- 7.2: обороты ----


class TurnoverMonthOut(CamelModel):
    month: str
    incoming_rub: int
    incoming_net_rub: int
    outgoing_rub: int
    counterparties_in: int
    counterparties_out: int


class TurnoverOut(CamelModel):
    meta: Meta
    inn: str
    account_numbers: list[str]
    months: list[TurnoverMonthOut]


# ---- 7.3: открытие счёта ----


class OpenAccountCustomer(CamelModel):
    type: CustomerType
    name: str = Field(min_length=1, max_length=300)


class OpenAccountIn(CamelModel):
    type: Literal["SETTLEMENT"] = "SETTLEMENT"
    currency: Literal["RUB"] = "RUB"
    customer: OpenAccountCustomer | None = Field(
        default=None, description="Обязателен, если клиента ещё нет: он создаётся вместе со счётом"
    )


class OpenAccountOut(AccountOut):
    meta: Meta
    customer_id: str


# ---- 7.4: выдача ----


class ContractIn(CamelModel):
    number: str = Field(min_length=1, max_length=64)
    uid: str = Field(min_length=1, max_length=64)
    signed_at: datetime


class ProductIn(CamelModel):
    code: str = Field(min_length=1, max_length=64)
    name: str | None = None


class DisbursementIn(CamelModel):
    application_ref: str = Field(min_length=1, max_length=64)
    customer_inn: str
    contract: ContractIn
    product: ProductIn
    kind: LoanKind
    amount_rub: int = Field(ge=0, le=10**12)
    limit_rub: int | None = Field(default=None, gt=0, le=10**12)
    term_months: int = Field(gt=0, le=600)
    rate_percent: float = Field(ge=0, le=100)
    repayment_type: RepaymentType
    settlement_account: AccountNumber

    @model_validator(mode="after")
    def _kind_rules(self) -> DisbursementIn:
        if self.kind == "LOAN":
            if self.amount_rub <= 0:
                raise ValueError("amountRub: сумма кредита должна быть больше нуля")
            if self.limit_rub is not None:
                raise ValueError("limitRub: у разовой выдачи (LOAN) лимита нет")
            if self.repayment_type == "REVOLVING":
                raise ValueError("repaymentType: для LOAN допустимо ANNUITY или BULLET")
        else:
            if self.limit_rub is None:
                raise ValueError("limitRub: для линии и овердрафта лимит обязателен")
            if self.amount_rub > self.limit_rub:
                raise ValueError("amountRub: транш больше лимита")
            if self.repayment_type != "REVOLVING":
                raise ValueError("repaymentType: для линии и овердрафта допустимо REVOLVING")
        return self


class DisbursementPosting(CamelModel):
    debit: str
    credit: str
    amount_rub: int
    purpose: str


class DisbursementOut(CamelModel):
    meta: Meta
    disbursement_id: str
    status: Literal["COMPLETED"] = "COMPLETED"
    loan_id: str
    loan_account: str
    settlement_account: str
    amount_rub: int
    value_date: date
    postings: list[DisbursementPosting]
    settlement_balance_rub: int


# ---- 7.6: комплаенс ----


class ScreeningSubject(CamelModel):
    inn: str
    role: ScreeningRole


class ScreeningIn(CamelModel):
    subjects: list[ScreeningSubject] = Field(min_length=1, max_length=50)


class AmlListOut(CamelModel):
    listed: bool
    list_name: str | None


class ZskOut(CamelModel):
    risk_level: RiskLevel
    assessed_at: date


class StopListOut(CamelModel):
    listed: bool
    reason: str | None


class ScreeningResult(CamelModel):
    inn: str
    role: ScreeningRole
    aml_list: AmlListOut
    zsk: ZskOut | None
    internal_stop_list: StopListOut


class ScreeningOut(CamelModel):
    meta: Meta
    screening_id: str
    overall: Literal["CLEAR", "HIT"]
    results: list[ScreeningResult]


# ---- 8.3: тело админ-API ----


class CustomerBody(CamelModel):
    type: CustomerType
    name: str = Field(min_length=1, max_length=300)
    customer_since: date


class AccountBody(CamelModel):
    number: AccountNumber | None = Field(
        default=None, description="Можно не указывать: мок сгенерирует номер с верным ключом"
    )
    type: Literal["SETTLEMENT"] = "SETTLEMENT"
    status: AccountStatus = "OPEN"
    opened_at: date
    balance_rub: int = Field(default=0, ge=0)


class TurnoverBody(CamelModel):
    month: Month
    incoming_rub: int = Field(ge=0)
    incoming_net_rub: int = Field(ge=0)
    outgoing_rub: int = Field(ge=0)
    counterparties_in: int = Field(ge=0)
    counterparties_out: int = Field(ge=0)


class LoanBody(CamelModel):
    application_ref: str = Field(min_length=1, max_length=64)
    contract_number: str = Field(min_length=1, max_length=64)
    contract_uid: str = Field(min_length=1, max_length=64)
    product_code: str = Field(min_length=1, max_length=64)
    kind: LoanKind = "LOAN"
    amount_rub: int = Field(ge=0, le=10**12)
    limit_rub: int | None = Field(default=None, gt=0, le=10**12)
    term_months: int = Field(gt=0, le=600)
    rate_percent: float = Field(ge=0, le=100)
    repayment_type: RepaymentType = "ANNUITY"
    status: LoanStatus = "ACTIVE"
    disbursed_at: date
    settlement_account: AccountNumber | None = Field(
        default=None, description="По умолчанию — первый расчётный счёт клиента из тела"
    )


class AmlBody(CamelModel):
    list_name: ListName
    reason: str | None = None


class ZskBody(CamelModel):
    risk_level: RiskLevel
    assessed_at: date


class StopListBody(CamelModel):
    reason: str | None = None


class ComplianceBody(CamelModel):
    aml: AmlBody | None = None
    zsk: ZskBody | None = None
    internal_stop_list: StopListBody | None = None


class BankCoreBody(CamelModel):
    customer: CustomerBody | None = None
    accounts: list[AccountBody] = []
    turnover: list[TurnoverBody] = []
    loans: list[LoanBody] = []
    compliance: ComplianceBody | None = None
