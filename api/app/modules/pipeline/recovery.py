"""Сторож потерянных задач и истёкших аренд (T-271): короткие транзакции, без сети в БД."""

from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.modules.applications import (
    Actor,
    Application,
    ApplicationVersion,
    Status,
    hold_operation,
    transition,
)
from app.modules.pipeline import persist, runner
from app.modules.pipeline.models import MAX_RUN_ATTEMPTS, PipelineRun
from app.modules.pipeline.policy_registry import register_current
from app.shared import clock, db
from app.shared.ids import uuid7
from app.shared.settings import get_settings
from app.shared.tasks import enqueue

log = structlog.get_logger("app.pipeline.recovery")
DISPATCH_LEASE = timedelta(seconds=30)


def reap_one(application_id: UUID) -> str:
    with hold_operation(application_id) as scope:
        if scope is None:
            return "skipped"
        with db.transaction() as session:
            application = session.scalar(
                select(Application)
                .where(Application.id == application_id)
                .with_for_update(skip_locked=True)
            )
            if (
                application is None
                or application.status not in runner.RUNNABLE
                or application.current_version_id is None
            ):
                return "skipped"
            version = session.get(ApplicationVersion, application.current_version_id)
            if version is None:
                return "skipped"
            run_id = session.scalar(
                select(PipelineRun.id)
                .where(
                    PipelineRun.application_id == application_id,
                    PipelineRun.version_id == version.id,
                )
                .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
                .limit(1)
            )
            if run_id is None:
                key = f"{version.id}:{version.reason}"
                session.execute(
                    insert(PipelineRun)
                    .values(
                        id=uuid7(),
                        application_id=application_id,
                        version_id=version.id,
                        run_key=key,
                        trigger=version.reason,
                        status="QUEUED",
                        attempts=0,
                        created_at=clock.now(),
                    )
                    .on_conflict_do_nothing(constraint="uq_pipeline_runs_run_key")
                )
                run_id = session.scalar(select(PipelineRun.id).where(PipelineRun.run_key == key))
            # Не ждём run после блокировки app: DECISION берёт run→app в другой транзакции.
            run = session.scalar(
                select(PipelineRun)
                .where(PipelineRun.id == run_id)
                .with_for_update(skip_locked=True)
            )
            now = clock.system_now()
            if (
                run is None
                or run.status not in ("QUEUED", "RUNNING")
                or (run.locked_until is not None and run.locked_until > now)
            ):
                return "skipped"
            if run.attempts >= MAX_RUN_ATTEMPTS:
                if run.policy_version_id is None:
                    run.policy_version_id = register_current(session).id
                if application.status == Status.SUBMITTED:
                    transition(session, application, Status.CHECKING, actor=Actor.SYSTEM)
                inputs, snapshots = runner.decision_input(session, run, application)
                persist.persist_decision(
                    session,
                    run,
                    inputs,
                    persist.pipeline_error_result(inputs, run.id, run.attempts),
                    policy_version_id=run.policy_version_id,
                    engine_version=get_settings().engine_version,
                    snapshot_ids=snapshots,
                )
                run.status, run.last_error = "FAILED", "PIPELINE_ERROR"
                run.lease_token, run.locked_until, run.finished_at = None, None, now
                return "manual"
            # Аренда постановки ограничивает повторы сторожа. QUEUED доступен воркеру сразу;
            # RUNNING принимает только владелец новой аренды (атомарный claim_run).
            run.status, run.lease_token = "QUEUED", None
            run.locked_until = now + DISPATCH_LEASE
            enqueue(session, "pipeline.run", application_id=str(application_id))
        return "queued"


def reap(limit: int = 100) -> dict[str, int]:
    now = clock.system_now()
    with db.transaction() as session:
        live = (
            select(PipelineRun.id)
            .where(
                PipelineRun.application_id == Application.id,
                PipelineRun.version_id == Application.current_version_id,
                PipelineRun.status.in_(("QUEUED", "RUNNING")),
                PipelineRun.locked_until > now,
            )
            .exists()
        )
        ids = session.scalars(
            select(Application.id)
            .where(
                Application.status.in_(runner.RUNNABLE),
                Application.current_version_id.is_not(None),
                ~live,
            )
            .order_by(Application.updated_at, Application.id)
            .limit(limit)
        ).all()
    counts = {"queued": 0, "manual": 0, "skipped": 0, "errors": 0}
    for application_id in ids:
        try:
            counts[reap_one(application_id)] += 1
        except Exception as exc:  # одно неисправное приложение / брокер не останавливает остальные
            log.warning(
                "pipeline_recovery_failed",
                application=str(application_id),
                error_type=type(exc).__name__,
            )
            counts["errors"] += 1
    return counts
