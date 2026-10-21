"""Миграции роли scenarios. Модели роли подключаются в target_metadata, когда появятся таблицы."""

from app.common.migrations_env import run_env
from app.roles.scenarios.models import Base
from app.settings import Role

run_env(Role.SCENARIOS, Base.metadata)
