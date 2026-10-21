"""Схемы mock-tax (разделы 5.1–5.6, 8.3).

Тело админ-API (`TaxBody`) использует те же карточки, что и ответы бизнес-API, только без `meta`.
Карточки закрыты для лишних полей (`extra="forbid"`): опечатка в имени поля даёт `422`.
"""

from __future__ import annotations

import datetime as dt
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.common.inn import inn_is_valid
from app.common.schemas import CamelModel, Meta


def _check_inn(value: str) -> str:
    if not inn_is_valid(value):
        raise ValueError("ИНН должен состоять из 10 или 12 цифр с верной контрольной суммой")
    return value


def _check_company_inn(value: str) -> str:
    _check_inn(value)
    if len(value) != 10:
        raise ValueError("ИНН организации — 10 цифр")
    return value


CompanyInn = Annotated[str, AfterValidator(_check_company_inn)]
Rub = Annotated[int, Field(ge=0)]
Year = Annotated[int, Field(ge=1990, le=2100)]
Bik = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]
TaxAuthorityCode = Annotated[str, StringConstraints(pattern=r"^\d{4}$")]

TaxRegimeCode = Literal[
    "OSNO", "USN_INCOME", "USN_INCOME_MINUS_EXPENSES", "PSN", "ESHN", "AUSN", "NPD"
]
FormType = Literal["FULL", "SIMPLIFIED"]
SmeCategory = Literal["MICRO", "SMALL", "MEDIUM"]
BlockReason = Literal["NON_SUBMISSION_OF_DECLARATION", "TAX_DEBT_COLLECTION", "OTHER"]
ContractStatus = Literal["IN_PROGRESS", "EXECUTED", "TERMINATED"]

# Десять строк отчётности из 5.2
LINE_CODES = ("1100", "1200", "1300", "1400", "1500", "1600", "2110", "2200", "2330", "2400")


class Strict(CamelModel):
    model_config = ConfigDict(extra="forbid")


# --- 5.1 налоговый профиль ---------------------------------------------------------------------


class TaxRegime(Strict):
    code: TaxRegimeCode
    year: Year


class AvgHeadcount(Strict):
    value: Annotated[int, Field(ge=0)]
    year: Year


class TaxesPaidItem(Strict):
    year: Year
    total_rub: Rub


class Debts(Strict):
    as_of: date
    tax_debt_rub: Rub
    penalties_rub: Rub
    fines_rub: Rub


class IncomeExpenses(Strict):
    year: Year
    income_rub: Rub
    expenses_rub: Rub


class TaxOffenses(Strict):
    year: Year
    count: Annotated[int, Field(ge=0)]
    fines_rub: Rub


class RiskFlags(Strict):
    mass_address: bool = False
    mass_director: bool = False
    mass_founder: bool = False
    disqualified_management: bool = False
    no_reports_over_year: bool = False


class TaxProfileCard(Strict):
    """Формат ответа `GET /tax-profile/{inn}` без `meta`."""

    inn: Annotated[str, AfterValidator(_check_inn)]
    tax_regimes: list[TaxRegime] = []
    avg_headcount: AvgHeadcount | None = None
    taxes_paid: list[TaxesPaidItem] = []
    debts: Debts
    income_expenses: IncomeExpenses | None = None
    tax_offenses: TaxOffenses | None = None
    risk_flags: RiskFlags = RiskFlags()

    @model_validator(mode="after")
    def _unique_years(self) -> TaxProfileCard:
        if len({t.year for t in self.taxes_paid}) != len(self.taxes_paid):
            raise ValueError("taxesPaid: год указан дважды")
        return self


class TaxProfileResponse(TaxProfileCard):
    meta: Meta


# --- 5.2 отчётность ----------------------------------------------------------------------------


class StatementLines(Strict):
    """Все десять строк, рубли. Баланс одной записи должен сходиться."""

    line_1100: int = Field(alias="1100")
    line_1200: int = Field(alias="1200")
    line_1300: int = Field(alias="1300")
    line_1400: int = Field(alias="1400")
    line_1500: int = Field(alias="1500")
    line_1600: int = Field(alias="1600")
    line_2110: int = Field(alias="2110")
    line_2200: int = Field(alias="2200")
    line_2330: int = Field(alias="2330")
    line_2400: int = Field(alias="2400")

    @model_validator(mode="after")
    def _balance(self) -> StatementLines:
        if self.line_1600 != self.line_1100 + self.line_1200:
            raise ValueError("Баланс не сходится: 1600 должно равняться 1100 + 1200")
        if self.line_1600 != self.line_1300 + self.line_1400 + self.line_1500:
            raise ValueError("Баланс не сходится: 1600 должно равняться 1300 + 1400 + 1500")
        return self


