"""Public document operations. Authenticated access is explicit; no upper-module imports."""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.storage import PostgresFileStore
from app.modules.documents.validation import PDF_LIMIT, clean_filename, validate_content
from app.shared import clock
from app.shared.errors import AppError, not_found
from app.shared.settings import get_settings


@dataclass(frozen=True)
class Access:
    user_id: UUID
    company_ids: tuple[UUID, ...] = ()
    bank: bool = False


@dataclass(frozen=True)
class UploadContext:
    company_id: UUID
    application_id: UUID
    task_id: UUID | None = None


def get_metadata(session: Session, access: Access, document_id: UUID) -> Document:
    query = select(Document).where(Document.id == document_id)
    if not access.bank:
        query = query.where(Document.company_id.in_(access.company_ids))
    row = session.scalar(query)
    if row is None:
        raise not_found("Документ")
    return row


def list_metadata(session: Session, access: Access, application_id: UUID) -> list[Document]:
    query = select(Document).where(Document.application_id == application_id)
    if not access.bank:
        query = query.where(Document.company_id.in_(access.company_ids))
    return list(session.scalars(query.order_by(Document.created_at, Document.id)))


def verified_content(session: Session, access: Access, document_id: UUID) -> tuple[Document, bytes]:
    """Use the stored original and verify its digest, including before any future signing."""
    row = get_metadata(session, access, document_id)
    content = PostgresFileStore(session).get(row.storage_key)
    if len(content) != row.size_bytes or not hmac.compare_digest(
        hashlib.sha256(content).hexdigest(), row.sha256
    ):
        raise AppError(500, "DOCUMENT_INTEGRITY_ERROR", "Не удалось проверить целостность файла")
    return row, content


def store(
    session: Session,
    access: Access,
    context: UploadContext,
    *,
    content: bytes,
    filename: str,
    kind: str,
    origin: str = "UPLOADED",
    replaces_id: UUID | None = None,
) -> Document:
    """Called after applications locks and authorizes the upload context (one transaction).

    Counts include replaced files: originals remain stored for the audit and consume quota.
    Only the same task/kind can be replaced; failed validation never cancels the old file.
    """
    if access.bank or context.company_id not in access.company_ids:
        raise not_found("Заявка")
    if origin not in {"UPLOADED", "DEMO_GENERATED"}:
        raise AppError(422, "VALIDATION_ERROR", "Неверное происхождение загрузки")
    settings = get_settings()
    mime, digest = validate_content(
        content, kind, min(PDF_LIMIT, settings.upload_max_mb * 1024 * 1024)
    )
    count, size = session.execute(
        select(func.count(Document.id), func.coalesce(func.sum(Document.size_bytes), 0)).where(
            Document.application_id == context.application_id
        )
    ).one()
    if count >= settings.upload_max_files_per_application:
        raise AppError(422, "TOO_MANY_FILES", "На заявку можно загрузить не больше 10 файлов")
    if size + len(content) > 50 * 1024 * 1024:
        raise AppError(413, "APPLICATION_FILES_TOO_LARGE", "Общий размер файлов больше 50 МБ")
    if replaces_id is not None:
        old = get_metadata(session, access, replaces_id)
        if (
            old.application_id != context.application_id
            or old.task_id != context.task_id
            or old.kind != kind
            or old.cancelled_at is not None
        ):
            raise AppError(409, "DOCUMENT_REPLACEMENT_CONFLICT", "Этот файл нельзя заменить")
        old.cancelled_at = clock.now()
    row = Document(
        company_id=context.company_id,
        application_id=context.application_id,
        task_id=context.task_id,
        storage_key=PostgresFileStore(session).put(content),
        kind=kind,
        origin=origin,
        filename=clean_filename(filename),
        mime=mime,
        size_bytes=len(content),
        sha256=digest,
        parse_status="PENDING" if kind == "BANK_STATEMENT_1C" else "NOT_REQUIRED",
        created_by=access.user_id,
    )
    session.add(row)
    session.flush()
    return row


def as_dict(row: Document) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "companyId": str(row.company_id),
        "applicationId": str(row.application_id),
        "taskId": str(row.task_id) if row.task_id else None,
        "kind": row.kind,
        "origin": row.origin,
        "filename": row.filename,
        "mime": row.mime,
        "sizeBytes": row.size_bytes,
        "sha256": row.sha256,
        "parseStatus": row.parse_status,
        "parsed": row.parsed,
        "parseError": row.parse_error,
        "createdAt": row.created_at.isoformat(),
        "cancelledAt": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "confirmedAt": row.confirmed_at.isoformat() if row.confirmed_at else None,
    }


def company_for(session: Session, document_id: UUID) -> UUID | None:
    """Scope lookup only; authorization still happens in get_metadata."""
    return session.scalar(select(Document.company_id).where(Document.id == document_id))
