"""T-365: повтор без новой доставки, аудит, откат, окно24ч и сброс компании."""

import asyncio
import threading
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.modules import applications, audit
from app.shared import clock, db, idempotency, operations, outbox, tasks
from app.shared.errors import AppError
from app.shared.models import IdempotencyKey, OutboxMessage
from tests.integration.test_backoffice_queue import bank as bank
from tests.integration.test_backoffice_queue import seed

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolated_outbox(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, dict[str, Any]]]:
    with db.transaction() as session:
        session.execute(text("TRUNCATE outbox, idempotency_keys RESTART IDENTITY"))
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: sent.append((name, kw)))
    return sent


def message(app_id: UUID, *, age: timedelta = timedelta(hours=1), status: str = "FAILED") -> int:
    with db.transaction() as session:
        row = OutboxMessage(
            aggregate_id=str(app_id),
            event_type="BANK_TEST",
            target_system="BANK_CORE",
            payload={"applicationId": str(app_id)},
            idempotency_key=f"original:{uuid4()}",
            status=status,
            attempts=30,
            last_error="SOURCE_UNAVAILABLE",
            created_at=clock.system_now() - age,
            next_attempt_at=clock.system_now(),
        )
        session.add(row)
        session.flush()
        return row.id


def status(message_id: int) -> str:
    with db.transaction() as session:
        row = session.get(OutboxMessage, message_id)
        assert row is not None
        return row.status


async def test_failed_list_filters_paginates_and_marks_unsafe_repeat(
    bank: httpx.AsyncClient,
) -> None:
    app_id, other = seed("Первая"), seed("Вторая")
    first, expired = message(app_id), message(app_id, age=timedelta(hours=25))
    message(other)
    message(app_id, status="PENDING")
    one = (
        await bank.get("/backoffice/outbox", params={"applicationId": str(app_id), "limit": 1})
    ).json()
    assert one["items"][0]["id"] == first
    assert one["items"][0]["canRetry"] is True
    two = (
        await bank.get(
            "/backoffice/outbox", params={"applicationId": str(app_id), "cursor": one["nextCursor"]}
        )
    ).json()
    assert [x["id"] for x in two["items"]] == [expired]
    assert two["items"][0]["blockedReason"] == "EXPIRED"
    assert two["nextCursor"] is None


async def test_retry_audit_replay_and_delivery_keep_original_receiver_key(
    bank: httpx.AsyncClient,
    isolated_outbox: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_id = seed("Первая")
    mid = message(app_id)
    with db.transaction() as session:
        original = session.get(OutboxMessage, mid)
        assert original is not None
        key, created = original.idempotency_key, original.created_at
        assert outbox.count_dead(session) == 1
    first = await bank.post(
        f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "same-action"}
    )
    assert first.status_code == 200
    assert first.json() == {"id": mid, "applicationId": str(app_id), "status": "PENDING"}
    replay = await bank.post(
        f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "same-action"}
    )
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    second_action = await bank.post(
        f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "new-action"}
    )
    assert second_action.status_code == 409
    assert second_action.json()["code"] == "OUTBOX_NOT_FAILED"
    assert isolated_outbox == [(outbox.RELAY_TASK, {})]
    with db.transaction() as session:
        assert outbox.count_dead(session) == 0
        assert (
            len(
                session.scalars(
                    select(audit.AuditRecord).where(audit.AuditRecord.action == "OUTBOX_RETRY")
                ).all()
            )
            == 1
        )
        row = session.get(OutboxMessage, mid)
        assert row is not None
        assert row.idempotency_key == key
        assert row.created_at == created
    delivered: list[str] = []
    monkeypatch.setattr(outbox, "_handlers", dict(outbox._handlers))
    outbox.register_handler(
        "BANK_CORE",
        "BANK_TEST",
        lambda item: (delivered.append(item.idempotency_key), outbox.Delivered())[1],
    )
    assert outbox.relay().delivered == 1
    assert delivered == [key]
    assert status(mid) == "SENT"


