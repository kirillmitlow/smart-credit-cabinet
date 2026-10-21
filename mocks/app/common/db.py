"""База роли: async-движок, сессии, миграции Alembic при старте и признак готовности (раздел 3.2).

У каждой роли своя база и свой набор миграций `roles/<роль>/migrations`. Миграции применяются
под advisory-блокировкой; пока база недоступна или схема не на последней ревизии,
/health/ready отвечает 503.
"""

from __future__ import annotations

import asyncio
import logging
import zlib
from collections.abc import AsyncIterator
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, Request
from sqlalchemy import Connection, String, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.settings import Role

log = logging.getLogger("app.db")

ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"
RETRY_SECONDS = 2.0


class Origin(StrEnum):
    SCENARIO = "SCENARIO"  # создано сервисом сценариев
    RUNTIME = "RUNTIME"  # появилось в работе: запрос в БКИ, выдача, открытие счёта


class OriginMixin:
    """Происхождение записи: по нему сброс компании не трогает чужие данные (3.2)."""

    origin: Mapped[str] = mapped_column(String(16), default=Origin.SCENARIO.value)
    scenario_code: Mapped[str | None] = mapped_column(String(64), index=True, default=None)


def version_table(role: Role) -> str:
    return f"alembic_version_{role.value}"


def alembic_config(role: Role, url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROLES_DIR / role.value / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["role"] = role
    return cfg


def head_revision(role: Role) -> str | None:
    return ScriptDirectory.from_config(alembic_config(role)).get_current_head()


def _lock_key(role: Role) -> int:
    return zlib.crc32(f"scc-mocks-migrate-{role.value}".encode())


class Database:
    def __init__(self, url: str, role: Role) -> None:
        self.role = role
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True, pool_size=5)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.migrated = False
        self._head = head_revision(role)

    async def migrate(self) -> None:
        """Применить миграции роли до последней ревизии под блокировкой Postgres."""
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _lock_key(self.role)})
            try:
                await conn.run_sync(self._upgrade)
                await conn.commit()
            finally:
                await conn.rollback()  # после ошибки транзакция прервана, иначе unlock не пройдёт
                unlock = text("SELECT pg_advisory_unlock(:k)")
                await conn.execute(unlock, {"k": _lock_key(self.role)})
                await conn.commit()
        self.migrated = True

    def _upgrade(self, connection: Connection) -> None:
        cfg = alembic_config(self.role)
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

    async def migrate_until_done(self) -> None:
        """Повторять, пока Postgres не поднимется: стенд стартует в любом порядке."""
        while not self.migrated:
            try:
                await self.migrate()
                log.info("Миграции применены", extra={"chaos": None})
            except Exception as exc:  # база ещё не готова — пробуем снова
                log.warning("База недоступна, повтор через %.0f с: %s", RETRY_SECONDS, exc)
                await asyncio.sleep(RETRY_SECONDS)

    async def is_ready(self) -> bool:
        if not self.migrated:
            return False
        try:
            async with self.engine.connect() as conn:
                result = await conn.execute(
                    text(f"SELECT version_num FROM {version_table(self.role)}")  # noqa: S608
                )
                return result.scalar_one_or_none() == self._head
        except Exception:
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
