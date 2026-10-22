"""Кредит и график платежей (50-06). Строки пишет `open_loan` по запросу выдачи, читает «Мои кредиты»."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base, IdMixin, TimestampMixin

LOAN_KINDS = ("LOAN", "CREDIT_LINE", "OVERDRAFT")
REPAYMENT_TYPES = ("ANNUITY", "BULLET", "REVOLVING")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Loan(IdMixin, TimestampMixin, Base):
    """Кредит нашего банка. Остаток долга равен выданной сумме: погашения не моделируем (7.5).

    У линии и овердрафта `principal_rub` = 0, а `limit_rub` — открытый лимит; графика нет (D-093).
    """

    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="status"),
        CheckConstraint(f"kind IN ({_in(LOAN_KINDS)})", name="kind"),
        CheckConstraint(f"repayment_type IN ({_in(REPAYMENT_TYPES)})", name="repayment_type"),
        UniqueConstraint("application_id", name="uq_loans_application_id"),
    )

    company_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("companies.id"), index=True)
    application_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("applications.id"))
    # Выдача живёт в другом модуле: связь по значению, без внешнего ключа между модулями
    disbursement_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    bank_core_loan_id: Mapped[str] = mapped_column(String(32))
    contract_number: Mapped[str] = mapped_column(String(64))
    contract_uid: Mapped[str] = mapped_column(String(64))
    product_code: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    repayment_type: Mapped[str] = mapped_column(String(16))
    principal_rub: Mapped[int] = mapped_column(BigInteger)
    limit_rub: Mapped[int | None] = mapped_column(BigInteger)
    outstanding_rub: Mapped[int] = mapped_column(BigInteger)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    term_months: Mapped[int] = mapped_column(Integer)
    payment_rub: Mapped[int | None] = mapped_column(BigInteger)
    loan_account: Mapped[str] = mapped_column(String(20))
    settlement_account: Mapped[str] = mapped_column(String(20))
    opened_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class PaymentScheduleRow(Base):
    """Строка графика. В MVP статус только `SCHEDULED`: оплату не отслеживаем (20-05)."""

    __tablename__ = "payment_schedule"
    __table_args__ = (
        UniqueConstraint("loan_id", "seq", name="uq_payment_schedule_loan_seq"),
        CheckConstraint("status IN ('SCHEDULED')", name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    loan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("loans.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    principal_rub: Mapped[int] = mapped_column(BigInteger)
    interest_rub: Mapped[int] = mapped_column(BigInteger)
    total_rub: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="SCHEDULED")
