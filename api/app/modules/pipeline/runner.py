"""Конвейер заявки: запуск, аренда, контрольные точки, шаги (T-270, 50-05, 30-01).

Один запуск на версию заявки (`pipeline_runs.run_key`). Шаги идут по порядку; результат каждого
шага и его контрольная точка пишутся одной транзакцией, поэтому повтор после обрыва продолжает
с последнего сохранённого шага, а выполненные шаги пропускает. Сеть вызывается вне транзакции.
Аренда (`lease_token` + `locked_until`) не даёт двум воркерам работать над одним запуском: второй
тихо выходит. Бизнес-сбой источника — не исключение (`SourceUnavailable` → флаг в ядре).
Исключения инфраструктуры (БД, Redis) пролетают наверх: их повторяет задача Celery.

Шаги (нумерация 30-01 / 50-05): COMPLETENESS (1), SOURCES (2), BUREAU (3–4), DECISION (5–6).
Расчёт целиком в `decisioning`; здесь нет формул.

TODO(T-271): сторож `pipeline.reaper` — перепостановка запусков с истёкшей арендой, лимит 5
перезапусков. TODO(T-277): повторные запуски по `INFO_PROVIDED` / `COLLATERAL_ADDED` и пометка
«правила обновлены». TODO(T-278): outbox в шаге DECISION (см. `hooks.after_decision`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules import companies
from app.modules.applications import (
    Actor,
    Application,
    ApplicationVersion,
    Status,
    record_event,
    transition,
)
from app.modules.decisioning import DecisionInput, decide
from app.modules.decisioning.types import Context, Product
from app.modules.integrations import Integrations, get_integrations
from app.modules.pipeline import bureau, facts, persist, sources
from app.modules.pipeline.consents import CONSENT_LABELS, load_bki_consents, valid_consent
from app.modules.pipeline.models import PipelineRun
from app.modules.pipeline.policy_registry import policy_by_id, register_current
from app.modules.pipeline.snapshots import (
    Collected,
    load_records,
    save_snapshots,
    save_statement_snapshot,
)
from app.shared import clock, db
from app.shared.errors import AppError
from app.shared.ids import uuid7
from app.shared.settings import get_settings

log = structlog.get_logger("app.pipeline")

# Жёсткий лимит задачи 90 с (50-05); аренда с запасом, продлевается на каждой контрольной точке
LEASE = timedelta(seconds=120)
STEPS = ("COMPLETENESS", "SOURCES", "BUREAU", "DECISION")
RUNNABLE = (Status.SUBMITTED, Status.CHECKING)


class RunResult(StrEnum):
    DONE = "DONE"  # запуск завершён этим вызовом
    SKIPPED = "SKIPPED"  # уже выполнен, чужая аренда или заявка не в обработке
    LEASE_LOST = "LEASE_LOST"  # аренду перехватили: уходим молча
    ABANDONED = "ABANDONED"  # заявка изменилась посреди запуска (например, отозвана)


class LeaseLostError(Exception):
    pass


class _Abandoned(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Claimed:
    run_id: UUID
    token: UUID
    application_id: UUID
    done_step: str | None
    policy_version_id: UUID


@dataclass(frozen=True, slots=True)
class Info:
    """Что нужно шагам от заявки; читается заново в каждой транзакции."""

    number: str
    applicant_inn: str
    product: Product
    version_data: dict[str, Any]


# ---------------------------------------------------------------- аренда и контрольные точки


def claim_run(application_id: UUID) -> Claimed | None:
    """Создать запуск (если нет) и взять аренду. `None` — делать нечего или занято."""
    now = clock.system_now()
    with db.transaction() as session:
        application = session.get(Application, application_id)
        if (
            application is None
            or application.current_version_id is None
            or Status(application.status) not in RUNNABLE
        ):
            return None
        version = session.get(ApplicationVersion, application.current_version_id)
        if version is None:
            return None
        # Перепроверка (`recheck.request_recheck`) заранее кладёт запуск с собственным ключом
        pending = session.scalars(
            select(PipelineRun)
            .where(
                PipelineRun.application_id == application.id,
                PipelineRun.status.in_(("QUEUED", "RUNNING")),
            )
            .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
            .limit(1)
        ).first()
        run_key = pending.run_key if pending is not None else f"{version.id}:{version.reason}"
        session.execute(
            insert(PipelineRun)
            .values(
                id=uuid7(),
                application_id=application.id,
                version_id=version.id,
                run_key=run_key,
                trigger=version.reason,
                status="QUEUED",
                attempts=0,
                created_at=clock.now(),
            )
            .on_conflict_do_nothing(constraint="uq_pipeline_runs_run_key")
        )
        token = uuid7()
        row = session.execute(
            update(PipelineRun)
            .where(
                PipelineRun.run_key == run_key,
                PipelineRun.status.in_(("QUEUED", "RUNNING")),
                or_(PipelineRun.locked_until.is_(None), PipelineRun.locked_until < now),
            )
            .values(
                status="RUNNING",
                lease_token=token,
                locked_until=now + LEASE,
                attempts=PipelineRun.attempts + 1,
                started_at=func.coalesce(PipelineRun.started_at, now),
            )
            .returning(PipelineRun.id, PipelineRun.current_step, PipelineRun.policy_version_id)
        ).first()
        if row is None:
            return None
        policy_version_id = row.policy_version_id
        if policy_version_id is None:
            # Версия правил фиксируется на старте запуска и не меняется до его конца (30-13)
            policy_version_id = register_current(session).id
            session.execute(
                update(PipelineRun)
                .where(PipelineRun.id == row.id)
                .values(policy_version_id=policy_version_id)
            )
        return Claimed(row.id, token, application.id, row.current_step, policy_version_id)


def _checkpoint(session: Session, claim: Claimed, step: str | None, **values: Any) -> None:
    """Продлить аренду и (если задан шаг) сохранить контрольную точку; чужая аренда — выход."""
    changes: dict[str, Any] = {"locked_until": clock.system_now() + LEASE, **values}
    if step is not None:
        changes["current_step"] = step
    result = session.execute(
        update(PipelineRun)
        .where(PipelineRun.id == claim.run_id, PipelineRun.lease_token == claim.token)
        .values(**changes)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise LeaseLostError(str(claim.run_id))


def _done(claim: Claimed, step: str) -> bool:
    if claim.done_step is None:
        return False
    return STEPS.index(step) <= STEPS.index(claim.done_step)


def _application(session: Session, claim: Claimed) -> Application:
    application = session.get(Application, claim.application_id)
    if application is None:
        raise _Abandoned("заявка удалена")
    return application


def _run(session: Session, claim: Claimed) -> PipelineRun:
    run = session.get(PipelineRun, claim.run_id)
    if run is None:
        raise _Abandoned("запуск удалён")
    return run


def _info(session: Session, claim: Claimed) -> Info:
    application = _application(session, claim)
    run = _run(session, claim)
    version = session.get(ApplicationVersion, run.version_id)
    company = companies.by_id(session, application.company_id)
    if version is None or company is None:
        raise _Abandoned("нет версии заявки или компании")
    data: dict[str, Any] = version.data
    product = data.get("productCode") or application.product_code or Product.EXPRESS.value
    return Info(application.number, company.inn, Product(product), data)


def _event(session: Session, claim: Claimed, step: str, payload: dict[str, Any]) -> None:
    application = _application(session, claim)
    record_event(
        session,
        application,
        "STEP",
        actor_type=Actor.SYSTEM,
        step_code=step,
        payload={"runId": str(claim.run_id), **payload},
    )


# ---------------------------------------------------------------- шаги


def step_completeness(claim: Claimed) -> None:
    """Шаг 1: заявка берётся в работу (`SUBMITTED → CHECKING`); полноту оценивает ядро."""
    with db.transaction() as session:
        _checkpoint(session, claim, "COMPLETENESS")
        application = session.scalars(
            select(Application).where(Application.id == claim.application_id).with_for_update()
        ).one()
        status = Status(application.status)
        if status == Status.SUBMITTED:
            transition(session, application, Status.CHECKING, actor=Actor.SYSTEM)
        elif status != Status.CHECKING:
            raise _Abandoned(f"статус заявки {status}")
        info = _info(session, claim)
        missing = facts.build_application(str(application.id), info.version_data).missing_fields
        _event(session, claim, "COMPLETENESS", {"missingFields": list(missing)})


def step_sources(claim: Claimed, integrations: Integrations) -> None:
    """Шаг 2: бесплатные источники параллельно, снимки «как есть»."""
    with db.transaction() as session:
        info = _info(session, claim)
    items = sources.collect_free_sources(
        integrations,
        application_id=claim.application_id,
        applicant_inn=info.applicant_inn,
        product=info.product,
    )
    with db.transaction() as session:
        _checkpoint(session, claim, "SOURCES")
        created = save_snapshots(session, claim.run_id, claim.application_id, items)
        application = session.get(Application, claim.application_id)
        if application is None:
            raise _Abandoned()
        created += save_statement_snapshot(
            session, claim.run_id, claim.application_id, application.company_id, info.applicant_inn
        )
        _event(session, claim, "SOURCES", _collected_payload(items, created))


def _collected_payload(items: list[Collected], created: int) -> dict[str, Any]:
    return {
        "collected": len(items),
        "saved": created,
        "unavailable": sorted(f"{i.resource}" for i in items if i.unavailable),
    }


def step_bureau(claim: Claimed, integrations: Integrations) -> None:
    """Шаги 3–4: субъекты, согласия, отчёты БКИ (или переиспользование отчёта заявки)."""
    with db.transaction() as session:
        info = _info(session, claim)
        records = load_records(session, claim.run_id, claim.application_id)
        subjects = _bki_subjects(info, records)
        consents = load_bki_consents(session, claim.application_id)
        plan = bureau.plan_bureau(session, claim.application_id, subjects, consents)
    items = bureau.request_reports(
        integrations,
        plan,
        application_id=claim.application_id,
        application_ref=info.number,
    )
    with db.transaction() as session:
        _checkpoint(session, claim, "BUREAU")
        created = save_snapshots(session, claim.run_id, claim.application_id, items)
        _event(
            session,
            claim,
            "BUREAU",
            {
                "requested": len(plan.to_request),
                "reused": len(plan.reused),
                "noConsent": len(plan.no_consent),
                "saved": created,
                "unavailable": sorted(i.resource for i in items if i.unavailable),
            },
        )


def _bki_subjects(info: Info, records: facts.Records) -> list[facts.Subject]:
    card_rec = records.get(facts.REGISTRY, info.applicant_inn)
    card = card_rec.data if card_rec is not None and card_rec.usable else None
    return facts.bki_subjects(info.applicant_inn, card, facts.guarantor_inn(info.version_data))


def step_decision(claim: Claimed) -> int:
    """Шаги 5–6: `decide()` и запись решения, перехода и событий одной транзакцией."""
    with db.transaction() as session:
        run = _run(session, claim)
        _checkpoint(session, claim, "DECISION")
        info = _info(session, claim)
        records = load_records(session, claim.run_id, claim.application_id)
        subjects = _bki_subjects(info, records)
        consents = load_bki_consents(session, claim.application_id)
        no_consent = bureau.inns_without_consent(records, subjects)
        unsigned = [CONSENT_LABELS[s.role.value] for s in subjects if s.inn in no_consent]
        guarantor = facts.guarantor_inn(info.version_data)
        application = facts.build_application(
            str(claim.application_id),
            info.version_data,
            unsigned_consents=unsigned,
            guarantor_consent_signed=bool(guarantor and valid_consent(consents, guarantor)),
        )
        snapshot = facts.build_snapshot(
            records,
            applicant_inn=info.applicant_inn,
            product=info.product,
            bki_no_consent=no_consent,
            bki_subject_list=subjects,
        )
        policy = policy_by_id(session, claim.policy_version_id)
        inp = DecisionInput(application, snapshot, Context(app_today=clock.today()), policy)
        result = decide(inp)
        snapshot_ids = [UUID(r.snapshot_id) for r in records.all() if r.snapshot_id]
        persist.persist_decision(
            session,
            run,
            inp,
            result,
            policy_version_id=claim.policy_version_id,
            engine_version=get_settings().engine_version,
            snapshot_ids=snapshot_ids,
        )
        _checkpoint(
            session,
            claim,
            "DECISION",
            status="DONE",
            finished_at=clock.system_now(),
            locked_until=None,
        )
        return len(snapshot_ids)


# ---------------------------------------------------------------- вход


def _abandon(claim: Claimed, reason: str) -> None:
    with db.transaction() as session:
        session.execute(
            update(PipelineRun)
            .where(PipelineRun.id == claim.run_id, PipelineRun.lease_token == claim.token)
            .values(
                status="FAILED",
                last_error=reason[:500],
                finished_at=clock.system_now(),
                locked_until=None,
            )
        )


def _run_pipeline(application_id: UUID, *, integrations: Integrations | None = None) -> RunResult:
    """Выполнить (или продолжить) конвейер заявки. Безопасно вызывать повторно и параллельно."""
    claim = claim_run(application_id)
    if claim is None:
        log.info("pipeline_skipped", application=str(application_id))
        return RunResult.SKIPPED
    ports = integrations or get_integrations()
    with structlog.contextvars.bound_contextvars(
        applicationId=str(application_id), runId=str(claim.run_id)
    ):
        try:
            if not _done(claim, "COMPLETENESS"):
                step_completeness(claim)
            if not _done(claim, "SOURCES"):
                step_sources(claim, ports)
            if not _done(claim, "BUREAU"):
                step_bureau(claim, ports)
            if not _done(claim, "DECISION"):
                step_decision(claim)
        except LeaseLostError:
            log.warning("pipeline_lease_lost")
            return RunResult.LEASE_LOST
        except _Abandoned as exc:
            _abandon(claim, str(exc))
            log.warning("pipeline_abandoned", reason=str(exc))
            return RunResult.ABANDONED
        except AppError as exc:
            if exc.code != "INVALID_TRANSITION":
                raise
            # Заявку изменили, пока шёл расчёт (отзыв клиентом): решение не сохраняем
            _abandon(claim, f"{exc.code}: {exc.detail}")
            log.warning("pipeline_abandoned", reason=exc.code)
            return RunResult.ABANDONED
    log.info("pipeline_done")
    return RunResult.DONE


def run_pipeline(application_id: UUID, *, integrations: Integrations | None = None) -> RunResult:
    from app.modules.applications import hold_operation
    from app.shared.operations import ResetInProgress

    try:
        with hold_operation(application_id) as scope:
            if scope is None:
                return RunResult.SKIPPED
            return _run_pipeline(application_id, integrations=integrations)
    except ResetInProgress:
        log.info("pipeline_reset_fenced", application=str(application_id))
        return RunResult.SKIPPED
