"""Реестр сброса демо (T-204): каждый модуль сам чистит свои таблицы, demo вызывает всех.

Модули регистрируют функцию при импорте; demo не импортирует модули напрямую (50-04).
Вне DEMO_MODE сброс запрещён.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.shared.errors import AppError
from app.shared.settings import get_settings

ResetFn = Callable[[Session], None]

# Порядок регистрации = порядок сброса; зависимые таблицы чистятся раньше родительских
_registry: list[tuple[str, ResetFn]] = []


def register_reset(module: str, fn: ResetFn) -> None:
    if any(name == module for name, _ in _registry):
        raise ValueError(f"Сброс модуля {module} уже зарегистрирован")
    _registry.append((module, fn))


def registered() -> list[str]:
    return [name for name, _ in _registry]


def run_all_resets(session: Session) -> list[str]:
    if not get_settings().demo_mode:
        raise AppError(403, "DEMO_DISABLED", "Сброс доступен только при DEMO_MODE=true")
    for _, fn in _registry:
        fn(session)
    return registered()