class FinancialRecord(Strict):
    year: Year
    form_type: FormType
    submitted_at: date
    lines: StatementLines


class LinePair(CamelModel):
    current: int
    previous: int | None


class FinancialSummary(CamelModel):
    revenue_rub: int
    sales_profit_rub: int
    interest_payable_rub: int
    net_profit_rub: int
    total_assets_rub: int
    equity_rub: int
    long_term_liabilities_rub: int
    short_term_liabilities_rub: int


class FinancialsCard(CamelModel):
    inn: str
    year: int
    available_years: list[int]
    form_type: FormType
    submitted_at: date
    lines: dict[str, LinePair]
    summary: FinancialSummary


class FinancialsResponse(FinancialsCard):
    meta: Meta


# --- 5.3 МСП, 5.4 НПД ----------------------------------------------------------------------------


class SmeRecord(Strict):
    category: SmeCategory
    included_at: date
    is_newly_created: bool
    is_social_enterprise: bool


class SmeStatusResponse(CamelModel):
    meta: Meta
    inn: str
    in_registry: bool
    category: SmeCategory | None
    included_at: date | None
    is_newly_created: bool | None
    is_social_enterprise: bool | None


class NpdRecord(Strict):
    registered_at: date
    deregistered_at: date | None = None

    @model_validator(mode="after")
    def _order(self) -> NpdRecord:
        if self.deregistered_at is not None and self.deregistered_at < self.registered_at:
            raise ValueError("Снятие с учёта НПД раньше постановки")
        return self


class NpdRequest(CamelModel):
    inn: str
    request_date: date


class NpdResponse(CamelModel):
    """Как у настоящего API ФНС: без `meta`."""

    status: bool
    message: str


# --- 5.5 блокировки ------------------------------------------------------------------------------


class AccountBlockRecord(Strict):
    number: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    date: dt.date
    tax_authority_code: TaxAuthorityCode
    bik: Bik
    reason: BlockReason
    lifted_at: dt.date | None = None

    @model_validator(mode="after")
    def _order(self) -> AccountBlockRecord:
        if self.lifted_at is not None and self.lifted_at < self.date:
            raise ValueError("Решение снято раньше, чем вынесено")
        return self


class BlockDecision(CamelModel):
    number: str
    date: dt.date
    tax_authority_code: str
    bik: str
    reason: BlockReason


class AccountBlocksResponse(CamelModel):
    meta: Meta
    inn: str
    checked_at: dt.datetime
    decisions: list[BlockDecision]


# --- 5.6 госзакупки ------------------------------------------------------------------------------


class Customer(Strict):
    name: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    inn: CompanyInn


class Contract(Strict):
    """Контракт ЕИС; `supplierInn` берётся из пути админ-запроса."""

    registry_number: Annotated[str, StringConstraints(pattern=r"^\d{19}$")]
    customer: Customer
    subject: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    price_rub: Annotated[int, Field(gt=0)]
    concluded_at: date
    execution_deadline: date
    payment_deadline: date
    status: ContractStatus
    paid_rub: Rub

    @model_validator(mode="after")
    def _consistent(self) -> Contract:
        if self.execution_deadline < self.concluded_at:
            raise ValueError("Срок исполнения раньше даты заключения")
        if self.payment_deadline < self.concluded_at:
            raise ValueError("Срок оплаты раньше даты заключения")
        if self.paid_rub > self.price_rub:
            raise ValueError("Оплачено больше цены контракта")
        return self


class ContractsResponse(CamelModel):
    meta: Meta
    supplier_inn: str
    contracts: list[Contract]


# --- тело админ-API ------------------------------------------------------------------------------


class TaxBody(Strict):
    """Тело `PUT /admin/subjects/{inn}` (8.3)."""

    tax_profile: TaxProfileCard | None = None
    financials: list[FinancialRecord] = []
    sme: SmeRecord | None = None
    npd: NpdRecord | None = None
    account_blocks: list[AccountBlockRecord] = []
    contracts: list[Contract] = []
