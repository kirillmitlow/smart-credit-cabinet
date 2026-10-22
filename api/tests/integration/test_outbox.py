"""T-278: outbox и ретранслятор на настоящем Postgres: порядок, аренда, паузы, FAILED, параллельность."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text, update

from app.shared import clock, db, outbox, tasks
from app.shared.models import OutboxMessage
from app.shared.outbox import Dead, Defer, Delivered, OutboxItem, Outcome, Retry

# ruff: noqa: PT018, PT012
pytestmark = pytest.mark.integration

TARGET, KIND = "BKI", "TEST_EVENT"


@pytest.fixture
def database(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    pushes: list[str] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: pushes.append(name))
    database = db.configure(postgres_url)
    db.migrate(database.engine)
    with database.transaction() as s:
        s.execute(text("TRUNCATE outbox"))
    outbox.clear_handlers()
    outbox.set_dead_letter_hook(None)
    yield pushes
    outbox.clear_handlers()
    outbox.set_dead_letter_hook(None)
    database.dispose()


def put(aggregate: str, key: str, **kw: Any) -> None:
    with db.transaction() as s:
        outbox.enqueue_outbox(
            s,
            aggregate_id=aggregate,
            event_type=KIND,
            target=TARGET,
            payload={"n": key},
            idempotency_key=key,
            **kw,
        )


def rows() -> list[OutboxMessage]:
    with db.transaction() as s:
        return list(s.scalars(select(OutboxMessage).order_by(OutboxMessage.id)))


def make_due() -> None:
    with db.transaction() as s:
        s.execute(update(OutboxMessage).values(next_attempt_at=clock.system_now()))


def test_enqueue_is_idempotent_pushes_once_and_rolls_back(database: list[str]) -> None:
    with db.transaction() as s:
        assert outbox.enqueue_outbox(
            s, aggregate_id="a", event_type=KIND, target=TARGET, payload={}, idempotency_key="k1"
        )
        assert not outbox.enqueue_outbox(
            s, aggregate_id="a", event_type=KIND, target=TARGET, payload={}, idempotency_key="k1"
        )
        outbox.enqueue_outbox(
            s, aggregate_id="a", event_type=KIND, target=TARGET, payload={}, idempotency_key="k2"
        )
    assert len(rows()) == 2
    assert database == ["outbox.relay"]  # один толчок на транзакцию, после коммита

    database.clear()
    with pytest.raises(RuntimeError), db.transaction() as s:
        outbox.enqueue_outbox(
            s, aggregate_id="b", event_type=KIND, target=TARGET, payload={}, idempotency_key="k3"
        )
        raise RuntimeError("откат")
    assert [r.idempotency_key for r in rows()] == ["k1", "k2"]  # откат убрал и запись
    assert database == []  # и толчок


def test_relay_delivers_in_order_per_aggregate(database: list[str]) -> None:
    seen: list[str] = []

    def handler(item: OutboxItem) -> Outcome:
        seen.append(item.idempotency_key)
        return Delivered()

    outbox.register_handler(TARGET, KIND, handler)
    for key in ("a1", "b1", "a2", "a3"):
        put(key[0], key)
    stats = outbox.relay(budget_s=5)
    assert stats.delivered == 4
    assert [k for k in seen if k[0] == "a"] == ["a1", "a2", "a3"]
    assert {r.status for r in rows()} == {"SENT"}


def test_failed_message_holds_later_ones_of_same_aggregate_only(database: list[str]) -> None:
    seen: list[str] = []

    def handler(item: OutboxItem) -> Outcome:
        seen.append(item.idempotency_key)
        return Retry("boom") if item.idempotency_key == "a1" else Delivered()

    outbox.register_handler(TARGET, KIND, handler)
    for key in ("a1", "a2", "b1"):
        put(key[0], key)
    outbox.relay(budget_s=5)
    assert seen == ["a1", "b1"]  # a2 ждёт a1, b1 ей не мешает
    first = rows()[0]
    assert first.attempts == 1 and first.status == "PENDING"
    assert first.next_attempt_at > clock.system_now() + timedelta(seconds=3)  # пауза ~5 с


def test_retry_counts_attempts_but_defer_does_not(database: list[str]) -> None:
    answers: list[Outcome] = [Defer(30), Retry("e"), Retry("e")]
    outbox.register_handler(TARGET, KIND, lambda item: answers.pop(0))
    put("a", "k")
    outbox.relay(budget_s=5)
    assert rows()[0].attempts == 0  # предохранитель: попытка не потрачена
    for expected in (1, 2):
        make_due()
        outbox.relay(budget_s=5)
        assert rows()[0].attempts == expected


def test_failed_after_max_attempts_and_hook_called(database: list[str]) -> None:
    hooked: list[tuple[int, str]] = []
    outbox.set_dead_letter_hook(lambda session, item, error: hooked.append((item.id, error)))
    outbox.register_handler(TARGET, KIND, lambda item: Retry("still down"))
    put("a", "k")
    with db.transaction() as s:
        s.execute(update(OutboxMessage).values(attempts=outbox.MAX_ATTEMPTS - 1))
    stats = outbox.relay(budget_s=5)
    assert stats.failed == 1
    row = rows()[0]
    assert row.status == "FAILED" and row.last_error == "still down"
    assert hooked == [(row.id, "still down")]
    with db.transaction() as s:
        assert outbox.count_dead(s) == 1


def test_expired_message_is_not_sent_or_manually_restarted(database: list[str]) -> None:
    calls: list[int] = []
    outbox.register_handler(TARGET, KIND, lambda item: calls.append(item.id) or Delivered())
    put("a", "k")
    with db.transaction() as s:
        s.execute(update(OutboxMessage).values(created_at=clock.system_now() - timedelta(days=2)))
    outbox.relay(budget_s=5)
    assert rows()[0].status == "FAILED"
    assert rows()[0].last_error == "RETRY_WINDOW_EXPIRED"
    assert calls == []
    with db.transaction() as s:
        assert not outbox.retry_dead(s, rows()[0].id)


def test_manual_retry_within_window_preserves_original_age(database: list[str]) -> None:
    outbox.register_handler(TARGET, KIND, lambda item: Dead("bad"))
    put("a", "k")
    created_at = rows()[0].created_at
    outbox.relay(budget_s=5)
    with db.transaction() as s:
        assert outbox.retry_dead(s, rows()[0].id)
    outbox.register_handler(TARGET, KIND, lambda item: Delivered())
    assert outbox.relay(budget_s=5).delivered == 1
    assert rows()[0].created_at == created_at


@pytest.mark.parametrize("outcome", [Retry("old"), Dead("old"), Delivered()])
def test_stale_worker_cannot_finalize_new_lease(
    database: list[str], monkeypatch: pytest.MonkeyPatch, outcome: Outcome
) -> None:
    outbox.register_handler(TARGET, KIND, lambda item: Delivered())
    put("a", "k")
    now = clock.system_now()
    monkeypatch.setattr(clock, "system_now", lambda: now)
    with db.transaction() as s:
        first = outbox._claim(s)
    now += outbox.LEASE + timedelta(seconds=1)
    with db.transaction() as s:
        second = outbox._claim(s)
    assert first is not None and second is not None
    assert first.lease_until != second.lease_until
    with db.transaction() as s:
        assert outbox._finalize(s, first, outcome) == "STALE"
    row = rows()[0]
    assert row.status == "PENDING" and row.attempts == 0
    assert row.lease_until == second.lease_until
    with db.transaction() as s:
        assert outbox._finalize(s, second, Delivered()) == "SENT"


def test_dead_goes_failed_at_once(database: list[str]) -> None:
    outbox.register_handler(TARGET, KIND, lambda item: Dead("ACCOUNT_BLOCKED"))
    put("a", "k")
    outbox.relay(budget_s=5)
    row = rows()[0]
    assert row.status == "FAILED" and row.attempts == 0


def test_handler_exception_is_a_retry(database: list[str]) -> None:
    def boom(item: OutboxItem) -> Outcome:
        raise ValueError("secret detail")

    outbox.register_handler(TARGET, KIND, boom)
    put("a", "k")
    outbox.relay(budget_s=5)
    row = rows()[0]
    assert row.attempts == 1 and row.last_error == "HANDLER_ERROR:ValueError"


def test_leased_message_is_not_taken_until_lease_expires(database: list[str]) -> None:
    seen: list[str] = []
    outbox.register_handler(
        TARGET, KIND, lambda item: (seen.append(item.idempotency_key), Delivered())[1]
    )
    put("a", "k")
    with db.transaction() as s:
        s.execute(
            update(OutboxMessage).values(lease_until=clock.system_now() + timedelta(minutes=1))
        )
    outbox.relay(budget_s=2)
    assert seen == []
    with db.transaction() as s:
        s.execute(
            update(OutboxMessage).values(lease_until=clock.system_now() - timedelta(seconds=1))
        )
    outbox.relay(budget_s=2)
    assert seen == ["k"]


def test_message_without_registered_handler_is_left_alone(database: list[str]) -> None:
    put("a", "k")
    assert outbox.relay(budget_s=1).handled == 0
    assert rows()[0].status == "PENDING"


def test_two_relays_never_take_the_same_message(database: list[str]) -> None:
    lock = threading.Lock()
    deliveries: list[str] = []

    def handler(item: OutboxItem) -> Outcome:
        time.sleep(0.02)
        with lock:
            deliveries.append(item.idempotency_key)
        return Delivered()

    outbox.register_handler(TARGET, KIND, handler)
    for i in range(24):
        put(f"agg{i}", f"k{i}")
    threads = [threading.Thread(target=outbox.relay, kwargs={"budget_s": 10}) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(deliveries) == sorted(f"k{i}" for i in range(24))  # каждое ровно один раз
    assert {r.status for r in rows()} == {"SENT"}


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(plan=st.lists(st.lists(st.booleans(), max_size=3), min_size=2, max_size=4))
def test_property_order_and_no_duplicates_under_any_failures(
    database: list[str], plan: list[list[bool]]
) -> None:
    """Сбои в любом порядке: получатель принимает по заявке строго по порядку и без дублей."""
    with db.transaction() as s:
        s.execute(text("TRUNCATE outbox"))
    failures = {f"m{i}": list(p) for i, p in enumerate(plan)}  # True = сбой на этой попытке
    accepted: list[str] = []

    def handler(item: OutboxItem) -> Outcome:
        script = failures[item.idempotency_key]
        if script and script.pop(0):
            return Retry("flaky")
        if item.idempotency_key not in accepted:  # получатель дедуплицирует по ключу
            accepted.append(item.idempotency_key)
        return Delivered()

    outbox.register_handler(TARGET, KIND, handler)
    for i in range(len(plan)):
        put("one", f"m{i}")
    for _ in range(len(plan) * 4 + 2):
        make_due()
        outbox.relay(budget_s=5)
    assert accepted == [f"m{i}" for i in range(len(plan))]
    assert {r.status for r in rows()} == {"SENT"}
