"""База api: синхронный SQLAlchemy 2 + psycopg 3 (Q-047, вариант А), миграции при старте (T-201).

Транзакцию открывает сервис (R7): `with transaction() as session: ...` — один сценарий, одна
транзакция. Миграции применяются под advisory-блокировкой: параллельно стартующие api и worker
не мешают друг другу, второй ждёт и видит готовую схему.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import DateTime, Engine, MetaData, Uuid, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.shared import clock
from app.shared.ids import uuid7

API_DIR = Path(__file__).resolve().parents[2]
_MIGRATION_LOCK = zlib.crc32(b"scc-api-migrations")

# Имена ограничений стабильны: миграции Alembic не «скачут» между запусками
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class TimestampMixin:
    """created_at/updated_at по часам стенда (APP_TODAY), а не по часам базы."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=clock.now, onupdate=clock.now
    )


class Database:
    def __init__(self, url: str, **engine_kwargs: Any) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True, **engine_kwargs)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Одна транзакция на сценарий: коммит в конце, откат при исключении."""
        with self.sessions.begin() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()


_database: Database | None = None


def configure(url: str, **engine_kwargs: Any) -> Database:
    global _database
    _database = Database(url, **engine_kwargs)
    return _database


def get_database() -> Database:
    if _database is None:
        raise RuntimeError("База не настроена: вызовите db.configure() при старте процесса")
    return _database


@contextmanager
def transaction() -> Iterator[Session]:
    with get_database().transaction() as session:
        yield session


def after_commit(session: Session, callback: Callable[[], None]) -> None:
    """Выполнить действие только после успешного коммита (постановка задач, R10)."""

    def _run(_session: Session) -> None:
        callback()

    event.listen(session, "after_commit", _run, once=True)


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def migrate(engine: Engine) -> None:
    """Применить миграции до head под блокировкой Postgres."""
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _MIGRATION_LOCK})
        try:
            cfg = alembic_config()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MIGRATION_LOCK})
            conn.commit()


def schema_is_current(engine: Engine) -> bool:
    """Текущая ревизия в базе = head (для /health/ready)."""
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current == head_revision()
