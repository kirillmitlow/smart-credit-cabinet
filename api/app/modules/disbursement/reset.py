"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared.resets import (
    Persona,
    delete_owned,
    register_persona_reset,
    register_reset,
    truncate,
)

TABLES = ("disbursements",)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("disbursement", reset_demo_data)


def reset_persona(session: Session, scope: Persona) -> None:
    delete_owned(session, "disbursement", "disbursements", "company_id", [scope.company_id])


register_persona_reset("disbursement", reset_persona, priority=20)
