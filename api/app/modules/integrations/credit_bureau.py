"""Порт `credit_bureau`: отчёты БКИ по субъектам и передача сведений банка (моки 6.1, 6.3, T-235).

Отчёт платный и требует согласия субъекта: функция `request_report` принимает `BkiConsent`
обязательным аргументом, без него вызвать её нельзя. Ключ идемпотентности строится из заявки
и субъекта, поэтому повтор после обрыва возвращает тот же отчёт и второго платного запроса нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

import structlog
from pydantic import Field

from app.modules.integrations._dto import Dto
from app.modules.integrations.client import IntegrationClient
from app.modules.integrations.policy import BUREAU_REPORT, BUREAU_SUBMIT
from app.modules.integrations.registry import BankruptcyCase
from app.modules.integrations.results import Reason, Result, SourceUnavailable, System
from app.shared import clock
from app.shared.logs import mask_inn

log = structlog.get_logger("app.integrations.credit_bureau")

# Допуск часов между контейнерами: согласие «из будущего» принимаем в пределах 5 минут (моки 2.5)
CONSENT_CLOCK_SKEW = timedelta(minutes=5)

# --- входные типы --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BkiConsent:
    """Реквизиты согласия субъекта на запрос в БКИ. Согласия хранит банк (consents), в БКИ уходят реквизиты."""

    consent_id: str
    subject_inn: str
    signed_at: datetime
    valid_until: date
    purpose: str
    sign_method: str
    signer_inn: str
    text_version: str


@dataclass(frozen=True, slots=True)
class BureauSubject:
    """Субъект отчёта. `LEGAL_ENTITY` — 10 цифр ИНН, `PERSON` — 12 (директор, владелец, ИП как человек)."""

    type: Literal["LEGAL_ENTITY", "PERSON"]
    inn: str
    name: str | None = None
    ogrn: str | None = None
    last_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    birth_date: date | None = None

    def __post_init__(self) -> None:
        expected = 10 if self.type == "LEGAL_ENTITY" else 12
        if len(self.inn) != expected or not self.inn.isdigit():
            raise ValueError(f"Субъект {self.type}: ИНН из {expected} цифр")


class BureauEventType(StrEnum):
    APPLICATION_REGISTERED = "APPLICATION_REGISTERED"
    APPLICATION_DECIDED = "APPLICATION_DECIDED"
    OBLIGATION_OPENED = "OBLIGATION_OPENED"
    OBLIGATION_CLOSED = "OBLIGATION_CLOSED"


@dataclass(frozen=True, slots=True)
class EventApplication:
    ref: str
    kind: str | None = None
    amount_rub: int | None = None
    term_months: int | None = None
    decision: str | None = None  # APPROVED | REJECTED | WITHDRAWN


@dataclass(frozen=True, slots=True)
class EventObligation:
    uid: str
    kind: str | None = None
    role: str | None = None
    opened_at: date | None = None
    planned_close_at: date | None = None
    closed_at: date | None = None
    amount_rub: int | None = None
    monthly_payment_rub: int | None = None
    secured: bool | None = None


@dataclass(frozen=True, slots=True)
class BureauEvent:
    """Событие банка для БКИ. `event_id` постоянный: повтор события возвращает исходный ответ."""

    event_id: str
    event_type: BureauEventType
    occurred_at: datetime
    subject: BureauSubject
    application: EventApplication | None = None
    obligation: EventObligation | None = None


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    submission_id: str
    status: str


# --- внутренние модели отчёта --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BureauSummary:
    active_obligations: int
    closed_obligations: int
    total_debt_rub: int
    monthly_payments_rub: int
    contingent_liabilities_rub: int
    current_overdue_rub: int
    current_overdue_days: int
    max_overdue_days_24m: int
    restructurings_24m: int
    inquiries_30d: int
    inquiries_30d_excluding_own: int
    rejected_applications_90d: int
    rejected_applications_90d_excluding_own: int
    history_length_months: int


@dataclass(frozen=True, slots=True)
class Obligation:
    uid: str  # у кредитов нашего банка равен contractUid в АБС
    kind: str
    role: str
    status: str
    opened_at: date
    planned_close_at: date | None
    closed_at: date | None
    amount_rub: int | None
    limit_rub: int | None
    balance_rub: int
    monthly_payment_rub: int | None
    overdue_rub: int
    overdue_days: int
    secured: bool
    payment_history: tuple[tuple[str, str], ...]  # (месяц YYYY-MM, статус OK|D1_29|…)


@dataclass(frozen=True, slots=True)
class Inquiry:
    on: date
    user_type: str
    purpose: str
    is_own: bool


@dataclass(frozen=True, slots=True)
class BureauApplication:
    on: date
    kind: str
    amount_rub: int | None
    decision: str
    decision_date: date | None
    is_own: bool


@dataclass(frozen=True, slots=True)
class BureauScore:
    """Оценка бюро: только для показа андеррайтеру, в решении не участвует (30-02)."""

    value: int
    scale_min: int
    scale_max: int
    model: str


@dataclass(frozen=True, slots=True)
class CreditHistory:
    """Отчёт БКИ. Для признаков берите `*_excluding_own`: наши запросы и отказы не считаются."""

    report_id: str
    generated_at: datetime
    match_status: str  # MATCHED | NOT_FOUND
    subject_type: str
    subject_inn: str
    has_history: bool
    summary: BureauSummary
    obligations: tuple[Obligation, ...]
    inquiries: tuple[Inquiry, ...]
    applications: tuple[BureauApplication, ...]
    bankruptcies: tuple[BankruptcyCase, ...]
    bureau_score: BureauScore | None


# --- DTO под JSON мока ---------------------------------------------------------------------------


class _SubjectDto(Dto):
    type: str
    inn: str


class _SummaryDto(Dto):
    # Псевдонимы заданы явно: to_camel пишет «24M» и «30D» с заглавной после цифры
    active_obligations: int
    closed_obligations: int
    total_debt_rub: int
    monthly_payments_rub: int
    contingent_liabilities_rub: int
    current_overdue_rub: int
    current_overdue_days: int
    max_overdue_days_24m: int = Field(alias="maxOverdueDays24m")
    restructurings_24m: int = Field(alias="restructurings24m")
    inquiries_30d: int = Field(alias="inquiries30d")
    inquiries_30d_excluding_own: int = Field(alias="inquiries30dExcludingOwn")
    rejected_applications_90d: int = Field(alias="rejectedApplications90d")
    rejected_applications_90d_excluding_own: int = Field(
        alias="rejectedApplications90dExcludingOwn"
    )
    history_length_months: int


class _PaymentDto(Dto):
    month: str
    status: str


class _ObligationDto(Dto):
    uid: str
    kind: str
    role: str
    status: str
    opened_at: date
    planned_close_at: date | None = None
    closed_at: date | None = None
    amount_rub: int | None = None
    limit_rub: int | None = None
    balance_rub: int
    monthly_payment_rub: int | None = None
    overdue_rub: int = 0
    overdue_days: int = 0
    secured: bool = False
    payment_history: list[_PaymentDto] = Field(default_factory=list)


class _InquiryDto(Dto):
    on: date = Field(alias="date")
    user_type: str
    purpose: str
    is_own: bool


class _ApplicationDto(Dto):
    on: date = Field(alias="date")
    kind: str
    amount_rub: int | None = None
    decision: str
    decision_date: date | None = None
    is_own: bool


class _CaseDto(Dto):
    case_number: str
    stage: str
    started_at: date
    completed_at: date | None = None


class _ScoreDto(Dto):
    value: int
    scale_min: int
    scale_max: int
    model: str


class _ReportDto(Dto):
    report_id: str
    generated_at: datetime
    match_status: str
    subject: _SubjectDto
    has_history: bool
    summary: _SummaryDto
    obligations: list[_ObligationDto] = Field(default_factory=list)
    inquiries: list[_InquiryDto] = Field(default_factory=list)
    applications: list[_ApplicationDto] = Field(default_factory=list)
    bankruptcies: list[_CaseDto] = Field(default_factory=list)
    bureau_score: _ScoreDto | None = None


class _ReceiptDto(Dto):
    submission_id: str
    status: str


# --- маппинг -------------------------------------------------------------------------------------


def map_report(payload: object) -> CreditHistory:
    dto = _ReportDto.model_validate(payload)
    s = dto.summary
    return CreditHistory(
        report_id=dto.report_id,
        generated_at=dto.generated_at,
        match_status=dto.match_status,
        subject_type=dto.subject.type,
        subject_inn=dto.subject.inn,
        has_history=dto.has_history,
        summary=BureauSummary(
            s.active_obligations,
            s.closed_obligations,
            s.total_debt_rub,
            s.monthly_payments_rub,
            s.contingent_liabilities_rub,
            s.current_overdue_rub,
            s.current_overdue_days,
            s.max_overdue_days_24m,
            s.restructurings_24m,
            s.inquiries_30d,
            s.inquiries_30d_excluding_own,
            s.rejected_applications_90d,
            s.rejected_applications_90d_excluding_own,
            s.history_length_months,
        ),
        obligations=tuple(
            Obligation(
                uid=o.uid,
                kind=o.kind,
                role=o.role,
                status=o.status,
                opened_at=o.opened_at,
                planned_close_at=o.planned_close_at,
                closed_at=o.closed_at,
                amount_rub=o.amount_rub,
                limit_rub=o.limit_rub,
                balance_rub=o.balance_rub,
                monthly_payment_rub=o.monthly_payment_rub,
                overdue_rub=o.overdue_rub,
                overdue_days=o.overdue_days,
                secured=o.secured,
                payment_history=tuple((p.month, p.status) for p in o.payment_history),
            )
            for o in dto.obligations
        ),
        inquiries=tuple(Inquiry(i.on, i.user_type, i.purpose, i.is_own) for i in dto.inquiries),
        applications=tuple(
            BureauApplication(a.on, a.kind, a.amount_rub, a.decision, a.decision_date, a.is_own)
            for a in dto.applications
        ),
        bankruptcies=tuple(
            BankruptcyCase(c.case_number, dto.subject.type, c.stage, c.started_at, c.completed_at)
            for c in dto.bankruptcies
        ),
        bureau_score=BureauScore(
            dto.bureau_score.value,
            dto.bureau_score.scale_min,
            dto.bureau_score.scale_max,
            dto.bureau_score.model,
        )
        if dto.bureau_score
        else None,
    )


def map_receipt(payload: object) -> SubmissionReceipt:
    dto = _ReceiptDto.model_validate(payload)
    return SubmissionReceipt(dto.submission_id, dto.status)


# --- тела запросов -------------------------------------------------------------------------------


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _subject_body(subject: BureauSubject) -> dict[str, Any]:
    body: dict[str, Any] = {"type": subject.type, "inn": subject.inn}
    optional = {
        "ogrn": subject.ogrn,
        "name": subject.name,
        "lastName": subject.last_name,
        "firstName": subject.first_name,
        "middleName": subject.middle_name,
        "birthDate": subject.birth_date.isoformat() if subject.birth_date else None,
    }
    body.update({k: v for k, v in optional.items() if v is not None})
    return body


def _consent_body(consent: BkiConsent) -> dict[str, Any]:
    return {
        "consentId": consent.consent_id,
        "subjectInn": consent.subject_inn,
        "signedAt": _moment(consent.signed_at),
        "validUntil": consent.valid_until.isoformat(),
        "purpose": consent.purpose,
        "signMethod": consent.sign_method,
        "signerInn": consent.signer_inn,
        "textVersion": consent.text_version,
    }


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _event_body(event: BureauEvent) -> dict[str, Any]:
    body: dict[str, Any] = {
        "eventId": event.event_id,
        "eventType": event.event_type.value,
        "occurredAt": _moment(event.occurred_at),
        "subject": {"type": event.subject.type, "inn": event.subject.inn},
    }
    if event.application:
        a = event.application
        body["application"] = _clean(
            {
                "ref": a.ref,
                "kind": a.kind,
                "amountRub": a.amount_rub,
                "termMonths": a.term_months,
                "decision": a.decision,
            }
        )
    if event.obligation:
        o = event.obligation
        body["obligation"] = _clean(
            {
                "uid": o.uid,
                "kind": o.kind,
                "role": o.role,
                "openedAt": o.opened_at.isoformat() if o.opened_at else None,
                "plannedCloseAt": o.planned_close_at.isoformat() if o.planned_close_at else None,
                "closedAt": o.closed_at.isoformat() if o.closed_at else None,
                "amountRub": o.amount_rub,
                "monthlyPaymentRub": o.monthly_payment_rub,
                "secured": o.secured,
            }
        )
    return body


def report_idempotency_key(application_ref: str, subject_inn: str) -> str:
    """`bki-report:{заявка}:{ИНН субъекта}`: из бизнес-данных, не случайный (50-08)."""
    return f"bki-report:{application_ref}:{subject_inn}"


def submission_idempotency_key(application_ref: str, event_type: BureauEventType) -> str:
    return f"sub:{application_ref}:{event_type.value}"


def check_consent(consent: BkiConsent, subject: BureauSubject, purpose: str) -> str | None:
    """Те же проверки, что делает БКИ (6.1), но до сети: код отказа или `None`.

    Просроченное согласие не должно стоить платного запроса и таймаута.
    """
    if consent.subject_inn != subject.inn:
        return "CONSENT_SUBJECT_MISMATCH"
    if consent.signed_at > clock.now() + CONSENT_CLOCK_SKEW:
        return "CONSENT_NOT_YET_VALID"
    if consent.valid_until < clock.today():
        return "CONSENT_EXPIRED"
    if consent.purpose != purpose:
        return "CONSENT_PURPOSE_MISMATCH"
    return None


# --- порт ----------------------------------------------------------------------------------------


class CreditBureauAdapter:
    def __init__(self, client: IntegrationClient) -> None:
        self._client = client

    def request_report(
        self,
        consent: BkiConsent,
        subject: BureauSubject,
        application_ref: str,
        *,
        purpose: str = "LOAN_APPLICATION",
        application_id: UUID | None = None,
    ) -> Result[CreditHistory]:
        """Платный отчёт по субъекту. Без действующего согласия в сеть не ходим.

        Отказ по согласию — `SourceUnavailable(REJECTED, error_code="CONSENT_EXPIRED" | …)`.
        Один повтор после `503` или обрыва с тем же ключом: БКИ вернёт тот же отчёт
        (`SnapshotMeta.replayed`), второго следа в истории запросов не будет.
        """
        refusal = check_consent(consent, subject, purpose)
        if refusal is not None:
            log.warning(
                "bki_report_consent_refused",
                code=refusal,
                subject=mask_inn(subject.inn),
                application_ref=application_ref,
            )
            return SourceUnavailable(
                System.CREDIT_BUREAU,
                Reason.REJECTED,
                error_code=refusal,
                resource="credit_bureau:report",
            )
        return self._client.call(
            policy=BUREAU_REPORT,
            method="POST",
            path="/api/v1/credit-reports",
            json_body={
                "subject": _subject_body(subject),
                "consent": _consent_body(consent),
                "purpose": purpose,
                "applicationRef": application_ref,
            },
            idempotency_key=report_idempotency_key(application_ref, subject.inn),
            parse=map_report,
            subject_inn=subject.inn,
            application_id=application_id,
            resource="credit_bureau:report",
        )

    def submit_event(
        self,
        event: BureauEvent,
        *,
        idempotency_key: str | None = None,
        application_id: UUID | None = None,
    ) -> Result[SubmissionReceipt]:
        """Передать сведения банка в БКИ (вызывает outbox, заявку не задерживает).

        Повторы делает outbox с тем же `event_id` и ключом; внутри вызова только ожидание
        `409 IDEMPOTENCY_IN_PROGRESS`. Ключ по умолчанию: `sub:{заявка}:{тип события}`.
        """
        key = idempotency_key
        if key is None:
            ref = event.application.ref if event.application else None
            if ref is None:
                raise ValueError("Для ключа идемпотентности нужна заявка или явный ключ")
            key = submission_idempotency_key(ref, event.event_type)
        return self._client.call(
            policy=BUREAU_SUBMIT,
            method="POST",
            path="/api/v1/submissions",
            json_body=_event_body(event),
            idempotency_key=key,
            parse=map_receipt,
            subject_inn=event.subject.inn,
            application_id=application_id,
            resource="credit_bureau:submission",
        )
