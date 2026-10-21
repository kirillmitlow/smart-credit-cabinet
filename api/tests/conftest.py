"""Общие фикстуры api: профили Hypothesis, изоляция настроек, запрет сети для ядра (T-208)."""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import HealthCheck, settings

from app.shared import cache
from app.shared.settings import get_settings

# dev — быстро локально, ci — детерминированно на PR, deep — ночью и перед сдачей (D-088)
settings.register_profile("dev", max_examples=50)
settings.register_profile(
    "ci", max_examples=200, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
settings.register_profile("deep", max_examples=2000)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Каждый тест читает настройки заново: monkeypatch.setenv действует сразу."""
    monkeypatch.setenv("APP_ENV", os.environ.get("APP_ENV", "test"))
    get_settings.cache_clear()
    cache.get_redis.cache_clear()
    yield
    get_settings.cache_clear()
    cache.get_redis.cache_clear()


class NetworkForbiddenError(RuntimeError):
    pass


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Для тестов ядра (INV-51): любая попытка открыть соединение — понятная ошибка."""

    def forbid(*_args: Any, **_kwargs: Any) -> Any:
        raise NetworkForbiddenError("Ядро decisioning не должно ходить в сеть (R2, INV-51)")

    monkeypatch.setattr(socket.socket, "connect", forbid)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid)
    monkeypatch.setattr(socket, "create_connection", forbid)
    monkeypatch.setattr(socket, "getaddrinfo", forbid)
