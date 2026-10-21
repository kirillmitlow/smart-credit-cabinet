"""Таблицы mock-registry (раздел 4.4): карточки ЕГРЮЛ/ЕГРИП, люди, роли и дела ЕФРСБ."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    BigInteger,
    Date,
    Float,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.common.db import OriginMixin


class Base(DeclarativeBase):
    """Своя метаданные у роли: миграции registry не видят таблиц других ролей."""


class Okved(Base):
    """Справочник кодов ОКВЭД: названия берутся отсюда, пополняется при записи карточки."""

    __tablename__ = "okved"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class Person(OriginMixin, Base):
    __tablename__ = "persons"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)
    # Субъект админ-API, чьим PUT записан человек (сам человек, если записан отдельно)
    owner_inn: Mapped[str] = mapped_column(String(12), index=True)
    last_name: Mapped[str] = mapped_column(Text)
    first_name: Mapped[str] = mapped_column(Text)
    middle_name: Mapped[str | None] = mapped_column(Text, default=None)
    birth_date: Mapped[date | None] = mapped_column(Date, default=None)


class Entity(OriginMixin, Base):
    __tablename__ = "entities"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    ogrn: Mapped[str] = mapped_column(String(15), unique=True)  # ОГРН или ОГРНИП
    kpp: Mapped[str | None] = mapped_column(String(9), default=None)
    person_inn: Mapped[str | None] = mapped_column(ForeignKey("persons.inn"), default=None)
    registration_date: Mapped[date] = mapped_column(Date)
    full_name: Mapped[str | None] = mapped_column(Text, default=None)
    short_name: Mapped[str | None] = mapped_column(Text, default=None)
    okopf_code: Mapped[str | None] = mapped_column(String(8), default=None)
    okopf_name: Mapped[str | None] = mapped_column(Text, default=None)
    status_code: Mapped[str] = mapped_column(String(16))
    status_name: Mapped[str] = mapped_column(Text)
    status_since: Mapped[date] = mapped_column(Date)
    pending_exclusion: Mapped[dict[str, str] | None] = mapped_column(JSONB, default=None)
    region_code: Mapped[str] = mapped_column(String(2))
    region_name: Mapped[str] = mapped_column(Text)
    address_full: Mapped[str | None] = mapped_column(Text, default=None)
    address_unreliable: Mapped[dict[str, str] | None] = mapped_column(JSONB, default=None)
    authorized_capital_rub: Mapped[int | None] = mapped_column(BigInteger, default=None)
    okved_main: Mapped[str] = mapped_column(String(10))
    okved_additional: Mapped[list[str]] = mapped_column(ARRAY(String(10)), default=list)
    tax_authority_code: Mapped[str] = mapped_column(String(4))
    tax_authority_name: Mapped[str] = mapped_column(Text)
    last_record_grn: Mapped[str] = mapped_column(String(15))
    last_record_date: Mapped[date] = mapped_column(Date)


class EntityRole(Base):
    """Руководитель и учредители организации."""

    __tablename__ = "entity_roles"
    __table_args__ = (Index("ix_entity_roles_person", "person_inn"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    entity_inn: Mapped[str] = mapped_column(
        ForeignKey("entities.inn", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # DIRECTOR | FOUNDER
    person_inn: Mapped[str | None] = mapped_column(ForeignKey("persons.inn"), default=None)
    founder_entity_inn: Mapped[str | None] = mapped_column(String(10), default=None)
    founder_name: Mapped[str | None] = mapped_column(Text, default=None)  # название учредителя-ЮЛ
    position: Mapped[str | None] = mapped_column(Text, default=None)
    share_percent: Mapped[float | None] = mapped_column(Float, default=None)
    share_nominal_rub: Mapped[int | None] = mapped_column(BigInteger, default=None)
    since: Mapped[date] = mapped_column(Date)
    unreliable: Mapped[dict[str, str] | None] = mapped_column(JSONB, default=None)
    position_order: Mapped[int] = mapped_column(default=0)  # порядок в карточке


class Bankruptcy(OriginMixin, Base):
    """Сведения ЕФРСБ. Субъект может не быть в entities (учредитель-человек)."""

    __tablename__ = "bankruptcies"
    __table_args__ = (UniqueConstraint("subject_inn", "case_number"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    subject_inn: Mapped[str] = mapped_column(String(12), index=True)
    subject_type: Mapped[str] = mapped_column(String(16))
    case_number: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[date] = mapped_column(Date)
    completed_at: Mapped[date | None] = mapped_column(Date, default=None)
