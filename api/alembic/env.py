"""Окружение Alembic: из приложения приходит готовое соединение, из командной строки — DATABASE_URL."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

import app.shared.models  # noqa: F401 — регистрирует таблицы shared в metadata
from app.shared.db import Base

target_metadata = Base.metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    url = context.config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
