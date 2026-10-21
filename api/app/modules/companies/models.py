"""Компании и участники (50-06, D-014, D-015, D-091)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base, IdMixin, TimestampMixin


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (CheckConstraint("kind IN ('LEGAL', 'IP', 'SELF_EMPLOYED')", name="kind"),)

    inn: Mapped[str] = mapped_column(String(12), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str | None] = mapped_column(String(32))
    okved: Mapped[str | None] = mapped_column(String(16))
    registered_on: Mapped[date | None] = mapped_column(Date)
    is_bank_customer: Mapped[bool | None] = mapped_column(Boolean)
    scenario_code: Mapped[str | None] = mapped_column(String(64), index=True)
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    profile_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanyMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "company_members"
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", name="uq_company_members_company_user"),
        CheckConstraint("role IN ('DIRECTOR', 'ACCOUNTANT', 'GUARANTOR')", name="role"),
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="status"),
    )

    company_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    can_sign: Mapped[bool] = mapped_column(Boolean, default=False)
    poa_permissions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    poa_number: Mapped[str | None] = mapped_column(String(64))
    poa_valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
