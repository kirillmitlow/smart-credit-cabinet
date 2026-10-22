"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared.resets import register_cache_prefix, register_reset, truncate

# Кэш автозаполнения (50-08): ключи `lookup:{система}:{ресурс}:{ИНН}`
LOOKUP_CACHE_PREFIX = "lookup:"
TABLES = ("integration_calls",)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("integrations", reset_demo_data)
register_cache_prefix("integrations", LOOKUP_CACHE_PREFIX)
