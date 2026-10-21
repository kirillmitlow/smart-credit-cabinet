"""Таблицы mock-tax (раздел 5.7).

Кроме таблиц из спецификации есть `tax_subjects`: субъект админ-API (ИНН) с `origin` и
`scenario_code`. Он нужен, потому что у субъекта может не быть налогового профиля (самозанятый
Орлов — только статус НПД), а сценарий всё равно должен уметь удалить его целиком.
Остальные таблицы ссылаются на него с `ON DELETE CASCADE`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.common.db import OriginMixin


def subject_fk() -> ForeignKey:
    return ForeignKey("tax_subjects.inn", ondelete="CASCADE")


class Base(DeclarativeBase):
    """Своя метаданные у роли: миграции tax не видят таблиц других ролей."""


class TaxSubject(OriginMixin, Base):
    __tablename__ = "tax_subjects"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)


class TaxProfile(Base):
    __tablename__ = "tax_profiles"

    inn: Mapped[str] = mapped_column(subject_fk(), primary_key=True)
    tax_regimes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # [{code, year}]
    avg_headcount: Mapped[int | None] = mapped_column(Integer, default=None)
    headcount_year: Mapped[int | None] = mapped_column(Integer, default=None)
    tax_debt_rub: Mapped[int] = mapped_column(BigInteger)
    penalties_rub: Mapped[int] = mapped_column(BigInteger)
    fines_rub: Mapped[int] = mapped_column(BigInteger)
    debts_as_of: Mapped[date] = mapped_column(Date)
    income_rub: Mapped[int | None] = mapped_column(BigInteger, default=None)
    expenses_rub: Mapped[int | None] = mapped_column(BigInteger, default=None)
    income_year: Mapped[int | None] = mapped_column(Integer, default=None)
    tax_offenses: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    risk_flags: Mapped[dict[str, bool]] = mapped_column(JSONB)


class TaxPaid(Base):
    __tablename__ = "taxes_paid"

    inn: Mapped[str] = mapped_column(subject_fk(), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    total_rub: Mapped[int] = mapped_column(BigInteger)


class FinancialStatement(Base):
    """Одна строка на год; `previous` в ответе берётся из строки предыдущего года."""

    __tablename__ = "financial_statements"

    inn: Mapped[str] = mapped_column(subject_fk(), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    form_type: Mapped[str] = mapped_column(String(16))
    submitted_at: Mapped[date] = mapped_column(Date)
    lines: Mapped[dict[str, int]] = mapped_column(JSONB)  # {"2110": 420000000, ...}


class SmeRegistry(Base):
    """Только те, кто в реестре: нет строки — `inRegistry: false`."""

    __tablename__ = "sme_registry"

    inn: Mapped[str] = mapped_column(subject_fk(), primary_key=True)
    category: Mapped[str] = mapped_column(String(8))
    included_at: Mapped[date] = mapped_column(Date)
    is_newly_created: Mapped[bool] = mapped_column(Boolean)
    is_social_enterprise: Mapped[bool] = mapped_column(Boolean)


class NpdStatus(Base):
    """Только самозанятые: нет строки — не плательщик НПД."""

    __tablename__ = "npd_status"

    inn: Mapped[str] = mapped_column(subject_fk(), primary_key=True)
    registered_at: Mapped[date] = mapped_column(Date)
    deregistered_at: Mapped[date | None] = mapped_column(Date, default=None)


class AccountBlock(Base):
    __tablename__ = "account_blocks"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    inn: Mapped[str] = mapped_column(subject_fk(), index=True)
    number: Mapped[str] = mapped_column(Text)
    decision_date: Mapped[date] = mapped_column("date", Date)
    tax_authority_code: Mapped[str] = mapped_column(String(4))
    bik: Mapped[str] = mapped_column(String(9))
    reason: Mapped[str] = mapped_column(String(40))
    lifted_at: Mapped[date | None] = mapped_column(Date, default=None)


class PublicContract(Base):
    __tablename__ = "public_contracts"

    registry_number: Mapped[str] = mapped_column(String(19), primary_key=True)
    supplier_inn: Mapped[str] = mapped_column(subject_fk(), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # порядок в теле админ-API
    customer_name: Mapped[str] = mapped_column(Text)
    customer_inn: Mapped[str] = mapped_column(String(10))
    subject: Mapped[str] = mapped_column(Text)
    price_rub: Mapped[int] = mapped_column(BigInteger)
    concluded_at: Mapped[date] = mapped_column(Date)
    execution_deadline: Mapped[date] = mapped_column(Date)
    payment_deadline: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    paid_rub: Mapped[int] = mapped_column(BigInteger)
