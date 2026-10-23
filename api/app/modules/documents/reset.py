"""Original bytes and metadata belong to documents, and are removed before tasks/applications."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.shared.resets import (
    Persona,
    delete_owned,
    register_persona_reset,
    register_reset,
    truncate,
)


def reset_all(session: Session) -> None:
    truncate(session, "documents", "document_blobs")


def prepare(session: Session, scope: Persona) -> None:
    rows = session.execute(
        select(Document.id, Document.storage_key).where(Document.company_id == scope.company_id)
    ).all()
    scope.add("documents", [row.id for row in rows])
    scope.add("document_blobs", [row.storage_key for row in rows])


def reset_one(session: Session, scope: Persona) -> None:
    delete_owned(session, "documents", "documents", "company_id", [scope.company_id])
    delete_owned(session, "documents", "document_blobs", "id", scope.ids("document_blobs"))


register_reset("documents", reset_all)
register_persona_reset("documents", reset_one, priority=45, prepare=prepare)
