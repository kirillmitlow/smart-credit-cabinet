"""Условия кредита, по которым делается выдача, и вид кредита по продукту (20-05, D-093).

Модуль `offers` (принятый вариант, договор) появится отдельной задачей. Пока условия читает
функция, которую регистрирует `app/wiring.py` (там заявка и решение конвейера): `disbursement`
с `pipeline` на одном уровне и друг друга не знают. Когда появится договор, заменяется только
эта функция; номер договора, УИд и время подписи она вправе вернуть сама.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class AgreedTerms:
    """Что согласовано с клиентом. Для линии и овердрафта `amount_rub` — лимит."""

    product_code: str
    amount_rub: int
    term_months: int
    rate_percent: Decimal
    contract_number: str | None = None
    contract_uid: str | None = None
    signed_at: datetime | None = None


type TermsProvider = Callable[[Session, UUID], AgreedTerms | None]

_provider: TermsProvider | None = None


def register_terms_provider(provider: TermsProvider | None) -> None:
    global _provider
    _provider = provider


def agreed_terms(session: Session, application_id: UUID) -> AgreedTerms | None:
    return _provider(session, application_id) if _provider else None


@dataclass(frozen=True, slots=True)
class Shape:
    """Вид кредита в АБС и способ погашения."""

    kind: str  # LOAN | CREDIT_LINE | OVERDRAFT
    repayment_type: str  # ANNUITY | BULLET | REVOLVING
    is_limit: bool  # открывается только лимит, денег не выдаём (D-093)


SHAPES: dict[str, Shape] = {
    "EXPRESS": Shape("LOAN", "ANNUITY", False),
    "WORKING_CAPITAL": Shape("LOAN", "ANNUITY", False),
    "INVESTMENT": Shape("LOAN", "ANNUITY", False),
    "CONTRACT": Shape("LOAN", "BULLET", False),
    "CREDIT_LINE": Shape("CREDIT_LINE", "REVOLVING", True),
    "OVERDRAFT": Shape("OVERDRAFT", "REVOLVING", True),
}


def shape_of(product_code: str) -> Shape:
    try:
        return SHAPES[product_code]
    except KeyError:
        raise ValueError(f"Неизвестный продукт: {product_code}") from None
