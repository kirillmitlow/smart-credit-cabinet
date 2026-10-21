"""T-100: один образ, пять ролей, понятная ошибка при неверной роли."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.main import create_app
from app.settings import ROLE_SERVICE, ConfigError, Role, load_settings
from tests.conftest import make_settings

MOCKS_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("role", list(Role))
async def test_each_role_starts_and_is_live(role: Role) -> None:
    app = create_app(make_settings(mock_role=role.value))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        live = await client.get("/health/live")
        docs = await client.get("/docs")
        spec = await client.get("/openapi.json")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert docs.status_code == 200
    assert spec.status_code == 200
    assert ROLE_SERVICE[role] in spec.json()["info"]["title"]


async def test_ready_is_503_without_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 503


@pytest.mark.parametrize("value", ["", "ledger"])
def test_unknown_or_empty_role_is_config_error(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MOCK_ROLE", value)
    with pytest.raises(ConfigError, match="MOCK_ROLE"):
        load_settings()


def test_bad_latency_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_ROLE", "tax")
    monkeypatch.setenv("MOCK_LATENCY_MS", "600-200")
    with pytest.raises(ConfigError, match="MOCK_LATENCY_MS"):
        load_settings()


def test_process_exits_with_russian_message_on_bad_role() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MOCK_")}
    env["MOCK_ROLE"] = "ledger"
    result = subprocess.run(  # noqa: S603 — запускаем свой модуль тем же интерпретатором
        [sys.executable, "-m", "app"],
        cwd=MOCKS_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2
    assert "Мок не запущен" in result.stderr
    assert "registry" in result.stderr


def test_settings_parse_keys_and_latency() -> None:
    settings = make_settings(mock_api_keys="api:k1, tests:k2", mock_latency_ms="200-600")
    assert settings.api_keys == {"k1": "api", "k2": "tests"}
    assert settings.latency_range_ms == (200, 600)
    assert make_settings(app_today="").app_today is None
