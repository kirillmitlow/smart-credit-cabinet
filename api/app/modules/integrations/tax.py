"""Порт `tax`: «Прозрачный бизнес», ГИР БО, реестр МСП, НПД, блокировки счетов, ЕИС (моки 5.1–5.6, T-233).

Каждая ручка — отдельный вызов со своим результатом: недоступность одной не роняет остальные.
`404` на профиль и на отчётность — нормальный ответ (нет налогоплательщика, у ИП нет отчётности).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from uuid import UUID

from pydantic import Field

from app.modules.integrations._dto import Dto
from app.modules.integrations.client import IntegrationClient
from app.modules.integrations.policy import TAX
from app.modules.integrations.results import Result
from app.shared import clock

# --- внутренние модели ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaxRegime:
    code: str
    year: int


@dataclass(frozen=True, slots=True)
class TaxesPaid:
    year: int
    total_rub: int


@dataclass(frozen=True, slots=True)
class TaxProfile:
    inn: str
    regimes: tuple[TaxRegime, ...]
    avg_headcount: int | None
    headcount_year: int | None
    taxes_paid: tuple[TaxesPaid, ...]
    debts_as_of: date
    tax_debt_rub: int
    penalties_rub: int
    fines_rub: int
    # У ИП блока доходов и расходов нет: бухотчётности у них нет
    income_year: int | None
    income_rub: int | None
    expenses_rub: int | None
    offenses_count: int
    offenses_fines_rub: int
    mass_address: bool
    mass_director: bool
    mass_founder: bool
    disqualified_management: bool
    no_reports_over_year: bool


@dataclass(frozen=True, slots=True)
class FinancialLine:
    current: int | None
    previous: int | None


@dataclass(frozen=True, slots=True)
class FinancialSummary:
    revenue_rub: int
    sales_profit_rub: int
    interest_payable_rub: int
    net_profit_rub: int
    total_assets_rub: int
    equity_rub: int
    long_term_liabilities_rub: int
    short_term_liabilities_rub: int


@dataclass(frozen=True, slots=True)
class Financials:
    """Годовая отчётность ГИР БО. Строки: 2110 выручка, 2200 прибыль от продаж, 2330 проценты,
    2400 чистая прибыль, 1100…1600 баланс."""

    inn: str
    year: int
    available_years: tuple[int, ...]
    form_type: str  # FULL | SIMPLIFIED
    submitted_at: date | None
    lines: Mapping[str, FinancialLine]
    summary: FinancialSummary

    def line(self, code: str) -> int | None:
        found = self.lines.get(code)
        return found.current if found else None


@dataclass(frozen=True, slots=True)
class SmeStatus:
    inn: str
    in_registry: bool
    category: str | None  # MICRO | SMALL | MEDIUM
    included_at: date | None
    is_newly_created: bool
    is_social_enterprise: bool


@dataclass(frozen=True, slots=True)
class SelfEmployedStatus:
    inn: str
    is_self_employed: bool
    checked_on: date


@dataclass(frozen=True, slots=True)
class AccountBlock:
    number: str
    decided_on: date
    tax_authority_code: str | None
    bik: str
    reason: str  # NON_SUBMISSION_OF_DECLARATION | TAX_DEBT_COLLECTION | OTHER


@dataclass(frozen=True, slots=True)
class GovContract:
    registry_number: str
    customer_name: str
    customer_inn: str | None
    subject: str
    price_rub: int
    concluded_at: date
    execution_deadline: date
    payment_deadline: date
    status: str  # IN_PROGRESS | EXECUTED | TERMINATED
    paid_rub: int


# --- DTO под JSON мока ---------------------------------------------------------------------------


class _RegimeDto(Dto):
    code: str
    year: int


class _HeadcountDto(Dto):
    value: int
    year: int


class _TaxesPaidDto(Dto):
    year: int
    total_rub: int


class _DebtsDto(Dto):
    as_of: date
    tax_debt_rub: int
    penalties_rub: int
    fines_rub: int


class _IncomeDto(Dto):
    year: int
    income_rub: int
    expenses_rub: int


class _OffensesDto(Dto):
    count: int
    fines_rub: int


class _RiskFlagsDto(Dto):
    mass_address: bool
    mass_director: bool
    mass_founder: bool
    disqualified_management: bool
    no_reports_over_year: bool


class _TaxProfileDto(Dto):
    inn: str
    tax_regimes: list[_RegimeDto]
    avg_headcount: _HeadcountDto | None = None
    taxes_paid: list[_TaxesPaidDto] = Field(default_factory=list)
    debts: _DebtsDto
    income_expenses: _IncomeDto | None = None
    tax_offenses: _OffensesDto | None = None
    risk_flags: _RiskFlagsDto


class _LineDto(Dto):
    current: int | None = None
    previous: int | None = None


class _SummaryDto(Dto):
    revenue_rub: int
    sales_profit_rub: int
    interest_payable_rub: int
    net_profit_rub: int
    total_assets_rub: int
    equity_rub: int
    long_term_liabilities_rub: int
    short_term_liabilities_rub: int


class _FinancialsDto(Dto):
    inn: str
    year: int
    available_years: list[int]
    form_type: str
    submitted_at: date | None = None
    lines: dict[str, _LineDto]
    summary: _SummaryDto


class _SmeDto(Dto):
    inn: str
    in_registry: bool
    category: str | None = None
    included_at: date | None = None
    is_newly_created: bool = False
    is_social_enterprise: bool = False


class _NpdDto(Dto):
    status: bool


class _BlockDto(Dto):
    number: str
    date: date
    tax_authority_code: str | None = None
    bik: str
    reason: str


class _BlocksDto(Dto):
    decisions: list[_BlockDto]


class _CustomerDto(Dto):
    name: str
    inn: str | None = None


class _ContractDto(Dto):
    registry_number: str
    customer: _CustomerDto
    subject: str
    price_rub: int
    concluded_at: date
    execution_deadline: date
    payment_deadline: date
    status: str
    paid_rub: int


class _ContractsDto(Dto):
    contracts: list[_ContractDto]


# --- маппинг -------------------------------------------------------------------------------------


def map_tax_profile(payload: object) -> TaxProfile:
    dto = _TaxProfileDto.model_validate(payload)
    income = dto.income_expenses
    offenses = dto.tax_offenses
    flags = dto.risk_flags
    return TaxProfile(
        inn=dto.inn,
        regimes=tuple(TaxRegime(r.code, r.year) for r in dto.tax_regimes),
        avg_headcount=dto.avg_headcount.value if dto.avg_headcount else None,
        headcount_year=dto.avg_headcount.year if dto.avg_headcount else None,
        taxes_paid=tuple(TaxesPaid(t.year, t.total_rub) for t in dto.taxes_paid),
        debts_as_of=dto.debts.as_of,
        tax_debt_rub=dto.debts.tax_debt_rub,
        penalties_rub=dto.debts.penalties_rub,
        fines_rub=dto.debts.fines_rub,
        income_year=income.year if income else None,
        income_rub=income.income_rub if income else None,
        expenses_rub=income.expenses_rub if income else None,
        offenses_count=offenses.count if offenses else 0,
        offenses_fines_rub=offenses.fines_rub if offenses else 0,
        mass_address=flags.mass_address,
        mass_director=flags.mass_director,
        mass_founder=flags.mass_founder,
        disqualified_management=flags.disqualified_management,
        no_reports_over_year=flags.no_reports_over_year,
    )


def map_financials(payload: object) -> Financials:
    dto = _FinancialsDto.model_validate(payload)
    s = dto.summary
    return Financials(
        inn=dto.inn,
        year=dto.year,
        available_years=tuple(dto.available_years),
        form_type=dto.form_type,
        submitted_at=dto.submitted_at,
        lines=MappingProxyType(
            {k: FinancialLine(v.current, v.previous) for k, v in dto.lines.items()}
        ),
        summary=FinancialSummary(
            s.revenue_rub,
            s.sales_profit_rub,
            s.interest_payable_rub,
            s.net_profit_rub,
            s.total_assets_rub,
            s.equity_rub,
            s.long_term_liabilities_rub,
            s.short_term_liabilities_rub,
        ),
    )


def map_sme(payload: object) -> SmeStatus:
    dto = _SmeDto.model_validate(payload)
    return SmeStatus(
        dto.inn,
        dto.in_registry,
        dto.category,
        dto.included_at,
        dto.is_newly_created,
        dto.is_social_enterprise,
    )


def map_blocks(payload: object) -> tuple[AccountBlock, ...]:
    dto = _BlocksDto.model_validate(payload)
    return tuple(
        AccountBlock(b.number, b.date, b.tax_authority_code, b.bik, b.reason) for b in dto.decisions
    )


def map_contracts(payload: object) -> tuple[GovContract, ...]:
    dto = _ContractsDto.model_validate(payload)
    return tuple(
        GovContract(
            c.registry_number,
            c.customer.name,
            c.customer.inn,
            c.subject,
            c.price_rub,
            c.concluded_at,
            c.execution_deadline,
            c.payment_deadline,
            c.status,
            c.paid_rub,
        )
        for c in dto.contracts
    )


# --- порт ----------------------------------------------------------------------------------------


class TaxAdapter:
    def __init__(self, client: IntegrationClient) -> None:
        self._client = client

    def get_tax_profile(
        self, inn: str, *, application_id: UUID | None = None
    ) -> Result[TaxProfile | None]:
        """«Прозрачный бизнес»: долги, режимы, флаги массовости. Нет налогоплательщика → `Ok(None)`."""
        return self._client.call(
            policy=TAX,
            method="GET",
            path=f"/api/v1/tax-profile/{inn}",
            parse=map_tax_profile,
            allow_404=True,
            subject_inn=inn,
            application_id=application_id,
            resource="tax:profile",
        )

    def get_financials(
        self, inn: str, year: int | None = None, *, application_id: UUID | None = None
    ) -> Result[Financials | None]:
        """Отчётность ГИР БО. Нет отчётности (ИП, молодая компания, неподанный год) → `Ok(None)`."""
        return self._client.call(
            policy=TAX,
            method="GET",
            path=f"/api/v1/financials/{inn}",
            params={"year": year} if year is not None else None,
            parse=map_financials,
            allow_404=True,
            subject_inn=inn,
            application_id=application_id,
            resource="tax:financials",
        )

    def get_sme_status(self, inn: str, *, application_id: UUID | None = None) -> Result[SmeStatus]:
        """Реестр МСП. Нет в реестре — это ответ (`in_registry=False`), а не ошибка."""
        return self._client.call(
            policy=TAX,
            method="GET",
            path=f"/api/v1/sme-status/{inn}",
            parse=map_sme,
            subject_inn=inn,
            application_id=application_id,
            resource="tax:sme",
        )

    def get_self_employed_status(
        self, inn: str, on: date | None = None, *, application_id: UUID | None = None
    ) -> Result[SelfEmployedStatus]:
        """Статус НПД на дату (по умолчанию «сегодня» стенда). Запрос только читает, поэтому повторяем."""
        day = on or clock.today()
        return self._client.call(
            policy=TAX,
            method="POST",
            path="/api/v1/self-employed/status",
            json_body={"inn": inn, "requestDate": day.isoformat()},
            parse=lambda payload: SelfEmployedStatus(
                inn, _NpdDto.model_validate(payload).status, day
            ),
            read_only_post=True,
            subject_inn=inn,
            application_id=application_id,
            resource="tax:npd",
        )

    def get_account_blocks(
        self, inn: str, bik: str | None = None, *, application_id: UUID | None = None
    ) -> Result[tuple[AccountBlock, ...]]:
        """Решения налоговой о блокировке счетов (Should: правило выключено, данные забираем)."""
        return self._client.call(
            policy=TAX,
            method="GET",
            path=f"/api/v1/account-blocks/{inn}",
            params={"bik": bik} if bik else None,
            parse=map_blocks,
            subject_inn=inn,
            application_id=application_id,
            resource="tax:blocks",
        )

    def get_gov_contracts(
        self, supplier_inn: str, status: str | None = None, *, application_id: UUID | None = None
    ) -> Result[tuple[GovContract, ...]]:
        """Госконтракты поставщика из ЕИС. Контрактов нет → пустой кортеж."""
        return self._client.call(
            policy=TAX,
            method="GET",
            path="/api/v1/contracts",
            params={"supplierInn": supplier_inn, **({"status": status} if status else {})},
            parse=map_contracts,
            subject_inn=supplier_inn,
            application_id=application_id,
            resource="tax:contracts",
        )
