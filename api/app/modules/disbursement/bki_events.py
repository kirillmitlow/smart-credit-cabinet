"""Сообщение `OBLIGATION_OPENED` для БКИ: payload в outbox и обратно в событие адаптера (моки 6.3).

В payload лежит всё, что нужно для события: обработчик ничего не берёт из базы и не меняет тело
при повторе, поэтому постоянный `eventId` и ключ дают исходный ответ БКИ.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.modules.disbursement import keys
from app.modules.disbursement.models import Disbursement
from app.modules.integrations import (
    BureauEvent,
    BureauEventType,
    BureauSubject,
    EventObligation,
)
from app.shared import clock


def build_payload(
    disbursement: Disbursement, payment_rub: int | None, opened_on: date, planned_close_at: date
) -> dict[str, Any]:
    inn = disbursement.customer_inn
    obligation: dict[str, Any] = {
        "uid": disbursement.contract_uid,
        "kind": disbursement.kind,
        "role": "BORROWER",
        "openedAt": opened_on.isoformat(),
        "plannedCloseAt": planned_close_at.isoformat(),
        "monthlyPaymentRub": payment_rub,
        "secured": False,
    }
    if disbursement.limit_rub is not None:
        obligation["limitRub"] = disbursement.limit_rub
    else:
        obligation["amountRub"] = disbursement.amount_rub
    return {
        "eventId": keys.obligation_event_id(disbursement.application_id),
        "occurredAt": clock.now().isoformat(),
        "subject": {"type": "LEGAL_ENTITY" if len(inn) == 10 else "PERSON", "inn": inn},
        "obligation": obligation,
    }


def event_from_payload(payload: dict[str, Any]) -> BureauEvent:
    subject = payload["subject"]
    o = payload["obligation"]
    return BureauEvent(
        event_id=payload["eventId"],
        event_type=BureauEventType.OBLIGATION_OPENED,
        occurred_at=datetime.fromisoformat(payload["occurredAt"]),
        subject=BureauSubject(subject["type"], subject["inn"]),
        obligation=EventObligation(
            uid=o["uid"],
            kind=o["kind"],
            role=o.get("role"),
            opened_at=date.fromisoformat(o["openedAt"]),
            planned_close_at=date.fromisoformat(o["plannedCloseAt"]),
            amount_rub=o.get("amountRub"),
            limit_rub=o.get("limitRub"),
            monthly_payment_rub=o.get("monthlyPaymentRub"),
            secured=o.get("secured"),
        ),
    )
