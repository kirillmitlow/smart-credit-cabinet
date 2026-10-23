"""Immutable source files and separately loaded metadata (T-332, 50-12)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.db import Base, IdMixin


class DocumentBlob(IdMixin, Base):
    __tablename__ = "document_blobs"
    content: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(Integer)


class Document(IdMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('BANK_STATEMENT_1C','FINANCIALS','CONTRACT','CREDIT_AGREEMENT',"
            "'PAYMENT_SCHEDULE','OTHER')",
            name="kind",
        ),
        CheckConstraint(
            "origin IN ('UPLOADED','DEMO_GENERATED','SYSTEM_GENERATED')", name="origin"
        ),
        CheckConstraint(
            "parse_status IN ('PENDING','PROCESSING','PARSED','FAILED','NOT_REQUIRED')",
            name="parse_status",
        ),
        CheckConstraint("size_bytes > 0", name="size_positive"),
    )
    company_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("companies.id"), index=True)
    application_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("applications.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"), index=True)
    storage_key: Mapped[UUID] = mapped_column(Uuid, ForeignKey("document_blobs.id"), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    origin: Mapped[str] = mapped_column(String(24))
    template_version: Mapped[str | None] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    parse_status: Mapped[str] = mapped_column(String(16))
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parse_error: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
