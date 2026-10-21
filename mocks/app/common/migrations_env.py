"""Общий env.py для миграций ролей: из приложения (готовое соединение) и из командной строки."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import Connection, MetaData
from sqlalchemy.ext.asyncio import create_async_engine

from app.common.db import version_table
from app.settings import Role


def _configure_and_run(connection: Connection, metadata: MetaData | None, role: Role) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table=version_table(role),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_from_url(url: str, metadata: MetaData | None, role: Role) -> None:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(_configure_and_run, metadata, role)
        await conn.commit()
    await engine.dispose()


def run_env(role: Role, metadata: MetaData | None) -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection, metadata, role)
        return
    url = context.config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]
    asyncio.run(_run_from_url(url, metadata, role))
