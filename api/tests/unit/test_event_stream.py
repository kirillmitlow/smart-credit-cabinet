"""Bounded queues: overflow requests resync without losing closure or the next event."""

from uuid import uuid4

import pytest
import redis

from app import event_stream
from app.modules import notifications
from app.modules.notifications.stream import Stream

pytestmark = pytest.mark.unit


async def test_scope_overflow_ping_and_eviction_have_independent_state() -> None:
    company = uuid4()
    stream = Stream(frozenset({company}), False, ("a", "b", "c"))
    stream.offer(900, uuid4())
    assert await stream.receive(0.001) == "ping"
    for event_id in range(101):
        stream.offer(event_id, company)
    assert await stream.receive(0.01) == "resync"
    assert await stream.receive(0.01) == 100
    stream.offer(101, company)
    assert await stream.receive(0.01) == 101
    stream.close("auth_expired")
    for event_id in range(102, 204):
        stream.offer(event_id, company)
    assert await stream.receive(0.01) == "auth_expired"


def test_frame_contains_only_explicit_projection_and_control_has_no_id() -> None:
    assert event_stream.frame("resync") == "event: resync\ndata: {}\n\n"
    assert event_stream.frame("step_done", {"applicationId": "a"}, 12).startswith(
        "id: 12\nevent: step_done"
    )


def test_redis_failure_does_not_turn_committed_action_into_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.notifications import stream

    class Down:
        def publish(self, *_: object) -> None:
            raise redis.ConnectionError("offline")

    monkeypatch.setattr(stream, "get_redis", lambda: Down())
    notifications.publish(1, uuid4())


async def test_hidden_events_are_filtered_before_queue_overflow() -> None:
    import json

    company = uuid4()
    hub = notifications.EventHub("redis://127.0.0.1:1")
    stream = Stream(frozenset({company}), False, ("a", "b", "c"))

    async def hidden(_event_id: int) -> bool:
        return False

    stream.visible = hidden
    hub.streams[stream.id] = stream
    try:
        for event_id in range(110):
            await hub._dispatch("scc:events", json.dumps({"id": event_id, "company": str(company)}))
        assert stream.queue.empty()  # even a resync would reveal hidden company activity
        assert not stream.closed.is_set()
    finally:
        await hub.redis.aclose()
