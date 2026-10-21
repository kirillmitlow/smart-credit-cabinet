"""Клиент сервиса тестовых сценариев (моки, раздел 10.4).

В бизнес-процессе не участвует: api берёт отсюда учётки персон (блок users, Q-023) и их
«что просит» для самопроверки. Возвращает словари как есть — разбор делает потребитель.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.shared.settings import get_settings

TIMEOUT_SECONDS = 5.0


class ScenariosUnavailableError(RuntimeError):
    pass


def _client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.scenarios_url,
        headers={"X-Admin-Key": settings.mock_admin_key},
        timeout=TIMEOUT_SECONDS * settings.integration_timeout_scale,
    )


def list_scenarios() -> list[dict[str, Any]]:
    try:
        with _client() as client:
            response = client.get("/api/v1/scenarios")
            response.raise_for_status()
            result: list[dict[str, Any]] = response.json()
            return result
    except httpx.HTTPError as exc:
        raise ScenariosUnavailableError(str(exc)) from exc


def get_scenario(code: str) -> dict[str, Any]:
    try:
        with _client() as client:
            response = client.get(f"/api/v1/scenarios/{code}")
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
    except httpx.HTTPError as exc:
        raise ScenariosUnavailableError(str(exc)) from exc
