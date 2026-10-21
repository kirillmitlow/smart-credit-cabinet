"""Платформенные таблицы shared: outbox и ключи идемпотентности (50-06, 50-05).

Статусы — строки с CHECK, не ENUM Postgres: добавить значение можно без пересоздания типа.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.db import Base


class OutboxMessage(Base):
    """Сообщение в БКИ или АБС, записанное в той же транзакции, что и смена статуса."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED')", name="status"),
        CheckConstraint("target_system IN ('BKI', 'BANK_CORE')", name="target_system"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    target_system: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)


class IdempotencyKey(Base):
    """Защита POST от двойного нажатия: scope = пользователь + метод + путь (50-07)."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_keys_scope_key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    scope: Mapped[str] = mapped_column(String(300))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
