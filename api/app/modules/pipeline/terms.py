"""Условия последнего решения для других модулей (выдача берёт ставку и платёж отсюда).

Читать `decisions` чужим модулям нельзя (R5), поэтому здесь маленькая функция чтения.
Решение андеррайтера (`source = UNDERWRITER`) новее решения ядра и перекрывает его.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.pipeline.models import Decision


@dataclass(frozen=True, slots=True)
class DecisionTerms:
    decision_id: UUID
    outcome: str
    rate_percent: Decimal
    payment_rub: int | None
    max_amount_rub: int | None


def latest_terms(session: Session, application_id: UUID) -> DecisionTerms | None:
    """Ставка и платёж последнего решения с ценой; `None`, если решения с условиями нет."""
    row = session.scalars(
        select(Decision)
        .where(Decision.application_id == application_id, Decision.rate_percent.is_not(None))
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(1)
    ).first()
    if row is None or row.rate_percent is None:
        return None
    return DecisionTerms(row.id, row.outcome, row.rate_percent, row.payment_rub, row.max_amount_rub)
