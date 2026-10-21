"""Учётные записи (50-06): клиенты из блока users сценариев и сотрудники банка."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('CLIENT', 'UNDERWRITER', 'ADMIN')", name="role"),
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="status"),
    )

    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    person_inn: Mapped[str | None] = mapped_column(String(12), index=True)
    login_ref: Mapped[str] = mapped_column(String(100), unique=True)
    scenario_code: Mapped[str | None] = mapped_column(String(64), index=True)


UserId = UUID
