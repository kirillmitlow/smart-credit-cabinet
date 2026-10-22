"""Реестр сброса демо (T-204, T-371): каждый модуль сам чистит свои таблицы, demo вызывает всех.

Модули регистрируют функции при импорте; demo не импортирует модули напрямую (50-04).
Вне DEMO_MODE сброс запрещён. Реестр знает три вида действий:

* `register_reset` — чистка таблиц модуля (`TRUNCATE`, см. `truncate`);
* `register_cache_prefix` — префикс ключей Valkey, которые надо удалить (сессии, кэш);
* `register_after_reset` — действие после чистки базы (например, подтянуть компании из сценариев).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.shared.db import Base
from app.shared.errors import AppError
from app.shared.models import IdempotencyKey, OutboxMessage
from app.shared.settings import get_settings
from app.shared.tables import TABLE_OWNERS

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


# Выборочный сброс (T-372): сначала собрать идентификаторы всех владельцев, затем чистить.


@dataclass
class Persona:
    company_id: UUID
    inn: str
    resources: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def add(self, name: str, values: Iterable[object]) -> None:
        self.resources[name] = tuple(str(value) for value in values)

    def keys(self, name: str) -> tuple[str, ...]:
        return self.resources.get(name, ())

    def ids(self, name: str) -> tuple[UUID, ...]:
        return tuple(UUID(value) for value in self.keys(name))

    def journal_ids(self) -> tuple[str, ...]:
        values = {str(self.company_id)}
        for group in self.resources.values():
            for value in group:
                try:
                    values.add(str(UUID(value)))
                except ValueError:
                    pass  # числовые id outbox не являются разрешением стирать UUID-ресурсы
        return tuple(sorted(values))


PersonaFn = Callable[[Session, Persona], None]
PersonaCacheFn = Callable[[Persona], None]


@dataclass(frozen=True)
class PersonaReset:
    module: str
    clean: PersonaFn
    priority: int
    prepare: PersonaFn | None = None
    prepare_priority: int = 50
    cache: PersonaCacheFn | None = None


_persona: list[PersonaReset] = []


def register_persona_reset(
    module: str,
    clean: PersonaFn,
    *,
    priority: int,
    prepare: PersonaFn | None = None,
    prepare_priority: int = 50,
    cache: PersonaCacheFn | None = None,
) -> None:
    if any(entry.module == module for entry in _persona):
        raise ValueError(f"Сброс персоны модуля {module} уже зарегистрирован")
    _persona.append(PersonaReset(module, clean, priority, prepare, prepare_priority, cache))


def collect_persona(session: Session, company_id: UUID, inn: str) -> Persona:
    scope = Persona(company_id, inn)
    for entry in sorted(_persona, key=lambda item: item.prepare_priority):
        if entry.prepare is not None:
            entry.prepare(session, scope)
    return scope


def reset_persona_cache(scope: Persona) -> None:
    for entry in _persona:
        if entry.cache is not None:
            entry.cache(scope)


def reset_persona_rows(session: Session, scope: Persona) -> list[str]:
    if not get_settings().demo_mode:
        raise AppError(403, "DEMO_DISABLED")
    session.execute(
        text("SELECT set_config('scc.demo_reset_ids', :ids, true)"),
        {"ids": ",".join(scope.journal_ids())},
    )
    session.execute(
        text("SELECT set_config('scc.demo_reset_outbox_ids', :ids, true)"),
        {"ids": ",".join(scope.keys("outbox"))},
    )
    entries = sorted(_persona, key=lambda entry: entry.priority)
    for entry in entries:
        entry.clean(session, scope)
    return [entry.module for entry in entries]


def owned_ids(
    session: Session, module: str, table: str, column: str, values: Iterable[object]
) -> tuple[str, ...]:
    if TABLE_OWNERS.get(table) != module:
        raise ValueError(f"{table} не принадлежит {module}")
    resource = Base.metadata.tables[table]
    rows = session.scalars(select(resource.c.id).where(resource.c[column].in_(tuple(values))))
    return tuple(str(value) for value in rows)


def delete_owned(
    session: Session, module: str, table: str, column: str, values: Iterable[object]
) -> None:
    if TABLE_OWNERS.get(table) != module or table in PROTECTED_TABLES:
        raise ValueError(f"Нельзя очистить {table} из {module}")
    resource = Base.metadata.tables[table]
    session.execute(delete(resource).where(resource.c[column].in_(tuple(values))))


def _prepare_shared(session: Session, scope: Persona) -> None:
    scope.add(
        "outbox",
        session.scalars(
            select(OutboxMessage.id).where(
                OutboxMessage.aggregate_id.in_(scope.keys("applications"))
            )
        ),
    )


def _mentions(value: object, resources: set[str]) -> bool:
    if isinstance(value, dict):
        return any(_mentions(item, resources) for item in value.values())
    if isinstance(value, list):
        return any(_mentions(item, resources) for item in value)
    return isinstance(value, str) and value in resources


def _reset_shared(session: Session, scope: Persona) -> None:
    session.execute(
        delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(scope.keys("applications")))
    )
    resources = set(scope.journal_ids())
    for row in session.scalars(select(IdempotencyKey)):
        matches = any(value in row.scope for value in resources)
        if not matches and row.response_body:
            try:
                matches = _mentions(json.loads(row.response_body), resources)
            except (ValueError, UnicodeError):
                pass  # старые/незавершённые ключи без привязки нельзя отнести к компании
        if matches:
            session.delete(row)


register_persona_reset(
    "shared", _reset_shared, priority=5, prepare=_prepare_shared, prepare_priority=90
)
