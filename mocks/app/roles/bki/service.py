"""Бизнес-логика БКИ: сборка отчёта, запись запроса, приём сведений банка (разделы 6.1–6.4).

Расчёт чисел «на сегодня» — в calc.py, здесь только чтение строк, проверка согласия и запись.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import MSK, Clock
from app.common.db import Origin
from app.common.inn import IdentifierError, validate_inn
from app.common.problems import ProblemException
from app.roles.bki import calc, models
from app.roles.bki import schemas as s
from app.roles.bki.config import BkiSettings

ILLUSTRATIVE_SCORE_MODEL = {"LEGAL_ENTITY": "SIM-B2B-1", "PERSON": "SIM-PERSON-1"}
INQUIRY_PURPOSE_DEFAULT = "LOAN_APPLICATION"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6).upper()}"


def msk_date(moment: datetime) -> date:
    return moment.astimezone(MSK).date()


def day_to_moment(day: date) -> datetime:
    """Запросы из сценариев приходят датой: ставим полдень по Москве, дата не плывёт при сдвиге."""
    return datetime.combine(day, time(12, 0), tzinfo=MSK).astimezone(UTC)


# ---------- проверки запроса ----------


def check_subject(subject: s.Subject) -> None:
    """ИНН с верной контрольной суммой (иначе 400) и тип субъекта по длине ИНН (иначе 422)."""
    try:
        validate_inn(subject.inn)
    except IdentifierError as exc:
        raise ProblemException(400, "INN_INVALID", str(exc)) from exc
    expected = s.SubjectType.LEGAL_ENTITY if len(subject.inn) == 10 else s.SubjectType.PERSON
    if subject.type != expected:
        raise ProblemException(
            422,
            "VALIDATION_ERROR",
            f"Тип {subject.type.value} не подходит к ИНН из {len(subject.inn)} цифр: "
            "у LEGAL_ENTITY 10 цифр, у PERSON 12",
            errors=[{"loc": ["body", "subject", "type"], "msg": f"Ожидается {expected.value}"}],
        )


def check_consent(
    consent: s.Consent | None, subject_inn: str, purpose: str, clock: Clock
) -> s.Consent:
    """Пять причин отказа по порядку; первая неудача — 403 со своим кодом (6.1)."""
    if consent is None:
        raise ProblemException(403, "CONSENT_MISSING", "Нет блока consent")
    if consent.subject_inn != subject_inn:
        raise ProblemException(
            403, "CONSENT_SUBJECT_MISMATCH", "Согласие дано другим субъектом (consent.subjectInn)"
        )
    if clock.is_in_future(consent.signed_at):
        raise ProblemException(
            403,
            "CONSENT_NOT_YET_VALID",
            f"Согласие подписано в будущем ({consent.signed_at.isoformat()}); допуск часов 5 минут",
        )
    if consent.valid_until < clock.today():
        raise ProblemException(
            403, "CONSENT_EXPIRED", f"Срок действия согласия истёк {consent.valid_until}"
        )
    if consent.purpose != purpose:
        raise ProblemException(
            403,
            "CONSENT_PURPOSE_MISMATCH",
            f"Согласие дано для цели {consent.purpose}, запрошена {purpose}",
        )
    return consent


# ---------- строки → факты и схемы ----------


def periods_of(row: models.Obligation) -> list[calc.Period]:
    return [
        calc.Period(
            date.fromisoformat(p["since"]),
            date.fromisoformat(p["until"]) if p.get("until") else None,
        )
        for p in row.overdue_periods or []
    ]


def facts_of(row: models.Obligation) -> calc.ObligationFacts:
    return calc.ObligationFacts(
        kind=row.kind,
        role=row.role,
        status=row.status,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        balance_rub=row.balance_rub,
        monthly_payment_rub=row.monthly_payment_rub,
        overdue_rub=row.overdue_rub,
        periods=periods_of(row),
    )


def subject_schema(row: models.Subject) -> s.Subject:
    return s.Subject(
        type=s.SubjectType(row.type),
        inn=row.inn,
        ogrn=row.ogrn,
        name=row.name,
        last_name=row.last_name,
        first_name=row.first_name,
        middle_name=row.middle_name,
        birth_date=row.birth_date,
    )


def report_obligation(
    row: models.Obligation, today: date, settings: BkiSettings
) -> s.ReportObligation:
    periods = periods_of(row)
    if row.payment_history_fixed is not None:
        history = [s.PaymentMonth.model_validate(m) for m in row.payment_history_fixed]
    else:
        history = [
            s.PaymentMonth(month=month, status=s.PaymentStatus(status))
            for month, status in calc.payment_history(row.opened_at, row.closed_at, periods, today)
        ]
    return s.ReportObligation(
        uid=row.uid,
        kind=s.ObligationKind(row.kind),
        role=s.ObligationRole(row.role),
        opened_at=row.opened_at,
        planned_close_at=row.planned_close_at,
        closed_at=row.closed_at,
        amount_rub=row.amount_rub,
        limit_rub=row.limit_rub,
        balance_rub=row.balance_rub,
        monthly_payment_rub=calc.effective_monthly_payment(
            row.kind, row.monthly_payment_rub, row.balance_rub, settings.bki_limit_payment_percent
        ),
        overdue_rub=row.overdue_rub,
        overdue_days=calc.overdue_days_at(periods, today, row.closed_at),
        status=s.ObligationStatus(row.status),
        secured=row.secured,
        payment_history=history,
    )


def summary_schema(summary: calc.Summary) -> s.ReportSummary:
    return s.ReportSummary(
        active_obligations=summary.active_obligations,
        closed_obligations=summary.closed_obligations,
        total_debt_rub=summary.total_debt_rub,
        monthly_payments_rub=summary.monthly_payments_rub,
        contingent_liabilities_rub=summary.contingent_liabilities_rub,
        current_overdue_rub=summary.current_overdue_rub,
        current_overdue_days=summary.current_overdue_days,
        max_overdue_days24m=summary.max_overdue_days_24m,
        restructurings24m=summary.restructurings_24m,
        inquiries30d=summary.inquiries_30d,
        inquiries30d_excluding_own=summary.inquiries_30d_excluding_own,
        rejected_applications90d=summary.rejected_applications_90d,
        rejected_applications90d_excluding_own=summary.rejected_applications_90d_excluding_own,
        history_length_months=summary.history_length_months,
    )


@dataclass
class SubjectRecords:
    subject: models.Subject | None
    obligations: list[models.Obligation]
    inquiries: list[models.Inquiry]
    applications: list[models.ApplicationInfo]
    bankruptcies: list[models.Bankruptcy]


async def find_subject(session: AsyncSession, inn: str) -> models.Subject | None:
    return await session.scalar(sa.select(models.Subject).where(models.Subject.inn == inn))


async def load_records(session: AsyncSession, inn: str) -> SubjectRecords:
    """Всё о субъекте. Запросы читаются по ИНН: след, оставленный до появления субъекта, виден."""
    subject = await find_subject(session, inn)
    inquiries = list(
        await session.scalars(
            sa.select(models.Inquiry)
            .where(models.Inquiry.inn == inn)
            .order_by(models.Inquiry.inquired_at.desc(), models.Inquiry.id.desc())
        )
    )
    if subject is None:
        return SubjectRecords(None, [], inquiries, [], [])
    sid = subject.id
    obligations = await session.scalars(
        sa.select(models.Obligation)
        .where(models.Obligation.subject_id == sid)
        .order_by(models.Obligation.opened_at, models.Obligation.id)
    )
    applications = await session.scalars(
        sa.select(models.ApplicationInfo)
        .where(models.ApplicationInfo.subject_id == sid)
        .order_by(models.ApplicationInfo.applied_at.desc(), models.ApplicationInfo.id.desc())
    )
    bankruptcies = await session.scalars(
        sa.select(models.Bankruptcy)
        .where(models.Bankruptcy.subject_id == sid)
        .order_by(models.Bankruptcy.started_at, models.Bankruptcy.id)
    )
    return SubjectRecords(
        subject, list(obligations), inquiries, list(applications), list(bankruptcies)
    )


def build_report(
    *,
    report_id: str,
    generated_at: datetime,
    today: date,
    records: SubjectRecords,
    requested: s.Subject,
    settings: BkiSettings,
) -> s.CreditReportBody:
    """Отчёт на «сегодня». Для субъекта, которого нет, — NOT_FOUND с нулями (6.1)."""
    if records.subject is None:
        return s.CreditReportBody(
            report_id=report_id,
            generated_at=generated_at,
            match_status=s.MatchStatus.NOT_FOUND,
            subject=requested,
            has_history=False,
            summary=summary_schema(calc.ZERO_SUMMARY),
            obligations=[],
            inquiries=[],
            applications=[],
            bankruptcies=[],
            bureau_score=None,
        )

    summary = calc.summarize(
        [facts_of(o) for o in records.obligations],
        [calc.InquiryFacts(msk_date(i.inquired_at), i.is_own) for i in records.inquiries],
        [
            calc.ApplicationFacts(a.applied_at, a.decided_at, a.decision, a.is_own)
            for a in records.applications
        ],
        today,
        settings.bki_limit_payment_percent,
    )
    has_history = bool(records.obligations)
    open_case = any(b.stage != s.BankruptcyStage.COMPLETED for b in records.bankruptcies)
    subject = subject_schema(records.subject)
    return s.CreditReportBody(
        report_id=report_id,
        generated_at=generated_at,
        match_status=s.MatchStatus.MATCHED,
        subject=subject,
        has_history=has_history,
        summary=summary_schema(summary),
        obligations=[report_obligation(o, today, settings) for o in records.obligations],
        inquiries=[
            s.ReportInquiry(
                date=msk_date(i.inquired_at),
                user_type=s.UserType(i.user_type),
                purpose=i.purpose,
                is_own=i.is_own,
            )
            for i in records.inquiries
        ],
        applications=[
            s.ReportApplication(
                date=a.applied_at,
                kind=a.kind,
                amount_rub=a.amount_rub,
                decision=s.ApplicationDecision(a.decision),
                decision_date=a.decided_at,
                is_own=a.is_own,
            )
            for a in records.applications
        ],
        bankruptcies=[
            s.ReportBankruptcy(
                case_number=b.case_number,
                stage=s.BankruptcyStage(b.stage),
                started_at=b.started_at,
                completed_at=b.completed_at,
            )
            for b in records.bankruptcies
        ],
        # Оценка — иллюстрация: без истории бюро её не считает
        bureau_score=(
            s.BureauScore(
                value=calc.bureau_score(summary, open_case),
                scale_min=300,
                scale_max=850,
                model=ILLUSTRATIVE_SCORE_MODEL[subject.type.value],
            )
            if has_history
            else None
        ),
    )


async def issue_report(
    session: AsyncSession,
    request: s.CreditReportRequest,
    consent: s.Consent,
    *,
    clock: Clock,
    settings: BkiSettings,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Записать наш запрос в историю, собрать отчёт и сохранить его снимок. Возвращает снимок."""
    inn = request.subject.inn
    now = clock.now().replace(microsecond=0)
    subject = await find_subject(session, inn)

    # Запрос пишется всегда, в том числе при NOT_FOUND, и входит в отчёт (6.1)
    inquiry = models.Inquiry(
        inn=inn,
        subject_id=subject.id if subject else None,
        inquired_at=now,
        user_name=settings.bki_own_user_name,
        user_type=s.UserType.BANK.value,
        purpose=request.purpose,
        is_own=True,
        origin=Origin.RUNTIME.value,
        scenario_code=subject.scenario_code if subject else None,
    )
    session.add(inquiry)
    await session.flush()

    report_id = new_id("rep")
    records = await load_records(session, inn)
    body = build_report(
        report_id=report_id,
        generated_at=now,
        today=clock.today(),
        records=records,
        requested=request.subject,
        settings=settings,
    )
    snapshot = body.model_dump(mode="json", by_alias=True)
    session.add(
        models.Report(
            id=report_id,
            inn=inn,
            subject_id=subject.id if subject else None,
            generated_at=now,
            purpose=request.purpose,
            application_ref=request.application_ref,
            idempotency_key=idempotency_key,
            consent=consent.model_dump(mode="json", by_alias=True),
            response=snapshot,
        )
    )
    await session.flush()
    inquiry.report_id = report_id
    await session.commit()
    return snapshot


