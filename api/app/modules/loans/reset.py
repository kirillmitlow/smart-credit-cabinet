"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared.resets import register_reset, truncate

TABLES = (
    "loans",
    "payment_schedule",
)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("loans", reset_demo_data)
