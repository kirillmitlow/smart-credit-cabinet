"""Настройки, которые нужны только БКИ (читаются из окружения, остальные роли о них не знают)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BkiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    # Минимальный платёж по лимитам (линия, овердрафт, карта), % от использованной части (6.1)
    bki_limit_payment_percent: float = 5.0
    # Как в таблице запросов называется наш банк (в отчёт имя не попадает, 6.1)
    bki_own_user_name: str = "Наш банк"
