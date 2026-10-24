"""T-352: real PostgreSQL/Valkey, two API instances, ASGI streaming without buffering clients."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import delete, text, update

from app import event_stream
from app.main import create_app
from app.modules import applications, auth, notifications
from app.modules.applications.models import Task
from app.modules.companies.models import Company, CompanyMember
from app.shared import db
from app.shared.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    apps = [create_app(Settings(database_url=postgres_url, redis_url=redis_url)) for _ in range(2)]
    database = db.get_database()
    db.migrate(database.engine)
    with db.transaction() as s:
        s.execute(text("TRUNCATE applications, company_members, companies, users CASCADE"))
        clients, records = [], []
        for n in range(2):
            company = Company(
                inn=f"001234567{n}", kind="LEGAL", name=f"Company {n}", status="ACTIVE"
            )
            user = auth.upsert_client(
                s,
                login_ref=f"sse:{n}",
                display_name=f"Client {n}",
                person_inn=None,
                scenario_code=None,
            )
            s.add(company)
            s.flush()
            s.add(
                CompanyMember(
                    company_id=company.id,
                    user_id=user.id,
                    role="DIRECTOR",
                    can_sign=True,
                    poa_permissions=[],
                    status="ACTIVE",
                )
            )
            principal = auth.Principal(
                user.id,
                "CLIENT",
                auth.Zone.CLIENT,
                user.display_name,
                memberships=(auth.Membership(company.id, "DIRECTOR"),),
                active_company_id=company.id,
            )
            record = applications.Application(
                number=f"SSE-{n}",
                company_id=company.id,
                created_by=user.id,
                status="DRAFT",
                version=1,
                draft={},
                flags=[],
            )
            s.add(record)
            s.flush()
            clients.append(principal)
            records.append(record.id)
        bank = auth.User(
            login_ref="sse:bank",
            display_name="Bank",
            role="UNDERWRITER",
            level="L2",
            status="ACTIVE",
        )
        s.add(bank)
        s.flush()
        bank_principal = auth.Principal(
            bank.id, bank.role, auth.Zone.BANK, bank.display_name, level="L2"
        )
    hubs = [notifications.EventHub(redis_url) for _ in apps]
    for app, hub in zip(apps, hubs, strict=True):
        app.state.event_hub = hub
        await hub.start()
        assert hub.ready.is_set()
    try:
        yield {
            "apps": apps,
            "hubs": hubs,
            "clients": clients,
            "bank": bank_principal,
            "records": records,
            "database": database,
        }
    finally:
        for hub in hubs:
            await hub.stop()
        database.dispose()


def emit(world: dict[str, Any], n: int = 0, *, session: Any = None) -> int:
    def write(s: Any) -> int:
        app = s.get(applications.Application, world["records"][n])
        return applications.record_event(
            s,
            app,
            "STEP",
            actor_type=applications.Actor.SYSTEM,
            step_code="REGISTRY_DONE",
            payload={"private": "MUST_NOT_LEAK"},
        ).id

    if session is not None:
        return write(session)
    with db.transaction() as s:
        return write(s)


class Browser:
    def __init__(
        self,
        app: Any,
        principal: auth.Principal,
        *,
        cursor: int | None = None,
        query_cursor: bool = False,
    ) -> None:
        self.bodies: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.disconnect = asyncio.Event()
        sid = principal.session_id or auth.sessions.create(principal)
        headers = [(b"cookie", f"{auth.sessions.COOKIE[principal.zone]}={sid}".encode())]
        query = f"zone={principal.zone.value}"
        if cursor is not None:
            if query_cursor:
                query += f"&lastEventId={cursor}"
            else:
                headers.append((b"last-event-id", str(cursor).encode()))
        self.scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "method": "GET",
            "scheme": "http",
            "path": "/events/stream",
            "raw_path": b"/events/stream",
            "root_path": "",
            "query_string": query.encode(),
            "headers": headers,
            "server": ("api", 80),
            "client": ("test", 1),
            "http_version": "1.1",
        }
        first = True

        async def receive() -> dict[str, Any]:
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": b""}
            await self.disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            await self.bodies.put(message)

        self.task = asyncio.create_task(app(self.scope, receive, send))

    async def frame(self) -> str:
        while True:
            message = await asyncio.wait_for(self.bodies.get(), 3)
            if message["type"] == "http.response.start":
                self.status = message["status"]
                self.headers = dict(message["headers"])
                if self.status != 200:
                    return str(self.status)
            else:
                return message.get("body", b"").decode()

    async def ready(self) -> None:
        assert "retry: 3000" in await self.frame()
        assert "event: resync" in await self.frame()
        assert self.status == 200
        assert self.headers[b"content-type"].startswith(b"text/event-stream")
        assert self.headers[b"x-accel-buffering"] == b"no"

    async def close(self) -> None:
        self.disconnect.set()
        await asyncio.wait_for(self.task, 3)


async def test_worker_commit_fanout_two_apis_is_private_and_not_before_commit(
    world: dict[str, Any],
) -> None:
    readers = [Browser(app, world["clients"][0]) for app in world["apps"]]
    foreign = Browser(world["apps"][0], world["clients"][1])
    bank = Browser(world["apps"][1], world["bank"])
    try:
        for reader in [*readers, foreign, bank]:
            await reader.ready()
        with db.transaction() as s:
            with s.begin_nested():
                event_id = emit(world, session=s)
            await asyncio.sleep(0.03)
            assert all(reader.bodies.empty() for reader in [*readers, foreign, bank])
        for reader in [*readers, bank]:
            received = await reader.frame()
            assert f"id: {event_id}\n" in received
            assert "step_done" in received
            assert "REGISTRY_DONE" in received
            assert "MUST_NOT_LEAK" not in received
            assert set(json.loads(received.split("data: ")[1])) == {"applicationId", "clientStep"}
        assert foreign.bodies.empty()
    finally:
        for reader in [*readers, foreign, bank]:
            await reader.close()
    assert all(not hub.streams for hub in world["hubs"])


async def test_resume_query_cursor_100_then_101_visible_events(world: dict[str, Any]) -> None:
    start = emit(world)
    for _ in range(100):
        emit(world)
    # Foreign events must not count towards replay/resync limit.
    for _ in range(2):
        emit(world, 1)
    reader = Browser(world["apps"][0], world["clients"][0], cursor=start, query_cursor=True)
    try:
        assert "retry" in await reader.frame()
        frames = [await reader.frame() for _ in range(100)]
        assert all("id: " in frame for frame in frames)
        assert "resync" in await reader.frame()
    finally:
        await reader.close()
    emit(world)
    reader = Browser(world["apps"][1], world["clients"][0], cursor=start)
    try:
        await reader.ready()  # 101 -> resync only, never a partial misleading replay
        assert reader.bodies.empty()
    finally:
        await reader.close()


async def test_out_of_order_commits_and_reconnect_force_resync(world: dict[str, Any]) -> None:
    reader = Browser(world["apps"][0], world["clients"][0])
    try:
        await reader.ready()
        with db.transaction() as slow:
            low = emit(world, session=slow)
            high = emit(world)
            assert high > low
            assert f"id: {high}" in await reader.frame()
        assert "resync" in await reader.frame()  # low id committed after high, not silently dropped
    finally:
        await reader.close()
    reconnect = Browser(world["apps"][1], world["clients"][0], cursor=high)
    try:
        await reconnect.ready()  # mandatory even though id>high replay is empty
    finally:
        await reconnect.close()


async def test_rollback_and_deleted_reset_row_never_deliver(world: dict[str, Any]) -> None:
    hub = world["hubs"][0]
    company = world["clients"][0].active_company_id
    stream = await hub.open(frozenset({company}), bank=False, session="reset-test")
    with db.get_database().sessions() as s:
        s.begin()
        emit(world, session=s)
        s.rollback()
    await asyncio.sleep(0.03)
    assert stream.queue.empty()
    event_id = emit(world)
    assert await stream.receive(1) == event_id
    with db.transaction() as s:
        s.execute(
            text("SELECT set_config('scc.demo_reset_ids', :ids, true)"),
            {"ids": str(world["records"][0])},
        )
        s.execute(
            delete(applications.ApplicationEvent).where(
                applications.ApplicationEvent.id == event_id
            )
        )
    principal = world["clients"][0]
    with db.transaction() as s:
        assert applications.event_notice(s, principal, event_id) is None
    await hub.close(stream)


async def test_guarantor_only_receives_personal_task_ids_and_revocation_is_fresh(
    world: dict[str, Any],
) -> None:
    p = world["clients"][0]
    with db.transaction() as s:
        s.execute(
            update(CompanyMember).where(CompanyMember.user_id == p.user_id).values(role="GUARANTOR")
        )
        app = s.get(applications.Application, world["records"][0])
        task = Task(
            application_id=app.id,
            round=1,
            kind="EXPLANATION",
            title="Personal",
            why_text="Test",
            details={},
            status="OPEN",
            assignee_user_id=p.user_id,
            created_by_actor="SYSTEM",
        )
        s.add(task)
        s.flush()
        own = applications.record_event(
            s,
            app,
            "TASK",
            actor_type=applications.Actor.SYSTEM,
            step_code="TASK_CREATED",
            payload={"taskId": str(task.id)},
        ).id
    sid = auth.sessions.create(p)  # stale Redis principal still claims DIRECTOR
    fresh = event_stream.principal_for(auth.Zone.CLIENT, sid)
    hidden = emit(world)
    with db.transaction() as s:
        assert applications.event_ids(s, fresh, 0) == [own]
        assert applications.event_notice(s, fresh, hidden) is None
        assert applications.event_notice(s, fresh, own).kind == "task_created"
        s.execute(
            update(CompanyMember)
            .where(CompanyMember.user_id == p.user_id)
            .values(status="SUSPENDED")
        )
    with db.transaction() as s:
        assert applications.event_ids(s, event_stream.principal_for(auth.Zone.CLIENT, sid), 0) == []


async def test_global_five_leases_lost_eviction_cannot_be_renewed(world: dict[str, Any]) -> None:
    a, b = world["hubs"]
    streams = [
        await (a if n % 2 == 0 else b).open(frozenset(), bank=True, session="one-session")
        for n in range(6)
    ]
    for _ in range(30):
        if streams[0].closed.is_set():
            break
        await asyncio.sleep(0.01)
    assert streams[0].closed.is_set()
    assert not await a.renew(streams[0])  # also works if eviction doorbell was lost
    assert await b.redis.zcard(streams[0].keys[0]) == 5
    for n, stream in enumerate(streams):
        await (a if n % 2 == 0 else b).close(stream)
    expired = await a.open(frozenset(), bank=True, session="dead-api")
    await a.redis.zadd(expired.keys[1], {expired.id: 0})
    assert not await a.renew(expired)
    await a.close(expired)


async def test_lost_publish_periodic_resync_and_session_logout(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(event_stream, "AUTH_INTERVAL", 0.02)
    monkeypatch.setattr(event_stream, "RENEW_INTERVAL", 0.02)
    p = world["clients"][0]
    sid = auth.sessions.create(p)
    reader = Browser(world["apps"][0], replace(p, session_id=sid))
    try:
        await reader.ready()
        monkeypatch.setattr(notifications, "publish", lambda *_: None)
        emit(world)
        assert "resync" in await reader.frame()
        auth.sessions.destroy(auth.Zone.CLIENT, sid)
        while "auth_expired" not in await reader.frame():
            pass
        await asyncio.wait_for(reader.task, 3)
    finally:
        await reader.close()


async def test_redis_unready_new_stream_503_and_existing_closes(world: dict[str, Any]) -> None:
    hub = world["hubs"][0]
    reader = Browser(world["apps"][0], world["clients"][0])
    await reader.ready()
    await hub.stop()
    await asyncio.wait_for(reader.task, 3)
    denied = Browser(world["apps"][0], world["clients"][0])
    try:
        assert await denied.frame() == "503"
    finally:
        await denied.close()
        await reader.close()


async def test_invalid_cursor_and_separate_bank_cookie(world: dict[str, Any]) -> None:
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=world["apps"][0]), base_url="http://api"
    ) as client:
        assert (await client.get("/events/stream?zone=client")).status_code == 401
        sid = auth.sessions.create(world["clients"][0])
        client.cookies.set("sid_client", sid)
        assert (await client.get("/events/stream?zone=bank")).status_code == 401
        for cursor in ("-1", "oops", str(2**63)):
            response = await client.get(
                "/events/stream?zone=client", headers={"Last-Event-ID": cursor}
            )
            assert response.status_code == 422


async def test_pubsub_disconnect_closes_old_stream_and_recovers_after_subscribe_ack(
    world: dict[str, Any],
) -> None:
    reader = Browser(world["apps"][0], world["clients"][0])
    await reader.ready()
    hub = world["hubs"][0]
    await hub.redis.execute_command("CLIENT", "KILL", "TYPE", "pubsub")
    await asyncio.wait_for(reader.task, 3)
    await reader.close()
    await asyncio.wait_for(hub.ready.wait(), 4)
    recovered = Browser(world["apps"][0], world["clients"][0])
    try:
        await recovered.ready()
        event_id = emit(world)
        assert f"id: {event_id}" in await recovered.frame()
    finally:
        await recovered.close()


async def test_slow_socket_releases_lease_without_waiting_for_heartbeat(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(event_stream, "SEND_TIMEOUT", 0.02)
    hub = world["hubs"][0]
    p = world["clients"][0]
    sid = auth.sessions.create(p)
    stream = await hub.open(frozenset({p.active_company_id}), bank=False, session="slow")
    response = event_stream.EventResponse(hub, stream, replace(p, session_id=sid), None)

    async def blocked_send(_message: Any) -> None:
        await asyncio.sleep(1)

    async def receive() -> Any:
        await asyncio.sleep(1)
        return {"type": "http.disconnect"}

    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, blocked_send)
    assert stream.id not in hub.streams
    assert await hub.redis.zcard(stream.keys[0]) == 0
