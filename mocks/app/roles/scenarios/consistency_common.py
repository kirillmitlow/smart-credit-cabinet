"""Контекст и сообщения правил согласованности синтетического сценария."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.debt_history import Trajectory
from app.roles.scenarios.schemas import ScenarioSpec


@dataclass
class Context:
    spec: ScenarioSpec
    data: dict[str, Any]
    today: date
    settings: ScenarioSettings
    code: str
    history: dict[str, Trajectory] = field(default_factory=dict)

    @property
    def identity(self) -> dict[str, Any]:
        return self.data["identity"]

    @property
    def tax(self) -> dict[str, Any]:
        return self.data["tax"]

    @property
    def bank(self) -> dict[str, Any]:
        return self.data["bankCore"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
