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
    "pipeline_runs",
    "source_snapshots",
    "decisions",
    "decision_reasons",
)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("pipeline", reset_demo_data)


def prepare_persona(session: Session, scope: Persona) -> None:
    scope.add(
        "decisions",
        owned_ids(session, "pipeline", "decisions", "application_id", scope.ids("applications")),
    )


def reset_persona(session: Session, scope: Persona) -> None:
    delete_owned(session, "pipeline", "decision_reasons", "decision_id", scope.ids("decisions"))
    delete_owned(session, "pipeline", "decisions", "application_id", scope.ids("applications"))
    delete_owned(
        session, "pipeline", "source_snapshots", "application_id", scope.ids("applications")
    )
    delete_owned(session, "pipeline", "pipeline_runs", "application_id", scope.ids("applications"))


register_persona_reset("pipeline", reset_persona, priority=60, prepare=prepare_persona)
