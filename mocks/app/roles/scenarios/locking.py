"""Один изменяющий сценарии процесс за раз, включая фон восстановления.

Блокировка сессии Postgres держится на закреплённом соединении между коммитами журнала.
Транзакционная блокировка здесь отпустила бы конкурента после первого сетевого запроса.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import Database

LOCK_KEY = 734218705623


@asynccontextmanager
async def locked_session(database: Database) -> AsyncIterator[AsyncSession]:
    async with mutation_session(database) as session:
        if session is None:
            raise RuntimeError("Ожидающая блокировка сценариев не получена")
        yield session


@asynccontextmanager
async def mutation_session(
    database: Database, *, wait: bool = True
) -> AsyncIterator[AsyncSession | None]:
    async with database.engine.connect() as connection:
        try:
            function = "pg_advisory_lock" if wait else "pg_try_advisory_lock"
            result = await connection.scalar(text(f"SELECT {function}(:key)"), {"key": LOCK_KEY})
            await connection.commit()
            if not wait and not result:
                yield None
                return
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                yield session
        finally:
            # Unlock даже при отмене ожидания: сервер мог успеть захватить блокировку.
            if not connection.invalidated:
                try:
                    await connection.rollback()
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY}
                    )
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise
