"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditRecord
from app.shared.resets import Persona, register_persona_reset, register_reset, truncate

TABLES = ("audit_log",)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("audit", reset_demo_data)


def reset_persona(session: Session, scope: Persona) -> None:
    session.execute(
        delete(AuditRecord).where(
            or_(
                AuditRecord.company_id == scope.company_id,
                AuditRecord.object_id.in_(scope.journal_ids()),
                (AuditRecord.object_type == "outbox")
                & AuditRecord.object_id.in_(scope.keys("outbox")),
            )
        )
    )


register_persona_reset("audit", reset_persona, priority=1)
