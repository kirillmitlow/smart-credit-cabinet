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


RESET_TIMEOUT_SECONDS = 120.0  # сброс чистит четыре мока и применяет все сценарии заново


def apply_one(code: str, *, idempotency_key: str) -> dict[str, Any]:
    """Повторно применить исходный сценарий к одной компании, включая RUNTIME моков."""
    settings = get_settings()
    try:
        with httpx.Client(
            base_url=settings.scenarios_url,
            headers={"X-Admin-Key": settings.mock_admin_key, "Idempotency-Key": idempotency_key},
            timeout=RESET_TIMEOUT_SECONDS * settings.integration_timeout_scale,
        ) as client:
            response = client.post(f"/api/v1/scenarios/{code}/apply")
            response.raise_for_status()
            view: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ScenariosUnavailableError(f"{type(exc).__name__}: {exc}") from exc
    if view.get("status") != "APPLIED":
        raise ScenariosUnavailableError("Сценарий не применён полностью")
    return view


def reset_all(mode: str = "KEEP_CUSTOM") -> dict[str, Any]:
    """Общий сброс моков (`POST /scenarios/reset`, 8.4): очистка, chaos в OK, сценарии заново.

    Только для модуля `demo` (D-081). Ошибку мока (в том числе 502 RESET_FAILED) отдаём как
    `ScenariosUnavailableError` с текстом причины: `demo` назовёт шаг «моки».
    """
    settings = get_settings()
    try:
        with httpx.Client(
            base_url=settings.scenarios_url,
            headers={"X-Admin-Key": settings.mock_admin_key},
            timeout=RESET_TIMEOUT_SECONDS * settings.integration_timeout_scale,
        ) as client:
            response = client.post("/api/v1/scenarios/reset", json={"mode": mode})
    except httpx.HTTPError as exc:
        raise ScenariosUnavailableError(f"{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        try:
            detail = str(response.json().get("detail") or "")
        except ValueError:
            detail = ""
        raise ScenariosUnavailableError(f"HTTP {response.status_code}: {detail[:500]}")
    result: dict[str, Any] = response.json()
    return result


class ScenarioRejectedError(RuntimeError):
    """Публичный отказ сценария, без внутренних адресов и тела ошибки сервиса."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def create_scenario(spec: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
    """Создать и применить; повтор ключа возвращает тот же сценарий после потери ответа."""
    settings = get_settings()
    try:
        with httpx.Client(
            base_url=settings.scenarios_url,
            headers={"X-Admin-Key": settings.mock_admin_key, "Idempotency-Key": idempotency_key},
            timeout=RESET_TIMEOUT_SECONDS * settings.integration_timeout_scale,
        ) as client:
            response = client.post("/api/v1/scenarios", json=spec)
        if response.status_code in {400, 409, 422}:
            try:
                code = response.json().get("code")
            except (ValueError, AttributeError):
                code = None
            allowed = {
                "INN_INVALID",
                "VALIDATION_ERROR",
                "SCENARIO_EXISTS",
                "SCENARIO_INN_EXISTS",
                "IDEMPOTENCY_IN_PROGRESS",
                "IDEMPOTENCY_KEY_REUSED",
            }
            fallback = (
                "VALIDATION_ERROR" if response.status_code in {400, 422} else "SCENARIO_EXISTS"
            )
            raise ScenarioRejectedError(
                response.status_code,
                code if isinstance(code, str) and code in allowed else fallback,
            )
        response.raise_for_status()
        view = response.json()
        if (
            response.status_code != 201
            or not isinstance(view, dict)
            or view.get("status") != "APPLIED"
        ):
            raise ScenariosUnavailableError("Создание сценария не подтверждено")
        return view
    except (httpx.HTTPError, ValueError) as exc:
        raise ScenariosUnavailableError("Сервис сценариев не подтвердил создание") from exc
