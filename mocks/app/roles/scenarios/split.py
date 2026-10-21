"""Чистая раскладка проверенного expanded на админ-тела четырёх систем (10.4)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class System(StrEnum):
    REGISTRY = "REGISTRY"
    TAX = "TAX"
    BKI = "BKI"
    BANK_CORE = "BANK_CORE"

    @property
    def summary_key(self) -> str:
        return "bankCore" if self is System.BANK_CORE else self.value.lower()


@dataclass(frozen=True)
class Subject:
    inn: str
    body: dict[str, Any]


def split(expanded: dict[str, Any]) -> dict[System, list[Subject]]:
    """Пустой PUT АБС не создаёт ресурс. Комплаенс не-клиента всё же нужно хранить.

    Реестру передаём единое тело с людьми; БКИ и АБС принимают также отдельных людей.
    Вход уже проверен T-126, повторно генерировать личности или значения нельзя.
    """
    inn = expanded["identity"]["inn"]
    result: dict[System, list[Subject]] = {system: [] for system in System}
    for system, key in (
        (System.REGISTRY, "registry"),
        (System.TAX, "tax"),
        (System.BANK_CORE, "bankCore"),
    ):
        body = expanded.get(key) or {}
        meaningful = any(body.values())
        if system is System.BANK_CORE:
            meaningful = any(
                body.get(k) for k in ("customer", "accounts", "turnover", "loans")
            ) or any((body.get("compliance") or {}).values())
        if meaningful:
            result[system].append(Subject(inn, body))
    for system, key in ((System.BKI, "bki"), (System.BANK_CORE, "bankSubjects")):
        for entry in expanded.get(key, []):
            if any(entry["body"].values()):
                result[system].append(Subject(entry["inn"], entry["body"]))
    return result
