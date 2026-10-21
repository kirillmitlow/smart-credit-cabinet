"""База mock_scenarios (10.7): сценарии и журнал их применения. Ключи идемпотентности — общая
таблица idempotency_keys (миграция scenarios_0002)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData()


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        CheckConstraint("origin IN ('BUILTIN', 'CUSTOM')", name="ck_scenarios_origin"),
        CheckConstraint(
            "status IN ('PENDING', 'APPLIED', 'PARTIAL', 'FAILED')", name="ck_scenarios_status"
        ),
    )

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(16))
    builtin_version: Mapped[int | None] = mapped_column(Integer)
    modified: Mapped[bool] = mapped_column(Boolean, default=False)
    expected_outcome: Mapped[str | None] = mapped_column(String(32))
    expected_final_outcome: Mapped[str | None] = mapped_column(String(32))
    expected_reason_codes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    inn: Mapped[str | None] = mapped_column(String(12), unique=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expanded: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    applied: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    needs_reapply: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    applied_month: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScenarioApplication(Base):
    """Журнал: что и куда отправлялось."""

    __tablename__ = "scenario_applications"
    __table_args__ = (
        CheckConstraint(
            "system IN ('REGISTRY', 'TAX', 'BKI', 'BANK_CORE')", name="ck_applications_system"
        ),
        CheckConstraint("action IN ('PUT', 'DELETE')", name="ck_applications_action"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    scenario_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("scenarios.code", ondelete="CASCADE"), index=True
    )
    system: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(8))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
