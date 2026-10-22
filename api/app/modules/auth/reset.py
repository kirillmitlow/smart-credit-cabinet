"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.modules.auth import codes, sessions
from app.shared.cache import get_redis
from app.shared.resets import (
    Persona,
    register_cache_prefix,
    register_persona_reset,
    register_reset,
    truncate,
)

TABLES = ("users",)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("auth", reset_demo_data)
register_cache_prefix("auth", sessions.KEY_PREFIX)
register_cache_prefix("auth", codes.KEY_PREFIX)


def reset_persona_cache(scope: Persona) -> None:
    client = get_redis()
    resources = scope.journal_ids()
    for key in client.scan_iter(match=codes.KEY_PREFIX + "*", count=500):
        raw = client.get(key)
        try:
            record = json.loads(str(raw))
            subject = str(record.get("subject", "")) if isinstance(record, dict) else ""
        except ValueError:
            continue
        company_matches = isinstance(record, dict) and record.get("company_id") == str(
            scope.company_id
        )
        if company_matches or any(resource in subject for resource in resources):
            client.unlink(key)


# Пользователь и сессия могут одновременно участвовать в другой компании.
# Учётки/участников исходного сценария восстанавливает companies.apply_scenario.
register_persona_reset("auth", lambda session, scope: None, priority=110, cache=reset_persona_cache)
