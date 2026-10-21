"""Настройки мока из переменных окружения (разделы 2.3, 2.5, 3.1, 3.4 спецификации)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from functools import cached_property

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Role(StrEnum):
    REGISTRY = "registry"
    TAX = "tax"
    BKI = "bki"
    BANK_CORE = "bank_core"
    SCENARIOS = "scenarios"


# Имя сервиса в compose и заголовок Swagger для каждой роли
ROLE_SERVICE = {
    Role.REGISTRY: "mock-registry",
    Role.TAX: "mock-tax",
    Role.BKI: "mock-credit-bureau",
    Role.BANK_CORE: "mock-bank-core",
    Role.SCENARIOS: "mock-scenarios",
}

ROLE_TITLE = {
    Role.REGISTRY: "ЕГРЮЛ / ЕГРИП и реестр банкротств (ЕФРСБ)",
    Role.TAX: "Открытые сервисы ФНС и госзакупки (ЕИС)",
    Role.BKI: "Бюро кредитных историй",
    Role.BANK_CORE: "АБС банка и комплаенс",
    Role.SCENARIOS: "Сервис тестовых сценариев",
}


class ConfigError(Exception):
    """Ошибка конфигурации: процесс должен остановиться с понятным сообщением."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    mock_role: Role
    # Диапазон случайной задержки бизнес-ответов, мс: "200-600" или одно число
    mock_latency_ms: str = "0"
    # Ключи потребителей: "api:dev-registry-key[,имя:ключ]"
    mock_api_keys: str = ""
    mock_admin_key: str = "dev-admin-key"
    database_url: str | None = None
    # Пусто — реальная дата; иначе ISO-дата «сегодня» для всего стенда (2.5)
    app_today: date | None = None
    bank_bik: str = Field(default="040000999", pattern=r"^\d{9}$")

    @field_validator("app_today", "database_url", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("mock_latency_ms")
    @classmethod
    def _check_latency(cls, value: str) -> str:
        parse_latency(value)
        return value

    @field_validator("mock_api_keys")
    @classmethod
    def _check_keys(cls, value: str) -> str:
        parse_api_keys(value)
        return value

    @cached_property
    def latency_range_ms(self) -> tuple[int, int]:
        return parse_latency(self.mock_latency_ms)

    @cached_property
    def api_keys(self) -> dict[str, str]:
        """Ключ → имя потребителя."""
        return parse_api_keys(self.mock_api_keys)

    @property
    def service_name(self) -> str:
        return ROLE_SERVICE[self.mock_role]


def parse_latency(raw: str) -> tuple[int, int]:
    parts = raw.strip().split("-")
    try:
        bounds = [int(p) for p in parts]
    except ValueError as exc:
        message = f"MOCK_LATENCY_MS: ожидается «200-600» или число, получено {raw!r}"
        raise ValueError(message) from exc
    if len(bounds) == 1:
        bounds *= 2
    if len(bounds) != 2 or bounds[0] < 0 or bounds[0] > bounds[1]:
        raise ValueError(f"MOCK_LATENCY_MS: неверный диапазон {raw!r}")
    return bounds[0], bounds[1]


def parse_api_keys(raw: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        consumer, sep, key = item.partition(":")
        if not sep or not consumer or not key:
            raise ValueError("MOCK_API_KEYS: ожидается «потребитель:ключ[,потребитель:ключ]»")
        keys[key] = consumer
    return keys


def load_settings() -> Settings:
    """Прочитать окружение; при ошибке — ConfigError с текстом для человека."""
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"]).upper() or "окружение"
            if field == "MOCK_ROLE":
                allowed = ", ".join(r.value for r in Role)
                lines.append(f"MOCK_ROLE не задана или неизвестна; допустимо: {allowed}")
            else:
                lines.append(f"{field}: {err['msg']}")
        raise ConfigError("Мок не запущен: " + "; ".join(lines)) from exc
