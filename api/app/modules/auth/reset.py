"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.auth import codes, sessions
from app.shared.resets import register_cache_prefix, register_reset, truncate

TABLES = ("users",)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("auth", reset_demo_data)
register_cache_prefix("auth", sessions.KEY_PREFIX)
register_cache_prefix("auth", codes.KEY_PREFIX)
