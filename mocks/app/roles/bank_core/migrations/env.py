"""Миграции роли bank_core."""

from app.common.migrations_env import run_env
from app.roles.bank_core.models import Base
from app.settings import Role

run_env(Role.BANK_CORE, Base.metadata)
