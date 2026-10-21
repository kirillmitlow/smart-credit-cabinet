"""Формат сценария (раздел 10.2 спецификации моков) — центральный контракт сервиса сценариев.

На эту модель опираются разворачивание (expand), раскладка по мокам и встроенные персоны:
названия полей не меняются без решения. Неизвестные поля отклоняются (422), чтобы опечатка
в параметре не превращалась молча в «значение из пресета».
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.common.schemas import CamelModel


class Strict(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Preset(StrEnum):
    IP_HEALTHY = "IP_HEALTHY"
    LLC_HEALTHY = "LLC_HEALTHY"
    LLC_HIGH_DEBT_LOAD = "LLC_HIGH_DEBT_LOAD"
    STARTUP = "STARTUP"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    PROBLEM_DEBTOR = "PROBLEM_DEBTOR"


Outcome = Literal[
    "APPROVED", "COUNTER_OFFER", "NEEDS_INFO", "MANUAL_REVIEW", "REJECTED", "NOT_ELIGIBLE"
]
ProductCode = Literal[
    "EXPRESS", "WORKING_CAPITAL", "CONTRACT", "CREDIT_LINE", "OVERDRAFT", "INVESTMENT"
]
CompanyForm = Literal["IP", "LLC", "JSC", "SELF_EMPLOYED"]
LoanKind = Literal[
    "LOAN", "CREDIT_LINE", "OVERDRAFT", "CREDIT_CARD", "LEASING", "MICROLOAN", "CONSUMER_LOAN"
]
RelDate = (
    str  # «-3M», «+4M» или абсолютная дата ISO; разбирает app.common.reldate при разворачивании
)


class Collateral(Strict):
    description: str = Field(min_length=1, max_length=300)
    value_rub: int | None = Field(default=None, ge=0, description="Оценка залога клиентом (30-17)")


class GuarantorRef(Strict):
    ref: str = Field(min_length=1, max_length=64)


class ApplicationSpec(Strict):
    """Что просит персона; в моки не уходит (сценарий самопроверки и e2e)."""

    product_code: ProductCode | None = None
    amount_rub: int = Field(gt=0)
    term_months: int | None = Field(default=None, ge=1, le=120)
    collateral: Collateral | None = None
    guarantor: GuarantorRef | None = None


class CompanySpec(Strict):
    form: CompanyForm | None = None
    name: str | None = Field(default=None, max_length=300)
    inn: str | None = Field(default=None, pattern=r"^\d{10}$|^\d{12}$")
    ogrn: str | None = Field(default=None, pattern=r"^\d{13}$|^\d{15}$")
    kpp: str | None = Field(default=None, pattern=r"^\d{4}[\dA-Z]{2}\d{3}$")
    age_months: int | None = Field(default=None, ge=0, le=1200)
    registration_date: date | None = None
    status: str | None = None
    okved: str | None = Field(default=None, pattern=r"^\d{2}(\.\d{1,2}){0,2}$")
    region_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    unreliable_address: bool | None = None
    pending_exclusion: bool | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.age_months is not None and self.registration_date is not None:
            raise ValueError("Укажите либо ageMonths, либо registrationDate")
        if self.ogrn is not None and self.age_months is not None:
            raise ValueError("При заданном ogrn дата регистрации задаётся только registrationDate")
        if self.form in ("IP", "SELF_EMPLOYED") and self.kpp is not None:
            raise ValueError("У ИП и самозанятого не бывает КПП")
        if self.inn is not None and self.form is not None:
            expected = 10 if self.form in ("LLC", "JSC") else 12
            if len(self.inn) != expected:
                raise ValueError(f"У формы {self.form} ИНН из {expected} цифр")
        return self


class Person(Strict):
    ref: str | None = Field(default=None, max_length=64)
    inn: str | None = Field(default=None, pattern=r"^\d{12}$")
    full_name: str | None = Field(default=None, max_length=200)
    birth_date: date | None = None
    share_percent: float | None = Field(default=None, ge=0, le=100)


class PeopleSpec(Strict):
    director: Person | None = None
    founders: list[Person] | None = None


class FinanceSpec(Strict):
    avg_monthly_revenue_rub: int | None = Field(default=None, ge=0)
    revenue_trend: Literal["GROWTH", "STABLE", "DECLINE"] | None = None
    trend_percent: float | None = Field(default=None, ge=-100, le=1000)
    seasonality: Literal["NONE", "AGRO", "RETAIL_Q4"] | None = None
    net_margin_percent: float | None = Field(default=None, ge=-100, le=100)
    min_monthly_surplus_rub: int | None = None
    noise_percent: float | None = Field(
        default=None, ge=0, le=50, description="Шум оборотов, %; по умолчанию 5, 0 — точный ряд"
    )
    has_statements: bool | None = None
    tax_regime: str | None = None
    vat_rate_percent: float | None = Field(default=None, ge=0, le=30)
    headcount: int | None = Field(default=None, ge=0)
    statements_mismatch_percent: float | None = Field(default=None, ge=-100, le=100)


class TaxSpec(Strict):
    tax_debt_rub: int | None = Field(default=None, ge=0)
    mass_address: bool | None = None
    mass_director: bool | None = None
    disqualified_management: bool | None = None
    account_blocked: bool | None = None


class BankruptcySpec(Strict):
    subject: str = Field(pattern=r"^(company|director|owner|founder:[\w-]+)$")
    stage: str
    started_years_ago: float = Field(ge=0)
    completed_years_ago: float | None = Field(default=None, ge=0)


class ContractCustomer(Strict):
    name: str
    inn: str | None = None


class ContractSpec(Strict):
    customer: ContractCustomer
    subject: str
    price_rub: int = Field(gt=0)
    concluded: RelDate | None = None
    execution_in: RelDate | None = None
    payment_in: RelDate | None = None
    status: str | None = None
    paid_rub: int | None = Field(default=None, ge=0)


class ActiveLoan(Strict):
    kind: LoanKind
    amount_rub: int | None = Field(default=None, gt=0)
    term_months: int | None = Field(default=None, ge=1)
    limit_rub: int | None = Field(default=None, gt=0)
    balance_rub: int | None = Field(default=None, ge=0)
    rate_percent: float | None = Field(default=None, ge=0, le=200)
    monthly_payment_rub: int | None = Field(default=None, ge=0)
    opened_at: RelDate | None = None
    secured: bool | None = None
    our_bank: bool | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        revolving = self.kind in ("CREDIT_LINE", "OVERDRAFT", "CREDIT_CARD")
        if revolving and self.limit_rub is None:
            raise ValueError(f"У {self.kind} нужен limitRub")
        if not revolving and self.amount_rub is None and self.monthly_payment_rub is None:
            raise ValueError(f"У {self.kind} нужен amountRub (и termMonths) или monthlyPaymentRub")
        return self


class ClosedLoan(Strict):
    kind: LoanKind
    amount_rub: int = Field(gt=0)
    opened_at: RelDate
    closed_at: RelDate
    repayment: Literal["ANNUITY", "BULLET"] = "ANNUITY"
    secured: bool | None = None


class BkiSubjectSpec(Strict):
    history_years: float | None = Field(default=None, ge=0)
    active_loans: list[ActiveLoan] | None = None
    closed_loans: list[ClosedLoan] | None = None
    monthly_payments_rub: int | None = Field(default=None, ge=0)
    current_overdue_days: int | None = Field(default=None, ge=0)
    current_overdue_rub: int | None = Field(default=None, ge=0)
    past_max_overdue_days: int | None = Field(default=None, ge=0)
    restructurings24m: int | None = Field(default=None, ge=0, alias="restructurings24m")
    inquiries30d: int | None = Field(default=None, ge=0, alias="inquiries30d")
    rejected_applications90d: int | None = Field(
        default=None, ge=0, alias="rejectedApplications90d"
    )
    sold_to_collectors: bool | None = None


class BkiSpec(Strict):
    company: BkiSubjectSpec | None = None
    director: BkiSubjectSpec | None = None
    owner: BkiSubjectSpec | None = None


class BankSpec(Strict):
    is_customer: bool | None = None
    customer_since_months: int | None = Field(default=None, ge=0)
    balance_rub: int | None = Field(default=None, ge=0)


class ComplianceSpec(Strict):
    aml_listed: Literal["COMPANY", "DIRECTOR"] | None = None
    zsk: str | None = None
    internal_stop_list: bool | None = None


class UserSpec(Strict):
    login: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    role: str
    person_ref: str | None = None
    full_name: str | None = None
    inn: str | None = Field(default=None, pattern=r"^\d{12}$")
    power_of_attorney: bool | None = None


class ScenarioSpec(Strict):
    """Тело POST /api/v1/scenarios и формат встроенных сценариев (10.2, 10.5)."""

    model_config = ConfigDict(
        json_schema_extra={
            "anyOf": [
                {"required": ["preset"], "properties": {"preset": {"type": "string"}}},
                {
                    "required": ["company"],
                    "properties": {
                        "company": {
                            "type": "object",
                            "required": ["form"],
                            "properties": {"form": {"type": "string"}},
                        }
                    },
                },
            ]
        }
    )

    code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    title: str = Field(min_length=1, max_length=300)
    preset: Preset | None = None
    builtin_version: int | None = Field(default=None, ge=1)
    expected_outcome: Outcome | None = None
    expected_final_outcome: Outcome | None = None
    expected_reason_codes: list[str] = Field(default_factory=list)
    application: ApplicationSpec | None = None
    company: CompanySpec | None = None
    people: PeopleSpec | None = None
    finance: FinanceSpec | None = None
    tax: TaxSpec | None = None
    bankruptcies: list[BankruptcySpec] = Field(default_factory=list)
    contracts: list[ContractSpec] = Field(default_factory=list)
    bki: BkiSpec | None = None
    active_loans: list[ActiveLoan] = Field(default_factory=list)
    closed_loans: list[ClosedLoan] = Field(default_factory=list)
    bank: BankSpec | None = None
    compliance: ComplianceSpec | None = None
    raw: dict[str, Any] | None = Field(
        default=None, description="Точные данные мока поверх сгенерированных"
    )
    users: list[UserSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        form = self.company.form if self.company else None
        if form is None and self.preset is None:
            raise ValueError("Укажите company.form или preset явно")
        founders = self.people.founders if self.people else None
        if form == "JSC" and founders:
            raise ValueError("У АО учредители-люди не указываются: ЕГРЮЛ не показывает акционеров")
        if form in ("IP", "SELF_EMPLOYED") and founders:
            raise ValueError("У ИП и самозанятого нет учредителей")
        if form in ("IP", "SELF_EMPLOYED") and self.people and self.people.director:
            raise ValueError("У ИП и самозанятого нет директора")
        if form == "SELF_EMPLOYED" and self.bank and self.bank.is_customer:
            raise ValueError(
                "Самозанятый в сценарии не может быть клиентом банка (нет расчётного счёта)"
            )
        logins = [u.login for u in self.users]
        if len(logins) != len(set(logins)):
            raise ValueError("Логины пользователей в сценарии должны быть уникальны")
        return self


class ScenarioOrigin(StrEnum):
    BUILTIN = "BUILTIN"
    CUSTOM = "CUSTOM"


ScenarioStatus = Literal["PENDING", "APPLIED", "PARTIAL", "FAILED"]
AppliedState = Literal["OK", "SKIPPED", "FAILED"]


class AppliedSummary(CamelModel):
    registry: AppliedState | None = None
    tax: AppliedState | None = None
    bki: AppliedState | None = None
    bank_core: AppliedState | None = None


class DirectorSummary(CamelModel):
    full_name: str
    inn: str


class ScenarioListItem(CamelModel):
    code: str
    title: str
    origin: ScenarioOrigin
    inn: str | None
    expected_outcome: Outcome | None
    status: ScenarioStatus
    modified: bool


class ScenarioView(CamelModel):
    """GET /scenarios/{code} и ответ POST: параметры, ожидания, развёрнутые данные, учётки."""

    code: str
    title: str
    origin: ScenarioOrigin
    builtin_version: int | None
    modified: bool
    status: ScenarioStatus
    inn: str | None
    ogrn: str | None = None
    short_name: str | None = None
    director: DirectorSummary | None = None
    expected_outcome: Outcome | None
    expected_final_outcome: Outcome | None
    expected_reason_codes: list[str]
    application: ApplicationSpec | None
    users: list[UserSpec]
    spec: dict[str, Any]
    applied: AppliedSummary | None = None
    expanded: dict[str, Any] | None = None
    last_error: str | None = None
    applied_at: datetime | None = None


class PresetView(CamelModel):
    code: Preset
    title: str
    defaults: dict[str, Any]
