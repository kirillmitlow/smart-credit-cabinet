"""Управление сбоями моков: только демо-панель, D-081. Админ-ключ остаётся на сервере."""

from typing import Any

import httpx

from app.modules.integrations.results import System
from app.shared.settings import get_settings


class ChaosUnavailableError(RuntimeError):
    pass


def configure(system: System, config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    urls = {
        System.REGISTRY: settings.registry_url,
        System.TAX: settings.tax_url,
        System.CREDIT_BUREAU: settings.bki_url,
        System.BANK_CORE: settings.bank_core_url,
    }
    try:
        with httpx.Client(
            base_url=urls[system],
            headers={"X-Admin-Key": settings.mock_admin_key},
            timeout=5 * settings.integration_timeout_scale,
        ) as client:
            response = (
                client.get("/admin/chaos")
                if config is None
                else client.put("/admin/chaos", json=config)
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data
    except (httpx.HTTPError, ValueError) as exc:
        # Не передаём наружу тело ошибки или конфигурацию HTTP-клиента.
        raise ChaosUnavailableError(system.value) from exc
