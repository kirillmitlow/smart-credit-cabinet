"""Миграции роли tax. Модели роли подключаются в target_metadata, когда появятся таблицы."""

from app.common.migrations_env import run_env
from app.settings import Role

run_env(Role.TAX, None)
