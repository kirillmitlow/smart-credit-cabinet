"""Реестр сброса демо (T-204, T-371): каждый модуль сам чистит свои таблицы, demo вызывает всех.

Модули регистрируют функции при импорте; demo не импортирует модули напрямую (50-04).
Вне DEMO_MODE сброс запрещён. Реестр знает три вида действий:

* `register_reset` — чистка таблиц модуля (`TRUNCATE`, см. `truncate`);
* `register_cache_prefix` — префикс ключей Valkey, которые надо удалить (сессии, кэш);
* `register_after_reset` — действие после чистки базы (например, подтянуть компании из сценариев).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.shared.errors import AppError
from app.shared.settings import get_settings

ResetFn = Callable[[Session], None]
AfterResetFn = Callable[[Session], Any]

# Порядок регистрации = порядок сброса
_registry: list[tuple[str, ResetFn]] = []
_cache_prefixes: list[tuple[str, str]] = []
_after: list[tuple[str, AfterResetFn]] = []

# Версии правил и служебная таблица миграций сбросу не подлежат: на них ссылаются решения
PROTECTED_TABLES = frozenset({"policy_versions", "alembic_version"})


def register_reset(module: str, fn: ResetFn) -> None:
    if any(name == module for name, _ in _registry):
        raise ValueError(f"Сброс модуля {module} уже зарегистрирован")
    _registry.append((module, fn))


def register_cache_prefix(module: str, prefix: str) -> None:
    if (module, prefix) in _cache_prefixes:
        raise ValueError(f"Префикс {prefix} модуля {module} уже зарегистрирован")
    _cache_prefixes.append((module, prefix))


def register_after_reset(module: str, fn: AfterResetFn) -> None:
    if any(name == module for name, _ in _after):
        raise ValueError(f"Действие после сброса модуля {module} уже зарегистрировано")
    _after.append((module, fn))


def registered() -> list[str]:
    return [name for name, _ in _registry]


def cache_prefixes() -> list[str]:
    return [prefix for _, prefix in _cache_prefixes]


def truncate(session: Session, *tables: str) -> None:
    """Очистить таблицы модуля вместе с зависимыми от них (`CASCADE`).

    `TRUNCATE` не вызывает построчные триггеры неизменяемости журналов (UPDATE/DELETE), поэтому
    журналы чистятся только так. Защищённые таблицы (`PROTECTED_TABLES`) не принимаются:
    `CASCADE` идёт от родителя к ссылающимся на него, а у защищённых таблиц ссылок наружу нет.
    """
    forbidden = PROTECTED_TABLES.intersection(tables)
    if forbidden:
        raise ValueError("Эти таблицы сбросу не подлежат: " + ", ".join(sorted(forbidden)))
    for table in tables:
        if not table.isidentifier():
            raise ValueError(f"Недопустимое имя таблицы: {table!r}")
    session.execute(text("TRUNCATE TABLE " + ", ".join(tables) + " CASCADE"))


def run_all_resets(session: Session) -> list[str]:
    if not get_settings().demo_mode:
        raise AppError(403, "DEMO_DISABLED", "Сброс доступен только при DEMO_MODE=true")
    for _, fn in _registry:
        fn(session)
    return registered()


def run_after_resets(session: Session) -> dict[str, Any]:
    """Действия после чистки базы, по порядку регистрации; результат каждого — по имени модуля."""
    if not get_settings().demo_mode:
        raise AppError(403, "DEMO_DISABLED", "Сброс доступен только при DEMO_MODE=true")
    return {name: fn(session) for name, fn in _after}


# Платформенные таблицы shared чистит сам реестр: у них нет модуля-владельца
register_reset("shared", lambda session: truncate(session, "outbox", "idempotency_keys"))
