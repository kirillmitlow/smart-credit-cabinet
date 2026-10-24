# ruff: noqa: F811
"""T-279: таблица сообщений 20-05, атомарность, повторы и независимость АБС от БКИ."""

from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.modules import applications
from app.modules.applications.models import Application
from app.modules.applications.states import Actor, Status
from app.shared import clock, db, outbox
from app.shared.models import OutboxMessage
from tests.integration.test_applications import TERMS, sokolova, stand, submit  # noqa: F401 — фикстуры

pytestmark = pytest.mark.integration


def messages(application_id: str) -> list[OutboxMessage]:
    with db.transaction() as session:
        return list(
            session.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.aggregate_id == application_id)
                .order_by(OutboxMessage.id)
            )
        )


def move(application_id: str, target: Status, actor: Actor = Actor.SYSTEM) -> None:
    with db.transaction() as session:
        application = session.get(Application, UUID(application_id))
        applications.transition(session, application, target, actor=actor)


async def registered(client: httpx.AsyncClient) -> str:
    application_id = (await client.post("/applications", json=TERMS)).json()["id"]
    assert (await submit(client, application_id)).status_code == 200
    return application_id


@pytest.mark.parametrize(
    "outcome",
    [
        Status.APPROVED,
        Status.REJECTED,
        Status.MANUAL_REVIEW,
        Status.NEEDS_INFO,
        Status.COUNTER_OFFER,
    ],
)
async def test_messages_follow_outcomes_and_keep_original_request(
    sokolova: httpx.AsyncClient, outcome: Status
) -> None:
    application_id = await registered(sokolova)
    move(application_id, Status.CHECKING)
    move(application_id, outcome)
    rows = messages(application_id)
    assert rows[0].event_type == "APPLICATION_REGISTERED"
    assert rows[0].payload["application"] == {
        "ref": (await sokolova.get(f"/applications/{application_id}")).json()["number"],
        "kind": "LOAN",
        "amountRub": 500_000,
        "termMonths": 12,
    }
    assert rows[0].payload["subject"] == {"type": "PERSON", "inn": "001234567887"}
    if outcome in (Status.APPROVED, Status.REJECTED):
        assert len(rows) == 2
        assert rows[1].payload["application"]["decision"] == outcome.value
    else:
        assert len(rows) == 1


@pytest.mark.parametrize("terminal", [Status.WITHDRAWN, Status.EXPIRED])
async def test_counter_offer_is_reported_only_after_client_choice(
    sokolova: httpx.AsyncClient, terminal: Status
) -> None:
    application_id = await registered(sokolova)
    move(application_id, Status.CHECKING)
    move(application_id, Status.COUNTER_OFFER)
    move(application_id, terminal, Actor.CLIENT if terminal == Status.WITHDRAWN else Actor.SYSTEM)
    assert [r.payload["application"].get("decision") for r in messages(application_id)] == [
        None,
        "WITHDRAWN",
    ]


async def test_accepting_counter_then_withdrawing_produces_distinct_stable_decisions(
    sokolova: httpx.AsyncClient,
) -> None:
    application_id = await registered(sokolova)
    move(application_id, Status.CHECKING)
    move(application_id, Status.COUNTER_OFFER)
    with db.transaction() as session:
        application = session.get(Application, UUID(application_id))
        application.amount_rub, application.term_months = 300_000, 18
    move(application_id, Status.OFFER_ACCEPTED, Actor.CLIENT)
    assert (
        await sokolova.post(f"/applications/{application_id}/withdraw", json={"confirmed": True})
    ).status_code == 200
    before = messages(application_id)
    assert (
        await sokolova.post(f"/applications/{application_id}/withdraw", json={"confirmed": True})
    ).status_code == 200
    after = messages(application_id)
    assert [r.payload["application"].get("decision") for r in after] == [
        None,
        "APPROVED",
        "WITHDRAWN",
    ]
    assert [r.payload for r in after] == [r.payload for r in before]
    assert len({r.payload["eventId"] for r in after}) == 3
    assert all(r.idempotency_key.isascii() for r in after)
    assert after[0].payload["application"]["amountRub"] == 500_000
    assert after[0].payload["application"]["termMonths"] == 12