# ---------- submissions ----------


async def ensure_subject(session: AsyncSession, subject: s.Subject) -> models.Subject:
    """Субъект по ИНН; если в БКИ его не было, создаётся (RUNTIME). Гонка безопасна."""
    await session.execute(
        pg_insert(models.Subject)
        .values(
            type=subject.type.value,
            inn=subject.inn,
            ogrn=subject.ogrn,
            name=subject.name,
            last_name=subject.last_name,
            first_name=subject.first_name,
            middle_name=subject.middle_name,
            birth_date=subject.birth_date,
            origin=Origin.RUNTIME.value,
            scenario_code=None,
        )
        .on_conflict_do_nothing(index_elements=["inn"])
    )
    found = await find_subject(session, subject.inn)
    if found is None:  # только что вставлен или уже был: сюда не попадаем
        raise RuntimeError(f"Субъект {subject.inn} не найден после вставки")
    await session.execute(
        sa.update(models.Inquiry)
        .where(models.Inquiry.inn == found.inn, models.Inquiry.subject_id.is_(None))
        .values(subject_id=found.id)
    )
    return found


def application_not_found(ref: str) -> ProblemException:
    return ProblemException(404, "APPLICATION_NOT_FOUND", f"Заявка {ref} не зарегистрирована в БКИ")


