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
    "loans",
    "payment_schedule",
)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("loans", reset_demo_data)


def prepare_persona(session: Session, scope: Persona) -> None:
    scope.add("loans", owned_ids(session, "loans", "loans", "company_id", [scope.company_id]))


def reset_persona(session: Session, scope: Persona) -> None:
    delete_owned(session, "loans", "payment_schedule", "loan_id", scope.ids("loans"))
    delete_owned(session, "loans", "loans", "company_id", [scope.company_id])


register_persona_reset("loans", reset_persona, priority=10, prepare=prepare_persona)
