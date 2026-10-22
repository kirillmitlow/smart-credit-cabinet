"""Заявка, её версии и журнал событий (50-06). Статусы — строки с CHECK, не ENUM."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.applications.states import IN_PROGRESS, Status
from app.shared import clock
from app.shared.db import Base, IdMixin, TimestampMixin

_STATUSES = ", ".join(f"'{s.value}'" for s in Status)
_IN_PROGRESS = ", ".join(f"'{s.value}'" for s in sorted(IN_PROGRESS))


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUSES})", name="status"),
        CheckConstraint("amount_rub IS NULL OR amount_rub > 0", name="amount_positive"),
        # Одна заявка «в работе» на компанию — защита от дубля на уровне БД (20-02)
        Index(
            "uq_applications_company_in_progress",
            "company_id",
            unique=True,
            postgresql_where=text(f"status IN ({_IN_PROGRESS})"),
        ),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    company_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("companies.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    product_code: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default=Status.DRAFT.value)
    amount_rub: Mapped[int | None] = mapped_column(BigInteger)
    term_months: Mapped[int | None] = mapped_column(Integer)
    purpose_code: Mapped[str | None] = mapped_column(String(32))
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationVersion(IdMixin, Base):
    """Неизменяемая копия того, что именно оценивали."""

    __tablename__ = "application_versions"
    __table_args__ = (
        UniqueConstraint("application_id", "number", name="uq_application_versions_number"),
        CheckConstraint("reason IN ('SUBMIT', 'INFO_PROVIDED', 'COLLATERAL_ADDED')", name="reason"),
    )

    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)


class ApplicationEvent(Base):
    """Журнал заявки = аудит + таймлайн; id последовательный и служит Last-Event-ID для SSE."""

    __tablename__ = "application_events"
    __table_args__ = (
        CheckConstraint("kind IN ('TRANSITION', 'STEP', 'TASK', 'OVERRIDE', 'NOTE')", name="kind"),
        CheckConstraint("actor_type IN ('CLIENT', 'SYSTEM', 'UNDERWRITER')", name="actor_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    kind: Mapped[str] = mapped_column(String(16))
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    step_code: Mapped[str | None] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))


CONSENT_KINDS = ("BKI", "TURNOVER", "PERSONAL_DATA")
CONSENT_ROLES = ("COMPANY", "IP", "DIRECTOR", "OWNER", "GUARANTOR")
_KINDS = ", ".join(f"'{k}'" for k in CONSENT_KINDS)
_ROLES = ", ".join(f"'{r}'" for r in CONSENT_ROLES)


class Consent(IdMixin, Base):
    """Подписанное согласие (20-04, 50-06): версия и хеш текста, срок, доказательство подписи.

    Одно согласие = один субъект (ИНН) и один вид в одной заявке; на новую заявку не переносится
    (D-077). Записи не удаляются, отзыв — `revoked_at` (T-262).
    """

    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_KINDS})", name="kind"),
        CheckConstraint("subject_type IN ('COMPANY', 'PERSON')", name="subject_type"),
        CheckConstraint(f"role IN ({_ROLES})", name="role"),
        Index(
            "uq_consents_active_subject_kind",
            "application_id",
            "subject_inn",
            "kind",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    bundle_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    subject_inn: Mapped[str] = mapped_column(String(12))
    subject_type: Mapped[str] = mapped_column(String(8))
    role: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(32), default="LOAN_APPLICATION")
    text_version: Mapped[str] = mapped_column(String(64))
    text_hash: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    valid_until: Mapped[date] = mapped_column(Date)
    signer_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    signer_inn: Mapped[str | None] = mapped_column(String(12))
    sign_method: Mapped[str] = mapped_column(String(32), default="SIMPLE_ESIGN")
    proof: Mapped[str] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
