"""Ключи идемпотентности и идентификаторы выдачи (20-05, 50-08).

Ключ уходит в HTTP-заголовок: только ASCII. Номер заявки кириллический («АЗ-2026-000001»),
поэтому ключи строятся из UUID заявки. Ключ строится по заявке, а не по попытке: тот же ключ
уходит при каждом повторе, в том числе после `LOST_RESPONSE`.
"""

from __future__ import annotations

from uuid import UUID

DISBURSEMENT_EVENT = "DISBURSEMENT"
OBLIGATION_EVENT = "OBLIGATION_OPENED"


def _ascii(value: str) -> str:
    if not value.isascii():
        raise ValueError("Ключ идемпотентности должен быть ASCII")
    return value


def account_key(application_id: UUID) -> str:
    """Открытие счёта: повтор не создаст второй счёт."""
    return _ascii(f"acc:{application_id}")


def disbursement_key(application_id: UUID) -> str:
    """Выдача: повтор после таймаута не выдаст деньги второй раз."""
    return _ascii(f"dsb:{application_id}")


def obligation_key(application_id: UUID) -> str:
    """Ключ outbox и `Idempotency-Key` сообщения `OBLIGATION_OPENED` в БКИ."""
    return _ascii(f"sub:{application_id}:{OBLIGATION_EVENT}")


def obligation_event_id(application_id: UUID) -> str:
    """Постоянный `eventId`: повтор события БКИ возвращает исходный ответ (мок 2.7)."""
    return _ascii(f"evt:{application_id}:{OBLIGATION_EVENT}")


def contract_uid(application_id: UUID) -> str:
    """УИд договора по умолчанию; он же `uid` обязательства в БКИ (7.5). Договор может задать свой."""
    return _ascii(f"{application_id}-1")
