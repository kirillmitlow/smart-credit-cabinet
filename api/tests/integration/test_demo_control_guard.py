"""Общий Redis-лимит облачного стенда: параллельные HTTP-запросы не обходят счётчик."""

import asyncio

import httpx
import pytest
import redis

from app.main import create_app
from app.shared import cache, resets
from app.shared.settings import DEV_SECRETS, Settings

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_shared_rate_window_survives_reset_prefixes(redis_url, monkeypatch):
    monkeypatch.setenv("REDIS_URL", redis_url)
    app = create_app(
        Settings(
            app_env="cloud",
            redis_url=redis_url,
            demo_stand_code="correct",
            demo_controls_per_minute=3,
            **{name: f"real-{name}" for name in DEV_SECRETS},
        )
    )
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    client.flushdb()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        replies = await asyncio.gather(
            *[
                c.put("/demo/chaos/tax", json={"mode": "OK"}, headers={"X-Demo-Code": "wrong"})
                for _ in range(12)
            ]
        )
        assert sorted(r.status_code for r in replies) == [403] * 3 + [429] * 9
        keys = list(client.scan_iter("demo-control-rate:*"))
        assert len(keys) == 1
        assert 0 < client.ttl(keys[0]) <= 120
        cache.delete_prefixes(resets.cache_prefixes())
        r = await c.put("/demo/chaos/tax", json={"mode": "OK"}, headers={"X-Demo-Code": "correct"})
        assert r.status_code == 429
    client.flushdb()
