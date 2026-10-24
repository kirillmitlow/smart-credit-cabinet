"""T-279: доставка повторяет сохранённое событие и различает временный сбой и дефект."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.applications import bureau_lifecycle as lifecycle
from app.modules.integrations import (
    BureauEvent,
    Ok,
    Reason,
    SnapshotMeta,
    SourceUnavailable,
    System,
)
from app.shared.outbox import Dead, Defer, Delivered, OutboxItem, Retry

pytestmark = pytest.mark.unit
AT = datetime(2026, 10, 21, 10, tzinfo=UTC)
META = SnapshotMeta(System.CREDIT_BUREAU, None, None, AT)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (Ok(None, META), Delivered),
        (SourceUnavailable(System.CREDIT_BUREAU, Reason.HTTP_5XX, status_code=503), Retry),
        (SourceUnavailable(System.CREDIT_BUREAU, Reason.CIRCUIT_OPEN), Defer),
        (SourceUnavailable(System.CREDIT_BUREAU, Reason.REJECTED, status_code=422), Dead),
    ],
)
def test_delivery_preserves_event_id_payload_time_and_request_key(
    monkeypatch: pytest.MonkeyPatch, response: Any, expected: type
) -> None:
    application_id = uuid4()
    key = lifecycle.event_key(application_id, lifecycle.DECIDED, "WITHDRAWN")
    item = OutboxItem(
        id=1,
        aggregate_id=str(application_id),
        event_type=lifecycle.DECIDED,
        target_system="BKI",
        idempotency_key=key,
        attempts=0,
        lease_until=AT,
        created_at=AT,
        payload={
            "eventId": f"evt:{application_id}:APPLICATION_DECIDED:WITHDRAWN",
            "eventType": "APPLICATION_DECIDED",
            "occurredAt": AT.isoformat(),
            "subject": {"type": "LEGAL_ENTITY", "inn": "0017654322"},
            "application": {"ref": "АЗ-2026-000001", "decision": "WITHDRAWN"},
        },
    )
    sent: list[tuple[BureauEvent, dict[str, Any]]] = []

    def submit(event: BureauEvent, **kwargs: Any) -> Any:
        sent.append((event, kwargs))
        return response

    monkeypatch.setattr(
        lifecycle,
        "get_integrations",
        lambda: SimpleNamespace(credit_bureau=SimpleNamespace(submit_event=submit)),
    )
    assert isinstance(lifecycle.deliver(item), expected)
    assert isinstance(lifecycle.deliver(item), expected)
    assert sent[0] == sent[1]
    event, options = sent[0]
    assert event.occurred_at == AT
    assert event.event_id == item.payload["eventId"]
    assert event.application.decision == "WITHDRAWN"
    assert options == {"idempotency_key": key, "application_id": application_id}
