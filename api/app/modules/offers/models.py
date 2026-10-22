"""Таблицы предложения, договора и подписей (50-06, T-340, T-341, T-263).

`offer_variants` и `signatures` неизменяемы: триггер БД запрещает UPDATE и DELETE (как журналы).
Условия варианта фиксируются в момент решения, подпись доказывает, что именно подписано.
`offers` и `contracts` меняются только статусом.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.db import Base, IdMixin

OFFER_KINDS = ("AS_REQUESTED", "COUNTER")
OFFER_STATUSES = ("OPEN", "ACCEPTED", "DECLINED", "EXPIRED")
VARIANTS_STATUSES = ("READY", "PENDING")
CONTRACT_STATUSES = ("READY", "SIGNED", "CANCELLED")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Offer(IdMixin, Base):
    """Предложение банка по решению: одно на решение (идемпотентность создания)."""

    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_offers_decision_id"),
        CheckConstraint(f"kind IN ({_in(OFFER_KINDS)})", name="kind"),
        CheckConstraint(f"status IN ({_in(OFFER_STATUSES)})", name="status"),
        CheckConstraint(f"variants_status IN ({_in(VARIANTS_STATUSES)})", name="variants_status"),
    )

    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    decision_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("decisions.id"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    # `PENDING`: запасное состояние, вариантов нет (встречное решения в норме несёт карточки T-297)
    variants_status: Mapped[str] = mapped_column(String(16), default="READY")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Без внешнего ключа: вариант создаётся после предложения, ссылку проверяет сервис
    accepted_variant_id: Mapped[UUID | None] = mapped_column(Uuid)
    accepted_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)


class OfferVariant(IdMixin, Base):
    """Карточка предложения (до трёх, D-072): условия, платёж и переплата посчитаны один раз."""

    __tablename__ = "offer_variants"
    __table_args__ = (UniqueConstraint("offer_id", "position", name="uq_offer_variants_position"),)

    offer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(120))
    product_code: Mapped[str] = mapped_column(String(32))
    amount_rub: Mapped[int] = mapped_column(BigInteger)
    term_months: Mapped[int] = mapped_column(Integer)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    payment_rub: Mapped[int] = mapped_column(BigInteger)
    last_payment_rub: Mapped[int] = mapped_column(BigInteger)
    overpayment_rub: Mapped[int] = mapped_column(BigInteger)
    collateral_required: Mapped[bool] = mapped_column(Boolean, default=False)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    what_changed: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Почему этот вариант: одна фраза клиенту (из снимка решения)
    note: Mapped[str] = mapped_column(Text, default="")


class Contract(IdMixin, Base):
    """Договор по принятому варианту. Тело хранится как есть, подписывается именно оно (20-04).

    PDF (T-336) в прототипе не делаем: `body` — детерминированный JSON, `content_hash` — его SHA-256.
    Правка условий = новая `revision`, прежний договор получает `CANCELLED`.
    """

    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("contract_uid", name="uq_contracts_contract_uid"),
        UniqueConstraint("number", name="uq_contracts_number"),
        UniqueConstraint("application_id", "revision", name="uq_contracts_revision"),
        CheckConstraint(f"status IN ({_in(CONTRACT_STATUSES)})", name="status"),
        Index(
            "uq_contracts_application_live",
            "application_id",
            unique=True,
            postgresql_where=text("status <> 'CANCELLED'"),
        ),
    )

    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("offers.id"))
    variant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("offer_variants.id"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # УИд договора в формате БКИ: `contractUid` в АБС = `uid` в БКИ (моки, 7.5)
    contract_uid: Mapped[str] = mapped_column(String(40))
    number: Mapped[str] = mapped_column(String(40))
    # Файла в хранилище пока нет (T-336): ссылка появится вместе с `documents`
    document_id: Mapped[UUID | None] = mapped_column(Uuid)
    template_version: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="READY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Signature(IdMixin, Base):
    """Простая электронная подпись договора (имитация, 20-04): HMAC-доказательство, не хеш кода."""

    __tablename__ = "signatures"
    __table_args__ = (
        UniqueConstraint("contract_id", "signer_user_id", name="uq_signatures_signer"),
        UniqueConstraint("contract_id", "attempt_id", name="uq_signatures_attempt"),
    )

    contract_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("contracts.id"), index=True)
    signer_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    signer_person_inn: Mapped[str | None] = mapped_column(String(12))
    signer_role: Mapped[str] = mapped_column(String(16))
    proof: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(32))
    # Код запроса подписи: повтор того же запроса возвращает эту подпись, а не создаёт вторую
    attempt_id: Mapped[str] = mapped_column(String(100))
    # Версия правил простой подписи, принятых подписантом (`pep-rules-v1`)
    consent_text_version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
