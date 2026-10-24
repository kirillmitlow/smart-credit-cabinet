"""Transactional parser operations; application authorization belongs to the caller.

The caller holds the application lock before these document locks, as upload/replacement
does. A result and its application event are committed together; duplicate deliveries
return None. Source bytes never leave this boundary or enter an exception traceback.
"""

from dataclasses import dataclass
from uuid import UUID

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.service import Access, verified_content
from app.modules.documents.statement_parser import parse_statement
from app.shared import clock
from app.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class StatementJob:
    application_id: UUID
    company_id: UUID
    task_id: UUID | None


def statement_job(session: Session, document_id: UUID) -> StatementJob | None:
    row = session.get(Document, document_id)
    if row is None or row.kind != "BANK_STATEMENT_1C" or row.cancelled_at is not None:
        return None
    return StatementJob(row.application_id, row.company_id, row.task_id)


def pending_statements(session: Session) -> list[UUID]:
    """Safety net for a failed after-commit broker push; repeated deliveries are harmless."""
    return list(
        session.scalars(
            select(Document.id)
            .where(
                Document.kind == "BANK_STATEMENT_1C",
                Document.cancelled_at.is_(None),
                Document.parse_status.in_(("PENDING", "PROCESSING")),
            )
            .order_by(Document.created_at, Document.id)
        )
    )


def process_statement(session: Session, document_id: UUID, expected_inn: str) -> Document | None:
    row = session.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if (
        row is None
        or row.cancelled_at is not None
        or row.kind != "BANK_STATEMENT_1C"
        or row.parse_status not in {"PENDING", "PROCESSING"}
    ):
        return None
    row.parse_status = "PROCESSING"
    try:
        _, content = verified_content(
            session, Access(row.created_by, (row.company_id,)), document_id
        )
        parsed = parse_statement(content, expected_inn, as_of=clock.today()).as_dict()
    except DBAPIError:
        raise  # infrastructure is retried; never turn a broken transaction into a file error
    except SoftTimeLimitExceeded:
        row.parse_status, row.parse_error = "FAILED", "PARSE_TIMEOUT"
    except AppError as exc:
        row.parse_status, row.parse_error = "FAILED", exc.code
    except Exception as exc:
        structlog.get_logger("documents").error(
            "statement_parse_failed", error_type=type(exc).__name__
        )
        row.parse_status, row.parse_error = "FAILED", "PARSE_FAILED"
    else:
        row.parse_status, row.parse_error, row.parsed = "PARSED", None, parsed
    session.flush()
    return row
