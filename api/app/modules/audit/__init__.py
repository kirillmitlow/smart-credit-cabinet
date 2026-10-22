"""Журнал действий вне заявки: вход, роли, действия андеррайтера и демо. Документ: 50-10."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditRecord


def record(
    session: Session,
    action: str,
    *,
    actor_id: UUID | None = None,
    actor_role: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    company_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Запись в той же транзакции, что и действие (R8). Персональных данных в details не класть."""
    session.add(
        AuditRecord(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            object_type=object_type,
            object_id=object_id,
            company_id=company_id,
            details=details or {},
            request_id=structlog.contextvars.get_contextvars().get("requestId"),
        )
    )


def exists(session: Session, action: str, *, actor_id: UUID) -> bool:
    """Было ли у этого пользователя действие `action` (например, принятие правил подписи)."""
    found = session.scalar(
        select(AuditRecord.id)
        .where(AuditRecord.action == action, AuditRecord.actor_id == actor_id)
        .limit(1)
    )
    return found is not None


__all__ = ["AuditRecord", "exists", "record"]
