"""T-333 composition: one fenced transaction for a statement result and notification.

Only IDs enter Celery. The original document never enters broker payloads or logs.
Application → document row lock order matches upload/replacement/cancellation. Parsing
is bounded to 5 MiB and has no network calls; reset uses the existing company fence.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from app.modules import applications, audit, companies, documents
from app.shared import db, operations, tasks

PARSE_TASK = "documents.parse_statement"
RECOVER_TASK = "documents.recover_statements"


def run_statement(document_id: UUID) -> str:
    with db.transaction() as session:
        job = documents.statement_job(session, document_id)
    if job is None:
        return "SKIPPED"
    with applications.hold_operation(job.application_id) as scope:
        if scope is None:
            return "SKIPPED"
        with db.transaction() as session:
            application = applications.statement_processing_context(
                session, job.application_id, job.task_id
            )
            if application is None or application.company_id != job.company_id:
                return "SKIPPED"
            company = companies.by_id(session, job.company_id)
            if company is None:
                return "SKIPPED"
            row = documents.process_statement(session, document_id, company.inn)
            if row is None:
                return "ALREADY"
            step = "STATEMENT_PARSED" if row.parse_status == "PARSED" else "STATEMENT_PARSE_FAILED"
            applications.record_event(
                session,
                application,
                "STEP",
                actor_type=applications.Actor.SYSTEM,
                step_code=step,
                reason_code=row.parse_error,
                payload={
                    "documentId": str(row.id),
                    "taskId": str(row.task_id) if row.task_id else None,
                },
            )
            audit.record(
                session,
                step,
                actor_role="SYSTEM",
                object_type="document",
                object_id=str(row.id),
                company_id=row.company_id,
                details={"sha256": row.sha256, "parseError": row.parse_error},
            )
            return row.parse_status


@tasks.celery_app.task(  # type: ignore[untyped-decorator]
    name=PARSE_TASK, bind=True, max_retries=3, soft_time_limit=55, time_limit=60
)
def parse_statement_task(self: Any, document_id: str) -> str:
    try:
        return run_statement(UUID(document_id))
    except (DBAPIError, operations.ResetInProgress):
        # No exception/traceback with file bytes is sent to Celery or its result backend.
        raise self.retry(countdown=(2, 10, 30)[min(int(self.request.retries), 2)]) from None


@tasks.celery_app.task(name=RECOVER_TASK)  # type: ignore[untyped-decorator]
def recover_statements() -> int:
    with db.transaction() as session:
        pending = documents.pending_statements(session)
    count = 0
    for document_id in pending:
        with db.transaction() as session:
            job = documents.statement_job(session, document_id)
            active = (
                job is not None
                and applications.statement_processing_context(
                    session, job.application_id, job.task_id
                )
                is not None
            )
        if active:
            tasks.send_now(PARSE_TASK, document_id=str(document_id))
            count += 1
    return count
