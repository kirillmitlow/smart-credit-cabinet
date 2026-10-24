"""События заявки для БКИ: снимок в той же транзакции, доставка через outbox (T-279, 20-05).

Переходы до подписи могут породить APPROVED, затем отдельный WITHDRAWN. Их eventId различны;
повтор одного исхода сохраняет прежние тело, время и ключ. MANUAL_REVIEW/NEEDS_INFO/встречное
не передаются. Уже существовавшие заявки без регистрации не получают отдельного DECIDED.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import companies
from app.modules.applications.models import Application
from app.modules.applications.operations import hold
from app.modules.applications.states import Status
from app.modules.integrations import (
    BureauEvent,
    BureauEventType,
    BureauSubject,
    EventApplication,
    Failure,
    Ok,
    classify_failure,
    get_integrations,
)
from app.shared import clock, outbox
from app.shared.models import OutboxMessage
from app.shared.outbox import Dead, Defer, Delivered, OutboxItem, Outcome, Retry

BKI = "BKI"
REGISTERED = "APPLICATION_REGISTERED"
DECIDED = "APPLICATION_DECIDED"


def event_key(application_id: UUID, event_type: str, decision: str | None = None) -> str:
    suffix = f":{decision}" if decision else ""
    return f"sub:{application_id}:{event_type}{suffix}"


def on_transition(
    session: Session, application: Application, source: Status, target: Status
) -> None:
    decision: str | None = None
    if target == Status.SUBMITTED:
        event_type = REGISTERED
    else:
        if target in (Status.APPROVED, Status.REJECTED):
            decision = target.value
        elif target == Status.OFFER_ACCEPTED and source == Status.COUNTER_OFFER:
            decision = "APPROVED"
        elif target in (Status.WITHDRAWN, Status.EXPIRED):
            decision = "WITHDRAWN"
        if decision is None:
            return
        # Старые заявки / внутренние черновые записи могли появиться до подключения БКИ.
        # Не посылаем решение без предшествующей регистрации у получателя.
        if (
            session.scalar(
                select(OutboxMessage.id).where(
                    OutboxMessage.idempotency_key == event_key(application.id, REGISTERED)
                )
            )
            is None
        ):
            return
        event_type = DECIDED
    company = companies.by_id(session, application.company_id)
    if company is None:
        raise ValueError("У заявки отсутствует компания")
    details: dict[str, str | int | None] = {"ref": application.number}
    if decision is not None:
        details["decision"] = decision
    else:
        details.update(
            kind=application.product_code
            if application.product_code in ("CREDIT_LINE", "OVERDRAFT")
            else "LOAN",
            amountRub=application.amount_rub,
            termMonths=application.term_months,
        )
    key = event_key(application.id, event_type, decision)
    outbox.enqueue_outbox(
        session,
        aggregate_id=str(application.id),
        event_type=event_type,
        target=BKI,
        idempotency_key=key,
        payload={
            "eventId": "evt:" + key.removeprefix("sub:"),
            "eventType": event_type,
            "occurredAt": clock.now().isoformat(),
            "subject": {
                "type": "LEGAL_ENTITY" if len(company.inn) == 10 else "PERSON",
                "inn": company.inn,
            },
            "application": details,
        },
    )


def deliver(item: OutboxItem) -> Outcome:
    payload = item.payload
    application = payload["application"]
    subject = payload["subject"]
    event = BureauEvent(
        event_id=payload["eventId"],
        event_type=BureauEventType(payload["eventType"]),
        occurred_at=datetime.fromisoformat(payload["occurredAt"]),
        subject=BureauSubject(subject["type"], subject["inn"]),
        application=EventApplication(
            ref=application["ref"],
            kind=application.get("kind"),
            amount_rub=application.get("amountRub"),
            term_months=application.get("termMonths"),
            decision=application.get("decision"),
        ),
    )
    result = get_integrations().credit_bureau.submit_event(
        event, idempotency_key=item.idempotency_key, application_id=UUID(item.aggregate_id)
    )
    if isinstance(result, Ok):
        return Delivered()
    kind = classify_failure(result)
    error = result.error_code or result.reason.value
    if kind == Failure.DEFER:
        return Defer(error=error)
    return Retry(error) if kind == Failure.RETRY else Dead(error)


@contextmanager
def _guard(item: OutboxItem) -> Iterator[bool]:
    with hold(UUID(item.aggregate_id)) as scope:
        yield scope is not None


def register_bureau_handlers() -> None:
    for event_type in (REGISTERED, DECIDED):
        outbox.register_handler(BKI, event_type, deliver, guard=_guard)