async def apply_event(session: AsyncSession, event: s.SubmissionEvent) -> None:
    occurred = msk_date(event.occurred_at)
    if isinstance(event, s.ApplicationRegistered):
        subject = await ensure_subject(session, event.subject)
        app = event.application
        await session.execute(
            pg_insert(models.ApplicationInfo)
            .values(
                subject_id=subject.id,
                application_ref=app.ref,
                applied_at=occurred,
                kind=app.kind,
                amount_rub=app.amount_rub,
                decision=s.ApplicationDecision.PENDING.value,
                decided_at=None,
                is_own=True,
                origin=Origin.RUNTIME.value,
                scenario_code=subject.scenario_code,
            )
            .on_conflict_do_nothing(constraint="uq_application_ref")
        )
    elif isinstance(event, s.ApplicationDecided):
        known = await find_subject(session, event.subject.inn)
        application = (
            await session.scalar(
                sa.select(models.ApplicationInfo).where(
                    models.ApplicationInfo.subject_id == known.id,
                    models.ApplicationInfo.application_ref == event.application.ref,
                )
            )
            if known
            else None
        )
        if application is None:
            raise application_not_found(event.application.ref)
        # После APPROVED разрешён отдельный WITHDRAWN (отказ до подписи): решение просто заменяется
        application.decision = event.application.decision.value
        application.decided_at = occurred
    elif isinstance(event, s.ObligationOpened):
        subject = await ensure_subject(session, event.subject)
        o = event.obligation
        balance = o.balance_rub if o.balance_rub is not None else (o.amount_rub or 0)
        await session.execute(
            pg_insert(models.Obligation)
            .values(
                subject_id=subject.id,
                uid=o.uid,
                kind=o.kind.value,
                role=o.role.value,
                opened_at=o.opened_at,
                planned_close_at=o.planned_close_at,
                closed_at=None,
                amount_rub=o.amount_rub,
                limit_rub=o.limit_rub,
                balance_rub=balance,
                monthly_payment_rub=o.monthly_payment_rub,
                overdue_rub=0,
                overdue_periods=[],
                status=s.ObligationStatus.ACTIVE.value,
                secured=o.secured,
                payment_history_fixed=None,
                origin=Origin.RUNTIME.value,
                scenario_code=subject.scenario_code,
            )
            .on_conflict_do_nothing(index_elements=["uid"])  # тот же uid второй раз не создаётся
        )
    else:
        known = await find_subject(session, event.subject.inn)
        obligation = (
            await session.scalar(
                sa.select(models.Obligation).where(
                    models.Obligation.subject_id == known.id,
                    models.Obligation.uid == event.obligation.uid,
                )
            )
            if known
            else None
        )
        if obligation is None:
            raise ProblemException(
                404, "OBLIGATION_NOT_FOUND", f"Обязательство {event.obligation.uid} не найдено"
            )
        obligation.status = s.ObligationStatus.CLOSED.value
        obligation.closed_at = event.obligation.closed_at
        obligation.balance_rub = 0


