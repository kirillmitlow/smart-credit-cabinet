"""Порт `bank_core` на чтение: клиент банка, обороты, наши кредиты, проверка по спискам (моки 7.1–7.6, T-234).

Выдача и открытие счёта — отдельная задача (T-236). Кредиты АБС и БКИ адаптер не объединяет:
это делают признаки по равенству `contract_uid` = `uid` (R4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import Field

from app.modules.integrations._dto import Dto
from app.modules.integrations.client import IntegrationClient
from app.modules.integrations.policy import BANK_CORE_READ
from app.modules.integrations.results import Result

SCREENING_ROLES = frozenset({"COMPANY", "DIRECTOR", "FOUNDER", "IE"})

# --- внутренние модели ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BankAccount:
    number: str
    type: str
    currency: str
    status: str  # OPEN | BLOCKED | CLOSED
    opened_at: date
    balance_rub: int


@dataclass(frozen=True, slots=True)
class Customer:
    customer_id: str
    inn: str
    kind: str
    name: str
    customer_since: date
    accounts: tuple[BankAccount, ...]


@dataclass(frozen=True, slots=True)
class TurnoverMonth:
    month: str  # YYYY-MM
    incoming_rub: int  # поступления с НДС
    incoming_net_rub: int  # без переводов себе и полученных кредитов
    outgoing_rub: int
    counterparties_in: int
    counterparties_out: int


@dataclass(frozen=True, slots=True)
class Turnover:
    """Помесячные обороты по расчётному счёту, от старого месяца к новому."""

    inn: str
    account_numbers: tuple[str, ...]
    months: tuple[TurnoverMonth, ...]


@dataclass(frozen=True, slots=True)
class OurLoan:
    loan_id: str
    application_ref: str | None
    contract_number: str | None
    contract_uid: str
    product_code: str | None
    kind: str  # LOAN | CREDIT_LINE | OVERDRAFT
    amount_rub: int | None
    limit_rub: int | None
    outstanding_rub: int
    term_months: int | None
    rate_percent: float | None
    repayment_type: str | None
    loan_account: str | None
    settlement_account: str | None
    status: str  # ACTIVE | CLOSED
    disbursed_at: date


@dataclass(frozen=True, slots=True)
class ScreeningSubject:
    inn: str
    role: str  # COMPANY | DIRECTOR | FOUNDER | IE


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    inn: str
    role: str
    aml_listed: bool
    aml_list_name: str | None
    zsk_risk_level: str | None  # GREEN | YELLOW | RED; у физлиц нет
    internal_stop_listed: bool
    internal_stop_reason: str | None


@dataclass(frozen=True, slots=True)
class ComplianceResult:
    screening_id: str
    overall: str  # CLEAR | HIT
    results: tuple[ScreeningResult, ...]

    @property
    def aml_hits(self) -> tuple[ScreeningResult, ...]:
        return tuple(r for r in self.results if r.aml_listed)


# --- DTO под JSON мока ---------------------------------------------------------------------------


class _AccountDto(Dto):
    number: str
    type: str
    currency: str
    status: str
    opened_at: date
    balance_rub: int


class _CustomerDto(Dto):
    customer_id: str
    inn: str
    type: str
    name: str
    customer_since: date
    accounts: list[_AccountDto] = Field(default_factory=list)


class _MonthDto(Dto):
    month: str
    incoming_rub: int
    incoming_net_rub: int
    outgoing_rub: int
    counterparties_in: int
    counterparties_out: int


class _TurnoverDto(Dto):
    inn: str
    account_numbers: list[str] = Field(default_factory=list)
    months: list[_MonthDto]


class _LoanDto(Dto):
    loan_id: str
    application_ref: str | None = None
    contract_number: str | None = None
    contract_uid: str
    product_code: str | None = None
    kind: str
    amount_rub: int | None = None
    limit_rub: int | None = None
    outstanding_rub: int
    term_months: int | None = None
    rate_percent: float | None = None
    repayment_type: str | None = None
    loan_account: str | None = None
    settlement_account: str | None = None
    status: str
    disbursed_at: date


class _LoansDto(Dto):
    loans: list[_LoanDto]


class _AmlDto(Dto):
    listed: bool
    list_name: str | None = None


class _ZskDto(Dto):
    risk_level: str


class _StopListDto(Dto):
    listed: bool
    reason: str | None = None


class _ScreeningItemDto(Dto):
    inn: str
    role: str
    aml_list: _AmlDto
    zsk: _ZskDto | None = None
    internal_stop_list: _StopListDto


class _ScreeningDto(Dto):
    screening_id: str
    overall: str
    results: list[_ScreeningItemDto]


# --- маппинг -------------------------------------------------------------------------------------


def map_customer(payload: object) -> Customer:
    dto = _CustomerDto.model_validate(payload)
    return Customer(
        dto.customer_id,
        dto.inn,
        dto.type,
        dto.name,
        dto.customer_since,
        tuple(
            BankAccount(a.number, a.type, a.currency, a.status, a.opened_at, a.balance_rub)
            for a in dto.accounts
        ),
    )


def map_turnover(payload: object) -> Turnover:
    dto = _TurnoverDto.model_validate(payload)
    return Turnover(
        dto.inn,
        tuple(dto.account_numbers),
        tuple(
            TurnoverMonth(
                m.month,
                m.incoming_rub,
                m.incoming_net_rub,
                m.outgoing_rub,
                m.counterparties_in,
                m.counterparties_out,
            )
            for m in dto.months
        ),
    )


def map_loans(payload: object) -> tuple[OurLoan, ...]:
    dto = _LoansDto.model_validate(payload)
    return tuple(
        OurLoan(
            loan_id=x.loan_id,
            application_ref=x.application_ref,
            contract_number=x.contract_number,
            contract_uid=x.contract_uid,
            product_code=x.product_code,
            kind=x.kind,
            amount_rub=x.amount_rub,
            limit_rub=x.limit_rub,
            outstanding_rub=x.outstanding_rub,
            term_months=x.term_months,
            rate_percent=x.rate_percent,
            repayment_type=x.repayment_type,
            loan_account=x.loan_account,
            settlement_account=x.settlement_account,
            status=x.status,
            disbursed_at=x.disbursed_at,
        )
        for x in dto.loans
    )


def map_screening(payload: object) -> ComplianceResult:
    dto = _ScreeningDto.model_validate(payload)
    return ComplianceResult(
        dto.screening_id,
        dto.overall,
        tuple(
            ScreeningResult(
                r.inn,
                r.role,
                r.aml_list.listed,
                r.aml_list.list_name,
                r.zsk.risk_level if r.zsk else None,
                r.internal_stop_list.listed,
                r.internal_stop_list.reason,
            )
            for r in dto.results
        ),
    )


def _check_screening_subjects(subjects: Sequence[ScreeningSubject]) -> None:
    """Без нужных субъектов проверку не запускаем: «чисто» по пустому списку было бы ложью."""
    if not subjects:
        raise ValueError("Проверка по спискам: нужен хотя бы один субъект")
    bad = [s.role for s in subjects if s.role not in SCREENING_ROLES]
    if bad:
        raise ValueError(f"Проверка по спискам: неизвестная роль {bad[0]}")
    roles = {s.role for s in subjects}
    if not roles & {"COMPANY", "IE"}:
        raise ValueError("Проверка по спискам: нужна компания (COMPANY) или ИП (IE)")
    if "COMPANY" in roles and "DIRECTOR" not in roles:
        raise ValueError("Проверка по спискам: у компании нужен директор (DIRECTOR)")


# --- порт ----------------------------------------------------------------------------------------


class BankCoreReadAdapter:
    def __init__(self, client: IntegrationClient) -> None:
        self._client = client

    def get_customer(
        self, inn: str, *, application_id: UUID | None = None
    ) -> Result[Customer | None]:
        """Клиент банка. Не клиент (`404`) → `Ok(None)`."""
        return self._client.call(
            policy=BANK_CORE_READ,
            method="GET",
            path=f"/api/v1/customers/{inn}",
            parse=map_customer,
            allow_404=True,
            subject_inn=inn,
            application_id=application_id,
            resource="bank_core:customer",
        )

    def get_turnover(
        self, inn: str, months: int = 12, *, application_id: UUID | None = None
    ) -> Result[Turnover | None]:
        """Помесячные обороты, до 24 месяцев. Не клиент → `Ok(None)`.

        Согласие клиента проверяет вызывающий до вызова, каждый вызов уходит в аудит `api`.
        """
        if not 1 <= months <= 24:
            raise ValueError("Обороты: months от 1 до 24")
        return self._client.call(
            policy=BANK_CORE_READ,
            method="GET",
            path=f"/api/v1/customers/{inn}/turnover",
            params={"months": months},
            parse=map_turnover,
            allow_404=True,
            subject_inn=inn,
            application_id=application_id,
            resource="bank_core:turnover",
        )

    def get_loans(
        self, inn: str, *, application_id: UUID | None = None
    ) -> Result[tuple[OurLoan, ...] | None]:
        """Действующие и закрытые кредиты нашего банка. Не клиент → `Ok(None)`, нет кредитов → `()`."""
        return self._client.call(
            policy=BANK_CORE_READ,
            method="GET",
            path=f"/api/v1/customers/{inn}/loans",
            parse=map_loans,
            allow_404=True,
            subject_inn=inn,
            application_id=application_id,
            resource="bank_core:loans",
        )

    def screen(
        self, subjects: Sequence[ScreeningSubject], *, application_id: UUID | None = None
    ) -> Result[ComplianceResult]:
        """Проверка по спискам Росфинмониторинга, ЗСК и внутреннему стоп-листу одним вызовом.

        Запрос только читает, поэтому повторяем. Без компании/ИП и директора (для компании)
        бросает `ValueError`: это ошибка вызывающего, а не сбой источника.
        """
        _check_screening_subjects(subjects)
        return self._client.call(
            policy=BANK_CORE_READ,
            method="POST",
            path="/api/v1/compliance/screening",
            json_body={"subjects": [{"inn": s.inn, "role": s.role} for s in subjects]},
            parse=map_screening,
            read_only_post=True,
            subject_inn=subjects[0].inn,
            application_id=application_id,
            resource="bank_core:compliance",
        )
