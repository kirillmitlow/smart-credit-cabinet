"""Схемы mock-credit-bureau: запрос отчёта, отчёт, submissions, тело админ-API (разделы 6, 8.3).

Модуль без `from __future__ import annotations`: FastAPI и Pydantic строят по аннотациям схемы.
Тело админ-PUT — в терминах ответа бизнес-API без meta и без «сегодняшних» чисел: вместо дней
просрочки и корзин там `overduePeriods` (6.4, 8.3).
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from app.common.schemas import CamelModel, Meta


class SubjectType(StrEnum):
    LEGAL_ENTITY = "LEGAL_ENTITY"
    PERSON = "PERSON"


class ObligationKind(StrEnum):
    LOAN = "LOAN"
    CREDIT_LINE = "CREDIT_LINE"
    OVERDRAFT = "OVERDRAFT"
    CREDIT_CARD = "CREDIT_CARD"
    LEASING = "LEASING"
    GUARANTEE = "GUARANTEE"
    SURETY = "SURETY"


class ObligationRole(StrEnum):
    BORROWER = "BORROWER"
    CO_BORROWER = "CO_BORROWER"
    GUARANTOR = "GUARANTOR"


class ObligationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RESTRUCTURED = "RESTRUCTURED"
    SOLD_TO_COLLECTORS = "SOLD_TO_COLLECTORS"
    WRITTEN_OFF = "WRITTEN_OFF"
    IN_COURT = "IN_COURT"


class PaymentStatus(StrEnum):
    OK = "OK"
    D1_29 = "D1_29"
    D30_59 = "D30_59"
    D60_89 = "D60_89"
    D90_119 = "D90_119"
    D120_PLUS = "D120_PLUS"
    NO_DATA = "NO_DATA"


class UserType(StrEnum):
    BANK = "BANK"
    MFO = "MFO"
    LEASING = "LEASING"
    INSURER = "INSURER"
    OTHER = "OTHER"


class ApplicationDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    WITHDRAWN = "WITHDRAWN"


class BankruptcyStage(StrEnum):
    OBSERVATION = "OBSERVATION"
    RESTRUCTURING = "RESTRUCTURING"
    PROPERTY_REALIZATION = "PROPERTY_REALIZATION"
    COMPLETED = "COMPLETED"


class MatchStatus(StrEnum):
    MATCHED = "MATCHED"
    NOT_FOUND = "NOT_FOUND"


Day = date  # псевдоним: поля `date` в схемах затеняют имя типа
Inn = Annotated[str, Field(min_length=1, max_length=12)]


class Subject(CamelModel):
    """Субъект кредитной истории: организация (ogrn, name) или человек (ФИО, birthDate)."""

    type: SubjectType
    inn: Inn
    ogrn: str | None = Field(default=None, max_length=15)
    name: str | None = Field(default=None, max_length=500)
    last_name: str | None = Field(default=None, max_length=100)
    first_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    birth_date: Day | None = None


# ---------- POST /credit-reports ----------


class Consent(CamelModel):
    consent_id: str = Field(max_length=100)
    subject_inn: str = Field(max_length=12)
    signed_at: AwareDatetime
    valid_until: Day
    purpose: str = Field(min_length=1, max_length=64)
    sign_method: str | None = Field(default=None, max_length=64)
    signer_inn: str | None = Field(default=None, max_length=12)
    text_version: str | None = Field(default=None, max_length=64)


class CreditReportRequest(CamelModel):
    subject: Subject
    # Необязательное в схеме: отсутствие даёт 403 CONSENT_MISSING, а не 422 (6.1)
    consent: Consent | None = None
    purpose: str = Field(min_length=1, max_length=64)
    application_ref: str | None = Field(default=None, max_length=64)


class ReportSummary(CamelModel):
    active_obligations: int
    closed_obligations: int
    total_debt_rub: int
    monthly_payments_rub: int
    contingent_liabilities_rub: int
    current_overdue_rub: int
    current_overdue_days: int
    max_overdue_days24m: int = Field(alias="maxOverdueDays24m")
    restructurings24m: int = Field(alias="restructurings24m")
    inquiries30d: int = Field(alias="inquiries30d")
    inquiries30d_excluding_own: int = Field(alias="inquiries30dExcludingOwn")
    rejected_applications90d: int = Field(alias="rejectedApplications90d")
    rejected_applications90d_excluding_own: int = Field(alias="rejectedApplications90dExcludingOwn")
    history_length_months: int


class PaymentMonth(CamelModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    status: PaymentStatus


class ReportObligation(CamelModel):
    uid: str
    kind: ObligationKind
    role: ObligationRole
    opened_at: Day
    planned_close_at: Day | None
    closed_at: Day | None
    amount_rub: int | None
    limit_rub: int | None
    balance_rub: int
    monthly_payment_rub: int | None
    overdue_rub: int
    overdue_days: int
    status: ObligationStatus
    secured: bool
    payment_history: list[PaymentMonth]


class ReportInquiry(CamelModel):
    date: Day
    user_type: UserType
    purpose: str
    is_own: bool


class ReportApplication(CamelModel):
    date: Day
    kind: str
    amount_rub: int
    decision: ApplicationDecision
    decision_date: Day | None
    is_own: bool


class ReportBankruptcy(CamelModel):
    case_number: str
    stage: BankruptcyStage
    started_at: Day
    completed_at: Day | None


class BureauScore(CamelModel):
    value: int
    scale_min: int
    scale_max: int
    model: str


class CreditReportBody(CamelModel):
    """Отчёт без meta: именно он хранится как снимок и повторно отдаётся без пересчёта."""

    report_id: str
    generated_at: datetime
    match_status: MatchStatus
    subject: Subject
    has_history: bool
    summary: ReportSummary
    obligations: list[ReportObligation]
    inquiries: list[ReportInquiry]
    applications: list[ReportApplication]
    bankruptcies: list[ReportBankruptcy]
    bureau_score: BureauScore | None


class CreditReport(CreditReportBody):
    """Ответ бизнес-API: meta + снимок отчёта."""

    meta: Meta


# ---------- POST /submissions ----------


class RegisteredApplication(CamelModel):
    ref: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=16, examples=["LOAN"])
    amount_rub: int = Field(ge=0)
    term_months: int | None = Field(default=None, ge=1)


class DecidedApplication(CamelModel):
    ref: str = Field(min_length=1, max_length=64)
    decision: Literal[
        ApplicationDecision.APPROVED, ApplicationDecision.REJECTED, ApplicationDecision.WITHDRAWN
    ]


class OpenedObligation(CamelModel):
    uid: str = Field(min_length=1, max_length=64)
    kind: ObligationKind
    role: ObligationRole = ObligationRole.BORROWER
    opened_at: Day
    planned_close_at: Day | None = None
    amount_rub: int | None = Field(default=None, ge=0)
    limit_rub: int | None = Field(default=None, ge=0)
    balance_rub: int | None = Field(default=None, ge=0, description="По умолчанию равен amountRub")
    monthly_payment_rub: int | None = Field(default=None, ge=0)
    secured: bool = False


class ClosedObligation(CamelModel):
    uid: str = Field(min_length=1, max_length=64)
    closed_at: Day


class _Event(CamelModel):
    event_id: str = Field(min_length=1, max_length=200)
    occurred_at: AwareDatetime
    subject: Subject


class ApplicationRegistered(_Event):
    event_type: Literal["APPLICATION_REGISTERED"]
    application: RegisteredApplication


class ApplicationDecided(_Event):
    event_type: Literal["APPLICATION_DECIDED"]
    application: DecidedApplication


class ObligationOpened(_Event):
    event_type: Literal["OBLIGATION_OPENED"]
    obligation: OpenedObligation


class ObligationClosed(_Event):
    event_type: Literal["OBLIGATION_CLOSED"]
    obligation: ClosedObligation


SubmissionEvent = Annotated[
    ApplicationRegistered | ApplicationDecided | ObligationOpened | ObligationClosed,
    Field(discriminator="event_type"),
]


class SubmissionAccepted(CamelModel):
    meta: Meta
    submission_id: str
    status: Literal["ACCEPTED"] = "ACCEPTED"


# ---------- админ-API: тело PUT (8.3) ----------


class OverduePeriod(CamelModel):
    since: Day
    until: Day | None = None  # null — текущая просрочка


class AdminObligation(CamelModel):
    uid: str = Field(min_length=1, max_length=64)
    kind: ObligationKind
    role: ObligationRole = ObligationRole.BORROWER
    opened_at: Day
    planned_close_at: Day | None = None
    closed_at: Day | None = None
    amount_rub: int | None = None
    limit_rub: int | None = None
    balance_rub: int = 0
    monthly_payment_rub: int | None = None
    overdue_rub: int = 0
    overdue_periods: list[OverduePeriod] = []
    status: ObligationStatus = ObligationStatus.ACTIVE
    secured: bool = False
    # Явная история хранится как есть; null — строится при чтении из overduePeriods
    payment_history: list[PaymentMonth] | None = None


class AdminInquiry(CamelModel):
    date: Day
    user_type: UserType = UserType.BANK
    purpose: str = Field(default="LOAN_APPLICATION", max_length=64)
    is_own: bool = False


class AdminApplication(CamelModel):
    date: Day
    kind: str = Field(default="LOAN", max_length=16)
    amount_rub: int = Field(ge=0)
    decision: ApplicationDecision
    decision_date: Day | None = None
    is_own: bool = False


class AdminBankruptcy(CamelModel):
    case_number: str = Field(max_length=64)
    stage: BankruptcyStage
    started_at: Day
    completed_at: Day | None = None


class BkiSubjectBody(CamelModel):
    subject: Subject
    obligations: list[AdminObligation] = []
    inquiries: list[AdminInquiry] = []
    applications: list[AdminApplication] = []
    bankruptcies: list[AdminBankruptcy] = []
