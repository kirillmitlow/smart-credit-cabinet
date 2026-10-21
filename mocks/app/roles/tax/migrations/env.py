"""Миграции роли tax."""

from app.common.migrations_env import run_env
from app.roles.tax.models import Base
from app.settings import Role

run_env(Role.TAX, Base.metadata)
