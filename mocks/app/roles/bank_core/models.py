"""Хранение mock-bank-core (раздел 7.7): клиенты, счета, обороты, кредиты, проводки, комплаенс."""

from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Sequence, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.common.db import OriginMixin

# Ссудный счёт берёт порядковый номер кредита (loan_000041 → ...0000041), расчётный — свой счётчик.
# Последовательности создаёт миграция вручную: Alembic их сам не видит.
loan_id_seq = Sequence("bank_core_loan_id_seq")
settlement_serial_seq = Sequence("bank_core_settlement_serial_seq")


class Base(DeclarativeBase):
    """Свой набор метаданных роли: с другими моками не пересекается."""


class Customer(OriginMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, sa.Identity(), primary_key=True)
    inn: Mapped[str] = mapped_column(String(12), unique=True)
    type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(300))
    customer_since: Mapped[date] = mapped_column(Date)


class Account(OriginMixin, Base):
    __tablename__ = "accounts"

    number: Mapped[str] = mapped_column(String(20), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # SETTLEMENT | LOAN
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    status: Mapped[str] = mapped_column(String(16))  # OPEN | BLOCKED | CLOSED
    opened_at: Mapped[date] = mapped_column(Date)
    balance_rub: Mapped[int] = mapped_column(BigInteger, default=0)


class MonthlyTurnover(OriginMixin, Base):
    __tablename__ = "monthly_turnover"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)  # первое число месяца
    incoming_rub: Mapped[int] = mapped_column(BigInteger)
    incoming_net_rub: Mapped[int] = mapped_column(BigInteger)
    outgoing_rub: Mapped[int] = mapped_column(BigInteger)
    counterparties_in: Mapped[int]
    counterparties_out: Mapped[int]


class Loan(OriginMixin, Base):
    """Кредит нашего банка.

    Деньги дважды не уходят благодаря уникальным ключам: одна выдача на заявку, на УИд и на номер
    договора, даже если запросы пришли с разными ключами идемпотентности.
    """

    __tablename__ = "loans"
    __table_args__ = (
        sa.UniqueConstraint("application_ref", name="uq_loans_application_ref"),
        sa.UniqueConstraint("contract_uid", name="uq_loans_contract_uid"),
        sa.UniqueConstraint("contract_number", name="uq_loans_contract_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    application_ref: Mapped[str] = mapped_column(String(64))
    contract_number: Mapped[str] = mapped_column(String(64))
    contract_uid: Mapped[str] = mapped_column(String(64))
    product_code: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    amount_rub: Mapped[int] = mapped_column(BigInteger)
    limit_rub: Mapped[int | None] = mapped_column(BigInteger)
    term_months: Mapped[int]
    rate_percent: Mapped[float] = mapped_column(sa.Float)
    repayment_type: Mapped[str] = mapped_column(String(16))
    loan_account: Mapped[str] = mapped_column(ForeignKey("accounts.number"))
    settlement_account: Mapped[str] = mapped_column(ForeignKey("accounts.number"))
    status: Mapped[str] = mapped_column(String(16))
    disbursed_at: Mapped[date] = mapped_column(Date)


class Posting(Base):
    """Проводки, которые делает симулятор (только выдача)."""

    __tablename__ = "postings"

    id: Mapped[int] = mapped_column(BigInteger, sa.Identity(), primary_key=True)
    debit_account: Mapped[str] = mapped_column(String(20), index=True)
    credit_account: Mapped[str] = mapped_column(String(20), index=True)
    amount_rub: Mapped[int] = mapped_column(BigInteger)
    purpose: Mapped[str] = mapped_column(Text)
    value_date: Mapped[date] = mapped_column(Date)
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComplianceEntry(OriginMixin, Base):
    """Перечень Росфинмониторинга (AML) и внутренний стоп-лист: по одной записи на ИНН и вид."""

    __tablename__ = "compliance_lists"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)
    list_type: Mapped[str] = mapped_column(String(16), primary_key=True)  # AML | INTERNAL_STOP
    list_name: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[date] = mapped_column(Date)


class ZskRating(OriginMixin, Base):
    __tablename__ = "zsk_ratings"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)
    risk_level: Mapped[str] = mapped_column(String(8))  # GREEN | YELLOW | RED
    assessed_at: Mapped[date] = mapped_column(Date)
