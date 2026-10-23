"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared.resets import (
    Persona,
    delete_owned,
    owned_ids,
    register_persona_reset,
    register_reset,
    truncate,
)

TABLES = (
    "applications",
    "application_versions",
    "application_events",
    "consents",
    "tasks",
)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("applications", reset_demo_data)


def prepare_persona(session: Session, scope: Persona) -> None:
    scope.add(
        "applications",
        owned_ids(session, "applications", "applications", "company_id", [scope.company_id]),
    )


def reset_persona(session: Session, scope: Persona) -> None:
    for table in ("tasks", "consents", "application_events", "application_versions"):
        delete_owned(session, "applications", table, "application_id", scope.ids("applications"))
    delete_owned(session, "applications", "applications", "id", scope.ids("applications"))


register_persona_reset(
    "applications", reset_persona, priority=90, prepare=prepare_persona, prepare_priority=0
)
