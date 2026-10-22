"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared.resets import register_reset, truncate

TABLES = (
    "pipeline_runs",
    "source_snapshots",
    "decisions",
    "decision_reasons",
)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("pipeline", reset_demo_data)
