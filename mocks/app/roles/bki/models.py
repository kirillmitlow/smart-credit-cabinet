"""Таблицы mock_bki (раздел 6.4). Метаданные свои, не общие с другими ролями.

Хранятся даты и периоды, а не «сегодняшние» числа: summary, дни просрочки и корзины истории
платежей считаются при чтении (calc.py). Таблицу idempotency_keys ведёт общий слой.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.common.db import OriginMixin


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(), primary_key=True)


class Subject(OriginMixin, Base):
    __tablename__ = "subjects"

    id: Mapped[int] = _pk()
    type: Mapped[str] = mapped_column(String(16))  # LEGAL_ENTITY | PERSON
    inn: Mapped[str] = mapped_column(String(12), unique=True)
    ogrn: Mapped[str | None] = mapped_column(String(15))
    name: Mapped[str | None] = mapped_column(String(500))
    last_name: Mapped[str | None] = mapped_column(String(100))
    first_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    birth_date: Mapped[date | None] = mapped_column(Date)


class Obligation(OriginMixin, Base):
    __tablename__ = "obligations"

    id: Mapped[int] = _pk()
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    uid: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(16))
    opened_at: Mapped[date] = mapped_column(Date)
    planned_close_at: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[date | None] = mapped_column(Date)
    amount_rub: Mapped[int | None] = mapped_column(BigInteger)
    limit_rub: Mapped[int | None] = mapped_column(BigInteger)
    balance_rub: Mapped[int] = mapped_column(BigInteger, default=0)
    monthly_payment_rub: Mapped[int | None] = mapped_column(BigInteger)
    overdue_rub: Mapped[int] = mapped_column(BigInteger, default=0)
    # [{"since": "2026-07-18", "until": null}]; until = null у текущей просрочки
    overdue_periods: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(24))
    secured: Mapped[bool] = mapped_column(Boolean, default=False)
    # Только если история задана явно; иначе строится при чтении
    payment_history_fixed: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # reportId
    # inn добавлен к 6.4: по нему отчёты уходят вместе с субъектом, в том числе при NOT_FOUND
    inn: Mapped[str] = mapped_column(String(12), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(String(64))
    application_ref: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    consent: Mapped[dict[str, Any]] = mapped_column(JSONB)  # реквизиты согласия храним с отчётом
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)  # снимок ответа без meta


class Inquiry(OriginMixin, Base):
    __tablename__ = "inquiries"
    __table_args__ = (Index("ix_inquiries_inn_inquired_at", "inn", "inquired_at"),)

    id: Mapped[int] = _pk()
    inn: Mapped[str] = mapped_column(String(12))  # по ИНН: запрос пишется и при NOT_FOUND
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), index=True
    )
    inquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_name: Mapped[str | None] = mapped_column(String(200))
    user_type: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(64))
    is_own: Mapped[bool] = mapped_column(Boolean, default=False)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.id", ondelete="SET NULL"))


class ApplicationInfo(OriginMixin, Base):
    __tablename__ = "applications_info"
    __table_args__ = (UniqueConstraint("subject_id", "application_ref", name="uq_application_ref"),)

    id: Mapped[int] = _pk()
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    application_ref: Mapped[str] = mapped_column(String(64))
    applied_at: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))
    amount_rub: Mapped[int] = mapped_column(BigInteger)
    decision: Mapped[str] = mapped_column(String(16))
    decided_at: Mapped[date | None] = mapped_column(Date)
    is_own: Mapped[bool] = mapped_column(Boolean, default=False)


class Bankruptcy(OriginMixin, Base):
    __tablename__ = "bankruptcies"

    id: Mapped[int] = _pk()
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    case_number: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[date] = mapped_column(Date)
    completed_at: Mapped[date | None] = mapped_column(Date)
    stage: Mapped[str] = mapped_column(String(24))


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # submissionId
    event_id: Mapped[str] = mapped_column(String(200), unique=True)
    event_type: Mapped[str] = mapped_column(String(32))
    inn: Mapped[str] = mapped_column(String(12), index=True)  # добавлен к 6.4, как у reports
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
