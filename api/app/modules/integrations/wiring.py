"""Сборка адаптеров: один общий клиент (пул соединений, журнал, предохранитель) на процесс."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.modules.integrations.bank_core import BankCoreReadAdapter
from app.modules.integrations.client import IntegrationClient
from app.modules.integrations.credit_bureau import CreditBureauAdapter
from app.modules.integrations.registry import RegistryAdapter
from app.modules.integrations.tax import TaxAdapter


@dataclass(frozen=True, slots=True)
class Integrations:
    """Порты всех внешних систем. Конвейер и тесты работают только с ними."""

    registry: RegistryAdapter
    tax: TaxAdapter
    bank_core: BankCoreReadAdapter
    credit_bureau: CreditBureauAdapter
    client: IntegrationClient


def build_integrations(client: IntegrationClient | None = None) -> Integrations:
    client = client or IntegrationClient()
    return Integrations(
        registry=RegistryAdapter(client),
        tax=TaxAdapter(client),
        bank_core=BankCoreReadAdapter(client),
        credit_bureau=CreditBureauAdapter(client),
        client=client,
    )


_lock = threading.Lock()
_instance: Integrations | None = None


def get_integrations() -> Integrations:
    global _instance
    with _lock:
        if _instance is None:
            _instance = build_integrations()
        return _instance


def set_integrations(integrations: Integrations | None) -> None:
    """Подмена в тестах (или сброс при `None`): закрывает прежний клиент."""
    global _instance
    with _lock:
        if _instance is not None:
            _instance.client.close()
        _instance = integrations
