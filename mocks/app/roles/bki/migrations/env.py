"""Миграции роли bki. Метаданные таблиц роли — для autogenerate; таблицу ключей идемпотентности
ведёт ревизия bki_0002 (при autogenerate её drop из черновика убираем руками)."""

from app.common.migrations_env import run_env
from app.roles.bki.models import Base
from app.settings import Role

run_env(Role.BKI, Base.metadata)
