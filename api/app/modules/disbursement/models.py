"""Выдача в АБС (50-06): одна строка на заявку, уникальный `application_id` (INV-83)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base, IdMixin, TimestampMixin

STATUSES = ("PENDING", "SENT", "CONFIRMED", "FAILED")


class Disbursement(IdMixin, TimestampMixin, Base):
    """Запрос на выдачу и его итог.

    Тело запроса в АБС целиком хранится здесь: повтор с тем же ключом обязан уйти с тем же телом,
    иначе мок ответит `409 IDEMPOTENCY_KEY_REUSED`. `FAILED` — остановка до решения человека
    (счёт заблокирован, расхождение суммы, наш дефект); заявка при этом остаётся `DISBURSING`.
    """

    __tablename__ = "disbursements"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_disbursements_application_id"),
        CheckConstraint("status IN ('PENDING', 'SENT', 'CONFIRMED', 'FAILED')", name="status"),
    )

    application_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("applications.id"))
    company_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("companies.id"), index=True)
    application_ref: Mapped[str] = mapped_column(String(64))
    customer_inn: Mapped[str] = mapped_column(String(12))
    contract_number: Mapped[str] = mapped_column(String(64))
    contract_uid: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    product_code: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    repayment_type: Mapped[str] = mapped_column(String(16))
    amount_rub: Mapped[int] = mapped_column(BigInteger)
    limit_rub: Mapped[int | None] = mapped_column(BigInteger)
    term_months: Mapped[int] = mapped_column(Integer)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    account_number: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    idempotency_key: Mapped[str] = mapped_column(String(200))
    bank_core_ref: Mapped[str | None] = mapped_column(String(32))
    loan_account: Mapped[str | None] = mapped_column(String(20))
    value_date: Mapped[date | None] = mapped_column(Date)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
