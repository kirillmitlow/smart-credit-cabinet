"""Миграции роли registry."""

from app.common.migrations_env import run_env
from app.roles.registry.models import Base
from app.settings import Role

run_env(Role.REGISTRY, Base.metadata)