@pytest.mark.parametrize("age", [timedelta(days=1), timedelta(days=2)])
async def test_expired_retry_is_forbidden_without_cache_audit_or_enqueue(
    bank: httpx.AsyncClient, isolated_outbox: list[tuple[str, dict[str, Any]]], age: timedelta
) -> None:
    mid = message(seed("Первая"), age=age)
    response = await bank.post(
        f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "expired"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "OUTBOX_RETRY_EXPIRED"
    assert status(mid) == "FAILED"
    assert isolated_outbox == []
    with db.transaction() as session:
        assert session.scalars(select(IdempotencyKey)).all() == []


async def test_two_requests_with_same_key_receive_in_progress_and_one_result(
    bank: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mid = message(seed("Первая"))
    entered, release = threading.Event(), threading.Event()
    original = outbox.retry_dead

    def paused(*args: Any, **kwargs: Any) -> bool:
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(outbox, "retry_dead", paused)
    first = asyncio.create_task(
        bank.post(f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "concurrent"})
    )
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        second = await bank.post(
            f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "concurrent"}
        )
        assert second.status_code == 409
        assert second.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
    finally:
        release.set()
    assert (await first).status_code == 200


async def test_audit_failure_rolls_back_retry_and_key_and_sends_no_task(
    bank: httpx.AsyncClient,
    isolated_outbox: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mid = message(seed("Первая"))

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError, match="audit failed"):
        await bank.post(f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "rollback"})
    assert status(mid) == "FAILED"
    assert isolated_outbox == []
    with db.transaction() as session:
        assert session.scalars(select(IdempotencyKey)).all() == []


async def test_lost_reply_after_commit_replays_without_a_second_effect(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mid = message(seed("Первая"))

    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("broker unavailable after commit")

    monkeypatch.setattr(tasks, "send_now", unavailable)
    with pytest.raises(RuntimeError, match="broker unavailable after commit"):
        await bank.post(
            f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "lost-reply"}
        )
    assert status(mid) == "PENDING"
    replay = await bank.post(
        f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "lost-reply"}
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"


async def test_company_reset_blocks_retry_before_any_write(bank: httpx.AsyncClient) -> None:
    app_id = seed("Первая")
    mid = message(app_id)
    scope = applications.operation_scope(app_id)
    assert scope is not None
    with operations.hold(lambda: scope, exclusive=True):
        result = await bank.post(
            f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "reset"}
        )
    assert result.status_code == 409
    assert result.json()["code"] == "DEMO_RESET_IN_PROGRESS"
    assert status(mid) == "FAILED"


async def test_missing_header_unexpected_body_and_client_role_are_rejected(
    bank: httpx.AsyncClient,
) -> None:
    mid = message(seed("Первая"))
    assert (await bank.post(f"/backoffice/outbox/{mid}/retry")).status_code == 422
    assert (
        await bank.post(
            f"/backoffice/outbox/{mid}/retry",
            headers={"Idempotency-Key": "extra"},
            json={"newKey": "bypass"},
        )
    ).status_code == 422
    bank.cookies.clear()
    assert (await bank.get("/backoffice/outbox")).status_code == 401
    assert (
        await bank.post(f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "client"})
    ).status_code == 401


async def test_orphan_message_is_visible_but_cannot_be_delivered(bank: httpx.AsyncClient) -> None:
    mid = message(uuid4())
    item = (await bank.get("/backoffice/outbox")).json()["items"][0]
    assert item["applicationId"] is None
    assert item["blockedReason"] == "APPLICATION_MISSING"
    assert (
        await bank.post(f"/backoffice/outbox/{mid}/retry", headers={"Idempotency-Key": "orphan"})
    ).status_code == 404


def test_public_http_cache_rejects_key_reuse_for_different_request() -> None:
    with db.transaction() as session:
        first = idempotency.run_once(
            session,
            scope="test",
            key="one",
            request={"x": 1},
            action=lambda: idempotency.Reply(200, {"ok": True}),
        )
    assert first.replayed is False
    with pytest.raises(AppError) as error, db.transaction() as session:
        idempotency.run_once(
            session,
            scope="test",
            key="one",
            request={"x": 2},
            action=lambda: idempotency.Reply(200, {"ok": False}),
        )
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