async def test_rollback_does_not_send_decision_or_change_status(
    sokolova: httpx.AsyncClient, stand: dict[str, Any]
) -> None:
    application_id = await registered(sokolova)
    move(application_id, Status.CHECKING)
    stand["sent"].clear()
    with pytest.raises(RuntimeError), db.transaction() as session:  # noqa: PT012 — проверяем откат транзакции
        application = session.get(Application, UUID(application_id))
        applications.transition(session, application, Status.REJECTED, actor=Actor.SYSTEM)
        raise RuntimeError("Откат")
    assert len(messages(application_id)) == 1
    assert stand["sent"] == []
    assert (await sokolova.get(f"/applications/{application_id}")).json()["status"] == "CHECKING"


async def test_bureau_outage_keeps_order_without_blocking_bank_core(
    sokolova: httpx.AsyncClient,
) -> None:
    application_id = await registered(sokolova)
    move(application_id, Status.CHECKING)
    move(application_id, Status.APPROVED)
    with db.transaction() as session:
        outbox.enqueue_outbox(
            session,
            aggregate_id=application_id,
            event_type="DISBURSEMENT",
            target="BANK_CORE",
            payload={},
            idempotency_key="bank-core-test",
        )
    seen: list[str] = []
    down = True

    def bureau(item: outbox.OutboxItem) -> outbox.Outcome:
        seen.append(item.event_type)
        return outbox.Retry("BKI_DOWN") if down else outbox.Delivered()

    outbox.clear_handlers()
    try:
        outbox.register_handler("BKI", "APPLICATION_REGISTERED", bureau)
        outbox.register_handler("BKI", "APPLICATION_DECIDED", bureau)
        outbox.register_handler("BANK_CORE", "DISBURSEMENT", lambda _: outbox.Delivered())
        first = outbox.relay(budget_s=2)
        assert (first.retried, first.delivered) == (1, 1)
        assert seen == ["APPLICATION_REGISTERED"]
        down = False
        message_id = messages(application_id)[0].id
        with db.transaction() as session:
            row = session.get(OutboxMessage, message_id)
            row.next_attempt_at = clock.system_now()
        second = outbox.relay(budget_s=2)
        assert second.delivered == 2
        assert seen == ["APPLICATION_REGISTERED", "APPLICATION_REGISTERED", "APPLICATION_DECIDED"]
    finally:
        outbox.clear_handlers()


async def test_failed_approval_cannot_be_replayed_after_a_later_withdrawal(
    sokolova: httpx.AsyncClient,
) -> None:
    application_id = await registered(sokolova)
    move(application_id, Status.CHECKING)
    move(application_id, Status.APPROVED)
    fail = True
    accepted: list[str] = []

    def bureau(item: outbox.OutboxItem) -> outbox.Outcome:
        decision = item.payload["application"].get("decision", "REGISTERED")
        if decision == "APPROVED" and fail:
            return outbox.Dead("BKI_RETRY_LIMIT")
        accepted.append(decision)
        return outbox.Delivered()

    outbox.clear_handlers()
    try:
        outbox.register_handler("BKI", "APPLICATION_REGISTERED", bureau)
        outbox.register_handler("BKI", "APPLICATION_DECIDED", bureau)
        assert outbox.relay(budget_s=2).failed == 1
        assert accepted == ["REGISTERED"]
        assert (
            await sokolova.post(
                f"/applications/{application_id}/withdraw", json={"confirmed": True}
            )
        ).status_code == 200
        assert outbox.relay(budget_s=2).handled == 0
        assert accepted == ["REGISTERED"]
        failed = messages(application_id)[1]
        fail = False
        with db.transaction() as session:
            assert outbox.retry_dead(session, failed.id)
        assert outbox.relay(budget_s=2).delivered == 2
        assert accepted == ["REGISTERED", "APPROVED", "WITHDRAWN"]
    finally:
        outbox.clear_handlers()
