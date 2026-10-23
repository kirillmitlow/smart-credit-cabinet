"""Демо-прокси, разрешённые поля и облачный барьер: реальные HTTP-роуты, внешние порты подменены."""

from contextlib import contextmanager, nullcontext
from functools import lru_cache
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.main import create_app
from app.modules import companies
from app.modules.integrations import System, chaos, scenarios
from app.shared import cache, operations
from app.shared.settings import DEV_SECRETS, Settings

pytestmark = pytest.mark.unit


class Counter:
    def __init__(self):
        self.hits = 0

    @contextmanager
    def pipeline(self, **kwargs):
        yield self

    def incr(self, key):
        self.hits += 1

    def expire(self, *args):
        pass

    def execute(self):
        return self.hits, True


def stand(monkeypatch, *, cloud=False, code="stand-123", limit=300, demo=True):
    settings = Settings(
        app_env="cloud" if cloud else "local",
        demo_mode=demo,
        demo_stand_code=code,
        demo_controls_per_minute=limit,
        **{name: f"real-{name}" for name in DEV_SECRETS},
    )
    app = create_app(settings)
    monkeypatch.setattr(operations, "hold", lambda provider: nullcontext())
    counter = Counter()
    monkeypatch.setattr(cache, "get_redis", lru_cache(maxsize=1)(lambda: counter))
    calls = []

    def configure(system, config=None):
        calls.append((system, config))
        return {
            "mode": (config or {}).get("mode", "OK"),
            "latencyMs": None,
            "X-Admin-Key": "secret-must-not-leak",
        }

    monkeypatch.setattr(chaos, "configure", configure)
    return app, calls


async def call(app, method, path, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        return await c.request(method, path, **kwargs)


@pytest.mark.anyio
async def test_cloud_barrier_on_all_mutations_before_side_effect(monkeypatch):
    app, calls = stand(monkeypatch, cloud=True)
    for path, method, body in [
        ("/demo/reset", "POST", None),
        ("/demo/personas/sokolova/reset", "POST", None),
        ("/demo/chaos/tax", "PUT", {"mode": "DOWN"}),
    ]:
        for headers in ({}, {"X-Demo-Code": "wrong"}):
            r = await call(app, method, path, headers=headers, json=body)
            assert r.status_code == 403
            assert r.json()["code"] == "DEMO_CODE_REQUIRED"
    assert calls == []
    r = await call(
        app, "PUT", "/demo/chaos/tax", headers={"X-Demo-Code": "stand-123"}, json={"mode": "DOWN"}
    )
    assert r.status_code == 200
    assert r.json() == {"system": "tax", "available": True, "mode": "DOWN", "latencyMs": None}
    assert calls[0][1]["paths"] is None
    assert "secret-must-not-leak" not in r.text


@pytest.mark.anyio
async def test_local_open_and_non_demo_all_denied(monkeypatch):
    app, _ = stand(monkeypatch)
    assert (await call(app, "PUT", "/demo/chaos/registry", json={"mode": "OK"})).status_code == 200
    app, calls = stand(monkeypatch, demo=False)
    for path, method in [
        ("/demo/personas", "GET"),
        ("/demo/chaos", "GET"),
        ("/demo/chaos/tax", "PUT"),
        ("/demo/reset", "POST"),
    ]:
        assert (await call(app, method, path, json={"mode": "OK"})).status_code == 403
    assert calls == []


@pytest.mark.anyio
async def test_missing_configured_code_fails_closed_and_attempts_limited(monkeypatch):
    app, _ = stand(monkeypatch, cloud=True, code="", limit=2)
    for expected in [403, 403, 429]:
        r = await call(
            app, "PUT", "/demo/chaos/tax", headers={"X-Demo-Code": "anything"}, json={"mode": "OK"}
        )
        assert r.status_code == expected
    assert r.headers["Retry-After"] == "60"


@pytest.mark.anyio
async def test_rate_store_failure_is_not_bypass(monkeypatch):
    app, calls = stand(monkeypatch, cloud=True)

    def broken():
        raise RedisConnectionError("private-internal-address")

    monkeypatch.setattr(cache, "get_redis", lru_cache(maxsize=1)(broken))
    r = await call(
        app, "PUT", "/demo/chaos/tax", json={"mode": "OK"}, headers={"X-Demo-Code": "stand-123"}
    )
    assert r.status_code == 503
    assert "private-internal-address" not in r.text
    assert calls == []


@pytest.mark.anyio
async def test_partial_chaos_availability_and_input_allowlist(monkeypatch):
    app, _ = stand(monkeypatch)

    def configure(system, config=None):
        if system is System.TAX:
            raise chaos.ChaosUnavailableError("private")
        return {"mode": "OK"}

    monkeypatch.setattr(chaos, "configure", configure)
    r = await call(app, "GET", "/demo/chaos")
    assert r.status_code == 200
    assert len(r.json()) == 4
    assert next(row for row in r.json() if row["system"] == "tax")["available"] is False
    assert (await call(app, "PUT", "/demo/chaos/tax", json={"mode": "OK"})).status_code == 502
    for path, body in [
        ("/demo/chaos/evil", {"mode": "OK"}),
        ("/demo/chaos/tax", {"mode": "UNKNOWN"}),
    ]:
        assert (await call(app, "PUT", path, json=body)).status_code == 422


@pytest.mark.anyio
async def test_personas_use_live_scenarios_and_never_return_users_or_spec(monkeypatch):
    app, _ = stand(monkeypatch)
    monkeypatch.setattr(
        scenarios, "list_scenarios", lambda: [{"code": "sokolova"}, {"code": "t-test"}]
    )

    def scenario(code):
        return {
            "code": code,
            "title": code,
            "inn": "123",
            "status": "APPLIED",
            "expectedOutcome": "MANUAL_REVIEW",
            "expectedFinalOutcome": "APPROVED",
            "expectedReasonCodes": ["MANUAL_TEST"],
            "application": {"productCode": "INVESTMENT", "amountRub": "1000000", "termMonths": 60},
            "users": [{"password": "secret"}],
            "spec": {"adminKey": "secret"},
        }

    monkeypatch.setattr(scenarios, "get_scenario", scenario)
    monkeypatch.setattr(
        companies, "for_scenario", lambda code: SimpleNamespace(company_id=UUID(int=1))
    )
    r = await call(app, "GET", "/demo/personas")
    assert r.status_code == 200
    assert [p["technical"] for p in r.json()] == [False, True]
    assert r.json()[0]["application"]["amountRub"] == "1000000"
    assert r.json()[0]["companyId"] == str(UUID(int=1))
    assert "secret" not in r.text
    assert "users" not in r.text
    assert "spec" not in r.text

    def broken():
        raise scenarios.ScenariosUnavailableError("private-key")

    monkeypatch.setattr(scenarios, "list_scenarios", broken)
    r = await call(app, "GET", "/demo/personas")
    assert r.status_code == 502
    assert "private-key" not in r.text
