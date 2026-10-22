"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared import cache
from app.shared.resets import (
    Persona,
    delete_owned,
    register_cache_prefix,
    register_persona_reset,
    register_reset,
    truncate,
)

# Кэш автозаполнения (50-08): ключи `lookup:{система}:{ресурс}:{ИНН}`
LOOKUP_CACHE_PREFIX = "lookup:"
TABLES = ("integration_calls",)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("integrations", reset_demo_data)
register_cache_prefix("integrations", LOOKUP_CACHE_PREFIX)


def reset_persona(session: Session, scope: Persona) -> None:
    delete_owned(
        session, "integrations", "integration_calls", "application_id", scope.ids("applications")
    )


def reset_persona_cache(scope: Persona) -> None:
    client = cache.get_redis()
    keys = list(client.scan_iter(match=f"{LOOKUP_CACHE_PREFIX}*:{scope.inn}", count=500))
    if keys:
        client.unlink(*keys)


register_persona_reset("integrations", reset_persona, priority=80, cache=reset_persona_cache)