async def accept_submission(
    session: AsyncSession,
    event: s.SubmissionEvent,
    raw: dict[str, Any],
    clock: Clock,
) -> str:
    """Принять событие банка и вернуть submissionId.

    Повтор того же eventId (в том числе с другим Idempotency-Key) возвращает исходный submissionId,
    не применяя событие второй раз; другое тело при том же eventId — 409 (раздел 2.7).
    """
    submission_id = new_id("sub")
    inserted = await session.scalar(
        pg_insert(models.Submission)
        .values(
            id=submission_id,
            event_id=event.event_id,
            event_type=event.event_type,
            inn=event.subject.inn,
            payload=raw,
            received_at=clock.now(),
            status="ACCEPTED",
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(models.Submission.id)
    )
    if inserted is None:
        existing = await session.scalar(
            sa.select(models.Submission).where(models.Submission.event_id == event.event_id)
        )
        if existing is None:  # строка с этим eventId была и исчезла: сюда не попадаем
            raise RuntimeError(f"Событие {event.event_id} пропало во время приёма")
        if existing.payload != raw:
            raise ProblemException(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                f"eventId {event.event_id} уже принят с другим телом события",
            )
        return existing.id

    await apply_event(session, event)
    await session.commit()
    return submission_id


async def purge_subject_records(session: AsyncSession, inns: list[str]) -> None:
    """Удалить всё по ИНН: субъекта и его записи, запросы, отчёты и сведения банка (включая RUNTIME)."""
    if not inns:
        return
    subject_ids = sa.select(models.Subject.id).where(models.Subject.inn.in_(inns))
    for model in (models.Obligation, models.ApplicationInfo, models.Bankruptcy):
        await session.execute(sa.delete(model).where(model.subject_id.in_(subject_ids)))
    await session.execute(sa.delete(models.Inquiry).where(models.Inquiry.inn.in_(inns)))
    await session.execute(sa.delete(models.Report).where(models.Report.inn.in_(inns)))
    await session.execute(sa.delete(models.Submission).where(models.Submission.inn.in_(inns)))
    await session.execute(sa.delete(models.Subject).where(models.Subject.inn.in_(inns)))
