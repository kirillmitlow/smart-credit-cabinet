"""Redis is a doorbell, not an event store (50-11). One subscriber per API process."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import redis
import redis.asyncio as aioredis
import structlog

from app.shared.cache import get_redis

CHANNEL = "scc:events"
EVICTIONS = "scc:events:evict"
LEASE_SECONDS = 75

# Redis TIME avoids clock drift across API processes. Order and liveness are separate:
# renewing an old stream must not make it the newest, nor revive an evicted/expired lease.
_ADMIT = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
local stale=redis.call('ZRANGEBYSCORE',KEYS[2],'-inf',now-75000)
for _,id in ipairs(stale) do redis.call('ZREM',KEYS[1],id); redis.call('ZREM',KEYS[2],id) end
local seq=redis.call('INCR',KEYS[3])
redis.call('ZADD',KEYS[1],seq,ARGV[1]); redis.call('ZADD',KEYS[2],now,ARGV[1])
while redis.call('ZCARD',KEYS[1])>5 do
 local old=redis.call('ZPOPMIN',KEYS[1],1)[1]
 redis.call('ZREM',KEYS[2],old); redis.call('PUBLISH',ARGV[2],old)
end
for _,key in ipairs(KEYS) do redis.call('EXPIRE',key,90) end
return 1
"""
_RENEW = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
local last=redis.call('ZSCORE',KEYS[2],ARGV[1])
if not last or tonumber(last)<=now-75000 or not redis.call('ZSCORE',KEYS[1],ARGV[1]) then
 redis.call('ZREM',KEYS[1],ARGV[1]); redis.call('ZREM',KEYS[2],ARGV[1]); return 0
end
redis.call('ZADD',KEYS[2],now,ARGV[1])
for _,key in ipairs(KEYS) do redis.call('EXPIRE',key,90) end
return 1
"""


def publish(event_id: int, company_id: UUID) -> None:
    """Called after outer commit, also in Celery. A lost doorbell is repaired by resync."""
    try:
        get_redis().publish(CHANNEL, json.dumps({"id": event_id, "company": str(company_id)}))
    except redis.RedisError as exc:
        structlog.get_logger("events").warning("publish_unavailable", error_type=type(exc).__name__)


@dataclass(eq=False)
class Stream:
    companies: frozenset[UUID]
    bank: bool
    keys: tuple[str, str, str]
    id: str = field(default_factory=lambda: uuid4().hex)
    queue: asyncio.Queue[int | str] = field(default_factory=lambda: asyncio.Queue(100))
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    reason: str = "closed"
    visible: Callable[[int], Awaitable[bool]] | None = field(default=None, repr=False)

    def close(self, reason: str = "closed") -> None:
        self.reason = reason
        self.closed.set()  # independent of the bounded data queue

    def offer(self, event_id: int, company_id: UUID) -> None:
        if self.closed.is_set() or not (self.bank or company_id in self.companies):
            return
        if self.queue.full():
            self.resync()
        self.queue.put_nowait(event_id)

    def resync(self) -> None:
        if self.queue.full():
            while not self.queue.empty():
                self.queue.get_nowait()
        self.queue.put_nowait("resync")

    async def receive(self, timeout: float = 15) -> int | str:
        queued = asyncio.create_task(self.queue.get())
        closed = asyncio.create_task(self.closed.wait())
        try:
            done, _ = await asyncio.wait(
                (queued, closed), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if closed in done:
                return self.reason
            return queued.result() if queued in done else "ping"
        finally:
            for task in (queued, closed):
                task.cancel()
            await asyncio.gather(queued, closed, return_exceptions=True)


class EventHub:
    def __init__(self, url: str) -> None:
        self.redis = aioredis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
        self.streams: dict[str, Stream] = {}
        self.ready = asyncio.Event()
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self._listen())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.ready.wait(), 3)

    async def stop(self) -> None:
        self.ready.clear()
        for stream in self.streams.values():
            stream.close()
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.redis.aclose()

    async def _listen(self) -> None:
        while True:
            try:
                async with self.redis.pubsub() as subscriber:
                    await subscriber.subscribe(CHANNEL, EVICTIONS)
                    acked: set[str] = set()
                    while len(acked) < 2:
                        message = await subscriber.get_message(timeout=2)
                        if not message:
                            raise redis.ConnectionError("subscribe acknowledgement timed out")
                        if message["type"] == "subscribe":
                            acked.add(message["channel"])
                    self.ready.set()  # never admit streams before SUBSCRIBE acknowledgement
                    while True:
                        message = await subscriber.get_message(
                            ignore_subscribe_messages=True, timeout=1
                        )
                        if message is not None:
                            await self._dispatch(message["channel"], message["data"])
            except redis.RedisError:
                pass
            finally:
                self.ready.clear()
                for stream in self.streams.values():
                    stream.close()
            await asyncio.sleep(1)

    async def _dispatch(self, channel: str, raw: str) -> None:
        if channel == EVICTIONS:
            if stream := self.streams.get(raw):
                stream.close()
            return
        try:
            data = json.loads(raw)
            event_id, company_id = int(data["id"]), UUID(data["company"])
        except (ValueError, TypeError, KeyError):
            return
        for stream in list(self.streams.values()):
            if stream.closed.is_set() or not (stream.bank or company_id in stream.companies):
                continue
            try:
                if stream.visible is None or await stream.visible(event_id):
                    stream.offer(event_id, company_id)
            except Exception:
                stream.close()  # failed ACL read must never fall back to an unfiltered queue

    async def open(
        self,
        companies: frozenset[UUID],
        *,
        bank: bool,
        session: str,
        visible: Callable[[int], Awaitable[bool]] | None = None,
    ) -> Stream:
        if not self.ready.is_set():
            raise redis.ConnectionError("subscriber unavailable")
        digest = hashlib.sha256(session.encode()).hexdigest()
        prefix = f"scc:streams:{digest}"
        stream = Stream(companies, bank, (f"{prefix}:order", f"{prefix}:lease", f"{prefix}:seq"))
        stream.visible = visible
        self.streams[stream.id] = stream
        try:
            await self.redis.eval(_ADMIT, 3, *stream.keys, stream.id, EVICTIONS)
            if not self.ready.is_set():
                raise redis.ConnectionError("subscriber disconnected")
        except BaseException:
            await self.close(stream)
            raise
        return stream

    async def renew(self, stream: Stream) -> bool:
        return bool(await self.redis.eval(_RENEW, 3, *stream.keys, stream.id))

    async def close(self, stream: Stream) -> None:
        stream.close()
        self.streams.pop(stream.id, None)
        with contextlib.suppress(redis.RedisError):
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.zrem(stream.keys[0], stream.id)
                pipe.zrem(stream.keys[1], stream.id)
                await pipe.execute()
