"""Настройки api из переменных окружения (docs/plan/50-architecture/13-config-and-profiles.md).

На `APP_ENV=cloud` секреты обязательны и не могут совпадать со значениями для разработки:
иначе процесс не стартует (50-09).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"
    TEST = "test"


# Значения «только для разработки»: на облаке запрещены (раздел «Секреты» 50-13)
DEV_SECRETS: dict[str, str] = {
    "postgres_password": "dev-postgres",
    "session_secret": "dev-session-secret",
    "registry_api_key": "dev-registry-key",
    "tax_api_key": "dev-tax-key",
    "bki_api_key": "dev-bki-key",
    "bank_core_api_key": "dev-bank-core-key",
    "mock_admin_key": "dev-admin-key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    # Общие
    app_env: AppEnv = AppEnv.LOCAL
    app_today: date | None = None
    demo_mode: bool = True
    demo_stand_code: SecretStr = Field(default=SecretStr(""), repr=False)
    demo_controls_per_minute: int = Field(default=300, ge=1)
    docs_links: dict[str, str] = Field(default_factory=lambda: {"api": "/docs"})
    log_level: str = "INFO"
    cookie_secure: bool = False
    cors_origins: str = ""

    # Хранилища
    postgres_host: str = "postgres"
    postgres_db: str = "api"
    postgres_user: str = "api"
    postgres_password: str = DEV_SECRETS["postgres_password"]
    database_url: str | None = None
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"

    # Внешние системы (моки)
    registry_url: str = "http://mock-registry:8000"
    tax_url: str = "http://mock-tax:8000"
    bki_url: str = "http://mock-credit-bureau:8000"
    bank_core_url: str = "http://mock-bank-core:8000"
    scenarios_url: str = "http://mock-scenarios:8000"
    integration_timeout_scale: float = Field(default=1.0, gt=0, le=10)
    cache_ttl_autofill_hours: int = Field(default=24, ge=0)

    # Процесс и правила
    policy_file: str = "policy/v1.yaml"
    # Хеш коммита сборки образа (ENGINE_VERSION); не из часов (30-13). TODO: передавать build-arg в compose
    engine_version: str = "dev"
    policy_edit_enabled: bool = False
    expiry_enabled: bool = False
    needs_info_ttl_days: int = Field(default=5, ge=1)
    offer_ttl_days: int = Field(default=10, ge=1)
    upload_max_mb: int = Field(default=10, ge=1, le=50)
    upload_max_files_per_application: int = Field(default=10, ge=1, le=10)
    session_idle_minutes: int = Field(default=30, ge=1)
    session_absolute_hours: int = Field(default=8, ge=1)
    rate_limit_enabled: bool = True
    metrics_enabled: bool = True
    worker_concurrency: int = Field(default=3, ge=1, le=16)

    # Профиль ИИ (D-094)
    nlu_enabled: bool = True
    nlu_base_url: str = "http://nlu:8000"

    # Секреты
    session_secret: str = DEV_SECRETS["session_secret"]
    registry_api_key: str = DEV_SECRETS["registry_api_key"]
    tax_api_key: str = DEV_SECRETS["tax_api_key"]
    bki_api_key: str = DEV_SECRETS["bki_api_key"]
    bank_core_api_key: str = DEV_SECRETS["bank_core_api_key"]
    mock_admin_key: str = DEV_SECRETS["mock_admin_key"]

    @field_validator("app_today", "database_url", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _cloud_requires_real_secrets(self) -> Self:
        if self.app_env is AppEnv.CLOUD:
            weak = [
                name.upper()
                for name, dev_value in DEV_SECRETS.items()
                if not getattr(self, name) or getattr(self, name) == dev_value
            ]
            if weak:
                raise ValueError(
                    "APP_ENV=cloud: задайте настоящие значения секретов: " + ", ".join(weak)
                )
        return self

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
