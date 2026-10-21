"""Точка входа ядра. Пока заглушка: реальные шаги собирает T-300 по спецификациям 30-xx."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DecisionInput:
    application_id: str
    facts: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionResult:
    outcome: str
    reason_codes: tuple[str, ...] = ()


def decide(inputs: DecisionInput) -> DecisionResult:
    """Детерминированная функция: одинаковые входы — одинаковый результат."""
    return DecisionResult(outcome="NEEDS_INFO", reason_codes=("NOT_IMPLEMENTED",))
