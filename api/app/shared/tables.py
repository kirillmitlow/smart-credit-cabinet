"""Владение таблицами (R5): каждая таблица числится ровно за одним модулем.

Модуль, добавивший таблицу, дописывает её сюда в той же задаче. Тест сверяет словарь с моделями
SQLAlchemy: таблица без владельца или с двумя владельцами ломает CI.
"""

from __future__ import annotations

TABLE_OWNERS: dict[str, str] = {
    "outbox": "shared",
    "idempotency_keys": "shared",
    "users": "auth",
    "companies": "companies",
    "company_members": "companies",
    "audit_log": "audit",
    "integration_calls": "integrations",
}
