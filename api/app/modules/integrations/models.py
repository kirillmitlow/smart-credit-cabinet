"""Журнал вызовов внешних систем: одна строка на каждую попытку (50-06, 50-08, спецификация моков 9.4).

Тел запросов и ответов здесь нет, ИНН замаскирован. Полный ответ лежит только в снимках источников.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.db import Base


class IntegrationCall(Base):
    __tablename__ = "integration_calls"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=clock.now, index=True
    )
    system: Mapped[str] = mapped_column(String(16), index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(200))
    subject_inn_masked: Mapped[str | None] = mapped_column(String(12))
    status_code: Mapped[int | None] = mapped_column(Integer)
    # Код отказа системы (CONSENT_EXPIRED…) или причина на нашей стороне (TIMEOUT, SCHEMA_ERROR…)
    error_code: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer)
    circuit_state: Mapped[str | None] = mapped_column(String(16))
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # Без внешнего ключа: журнал живёт дольше заявки и пишется отдельной транзакцией
    application_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    # Мок вернул сохранённый ответ (Idempotent-Replayed): второго платного запроса не было
    idempotent_replayed: Mapped[bool] = mapped_column(Boolean, default=False)
