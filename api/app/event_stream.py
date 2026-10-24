"""SSE HTTP composition (50-11). No DB connection or reset fence spans a stream's lifetime."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Annotated
from uuid import UUID

import redis
from anyio import CancelScope
from fastapi import APIRouter, Header, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send

from app.modules import applications, auth, companies, notifications
from app.shared import db
from app.shared.errors import AppError

router = APIRouter(tags=["живые статусы"])
AUTH_INTERVAL = 60
RENEW_INTERVAL = 15


def principal_for(zone: auth.Zone, sid: str) -> auth.Principal:
    principal = auth.sessions.load(zone, sid) if sid else None
    if principal is None or principal.zone is not zone:
        raise AppError(401, "UNAUTHENTICATED", "Нужно войти")
    with db.transaction() as session:
        user = auth.get(session, principal.user_id)
        if user is None or user.status != "ACTIVE":
            raise AppError(401, "UNAUTHENTICATED", "Сессия закрыта")
        roles = {"CLIENT"} if zone is auth.Zone.CLIENT else {"UNDERWRITER", "ADMIN"}
        if user.role not in roles or (zone is auth.Zone.BANK and user.level not in {"L1", "L2"}):
            raise AppError(403, "FORBIDDEN", "Доступ отозван")
        members = (
            tuple(
                auth.Membership(m.company_id, m.role, frozenset(m.poa_permissions))
                for m, _ in companies.memberships_of(session, user.id)
            )
            if zone is auth.Zone.CLIENT
            else ()
        )
        return replace(
            principal,
            role=user.role,
            level=user.level,
            person_inn=user.person_inn,
            memberships=members,
        )


def _companies(principal: auth.Principal) -> frozenset[UUID]:
    return frozenset(m.company_id for m in principal.memberships)


def _replay(principal: auth.Principal, cursor: int) -> list[int]:
    with db.transaction() as session:
        return applications.event_ids(session, principal, cursor)


def _notice(zone: auth.Zone, sid: str, event_id: int) -> applications.EventNotice | None:
    principal = principal_for(zone, sid)
    with db.transaction() as session:
        return applications.event_notice(session, principal, event_id)


def frame(kind: str, data: dict[str, str] | None = None, event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {kind}\ndata: {json.dumps(data or {}, separators=(',', ':'))}\n\n"


async def maintain(
    hub: notifications.EventHub, stream: notifications.Stream, zone: auth.Zone, sid: str
) -> None:
    checked = time.monotonic()
    try:
        while not stream.closed.is_set():
            await asyncio.sleep(RENEW_INTERVAL)
            if not await hub.renew(stream):
                stream.close()
                return
            if time.monotonic() - checked >= AUTH_INTERVAL:
                principal = await run_in_threadpool(principal_for, zone, sid)
                stream.companies = _companies(principal)
                # A worker can commit then crash before PUBLISH while the SSE connection stays up.
                # Sequence allocation order is not commit order, so max(id) cannot detect this gap.
                stream.resync()
                checked = time.monotonic()
    except AppError as exc:
        stream.close("auth_expired" if exc.status in {401, 403} else "closed")
    except redis.RedisError:
        stream.close()
    except Exception:
        stream.close()  # DB unavailable: close and let the existing frontend fallback recover


async def messages(
    hub: notifications.EventHub,
    stream: notifications.Stream,
    principal: auth.Principal,
    cursor: int | None,
) -> AsyncIterator[str]:
    watermark = cursor or 0
    try:
        yield "retry: 3000\n\n"
        replay = await run_in_threadpool(_replay, principal, cursor) if cursor is not None else []
        if len(replay) > 100:
            replay = []
        # Registering before replay closes the subscribe/replay gap. Always resync, including on
        # reconnect: a lower sequence id may have committed after a higher id was already delivered.
        for event_id in replay:
            notice = await run_in_threadpool(
                _notice, principal.zone, principal.session_id, event_id
            )
            if notice is not None:
                if stream.closed.is_set():
                    break
                watermark = max(watermark, notice.id)
                yield frame(notice.kind, notice.data, notice.id)
        if not stream.closed.is_set():
            yield frame("resync")
        while True:
            item = await stream.receive()
            if item == "auth_expired":
                yield frame("auth_expired")
                return
            if item == "closed":
                return
            if item == "ping":
                yield ": ping\n\n"
            elif item == "resync":
                yield frame("resync")
            elif isinstance(item, int):
                notice = await run_in_threadpool(
                    _notice, principal.zone, principal.session_id, item
                )
                if notice is None or stream.closed.is_set():
                    continue  # revoked scope or reset-deleted row: no id, no watermark change
                if notice.id <= watermark:
                    yield frame("resync")
                else:
                    watermark = notice.id
                    yield frame(notice.kind, notice.data, notice.id)
    except AppError as exc:
        if exc.status in {401, 403}:
            yield frame("auth_expired")


class EventResponse(StreamingResponse):
    """Slow sockets must not retain leases/tasks forever; cleanup also covers pre-yield aborts."""

    def __init__(
        self,
        hub: notifications.EventHub,
        stream: notifications.Stream,
        principal: auth.Principal,
        cursor: int | None,
    ) -> None:
        self.hub, self.stream, self.principal = hub, stream, principal
        super().__init__(
            messages(hub, stream, principal, cursor),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        maintenance = asyncio.create_task(
            maintain(self.hub, self.stream, self.principal.zone, self.principal.session_id)
        )

        async def bounded_send(message: Message) -> None:
            async with asyncio.timeout(10):
                await send(message)

        try:
            with contextlib.suppress(TimeoutError):
                await super().__call__(scope, receive, bounded_send)
        finally:
            with CancelScope(shield=True):
                maintenance.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await maintenance
                await self.hub.close(self.stream)


@router.get(
    "/events/stream",
    response_class=StreamingResponse,
    operation_id="streamEvents",
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def stream_events(
    request: Request,
    zone: auth.Zone,
    last_event_id: Annotated[str | None, Header(max_length=20)] = None,
    lastEventId: Annotated[str | None, Query(max_length=20)] = None,
) -> StreamingResponse:  # noqa: N803 — browser resume query is part of the approved contract
    raw = last_event_id if last_event_id is not None else lastEventId
    try:
        cursor = int(raw) if raw is not None else None
        if cursor is not None and not 0 <= cursor <= 2**63 - 1:
            raise ValueError
    except ValueError as exc:
        raise AppError(422, "INVALID_EVENT_CURSOR", "Неверный номер события") from exc
    sid = request.cookies.get(auth.sessions.COOKIE[zone], "")
    principal = await run_in_threadpool(principal_for, zone, sid)
    hub: notifications.EventHub = request.app.state.event_hub

    async def visible(event_id: int) -> bool:
        try:
            return await run_in_threadpool(_notice, zone, sid, event_id) is not None
        except AppError as exc:
            if exc.status in {401, 403}:
                return False
            raise

    try:
        stream = await hub.open(
            _companies(principal),
            bank=zone is auth.Zone.BANK,
            session=f"{zone}:{sid}",
            visible=visible,
        )
    except redis.RedisError as exc:
        raise AppError(
            503,
            "EVENT_STREAM_UNAVAILABLE",
            "Живые обновления временно недоступны",
            headers={"Retry-After": "3"},
        ) from exc
    return EventResponse(hub, stream, principal, cursor)
