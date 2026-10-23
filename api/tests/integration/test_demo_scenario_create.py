"""Создание: реальная БД/Redis, внешний порт сценариев с потерей ответа и повтором."""

import copy
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.main import create_app
from app.modules import audit, companies
from app.modules.companies import Company
from app.modules.integrations import scenarios
from app.shared import cache, db, operations, resets
from app.shared.settings import DEV_SECRETS, Settings

pytestmark = pytest.mark.integration

SPEC = {"code": "custom-demo", "title": "Тестовый ИП", "preset": "IP_HEALTHY"}
VIEW = {
    "code": "custom-demo",
    "title": "Тестовый ИП",
    "status": "APPLIED",
    "inn": "001234567887",
    "expectedOutcome": "APPROVED",
    "expectedFinalOutcome": None,
    "expectedReasonCodes": [],
    "application": {"productCode": "EXPRESS", "amountRub": 500000, "termMonths": 12},
    "applied": {"registry": "OK", "tax": "OK", "bki": "OK", "bankCore": "OK"},
    "users": [{"login": "owner", "personRef": "self", "role": "DIRECTOR"}],
    "expanded": {
        "identity": {
            "form": "IP",
            "inn": "001234567887",
            "status": "ACTIVE",
            "shortName": "Тестовый ИП",
            "persons": [{"ref": "self", "inn": "001234567887", "fullName": "Тестовый ИП"}],
        }
    },
    "spec": {"raw": {"adminKey": "must-never-appear"}},
}


class Source:
    def __init__(self):
        self.by_key: dict[str, dict[str, Any]] = {}
        self.calls = 0
        self.lose_reply = False
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.rejection: Exception | None = None

    def create(self, body, *, idempotency_key):
        self.calls += 1
        if self.rejection:
            raise self.rejection
        if self.block:
            self.entered.set()
            assert self.release.wait(10)
        if idempotency_key not in self.by_key:
            self.by_key[idempotency_key] = {**copy.deepcopy(VIEW), "code": body["code"]}
        if self.lose_reply:
            self.lose_reply = False
            raise scenarios.ScenariosUnavailableError("lost after upstream commit")
        return copy.deepcopy(self.by_key[idempotency_key])


@pytest.fixture
def stand(postgres_url, redis_url, monkeypatch) -> Iterator[tuple]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    settings = Settings(database_url=postgres_url, redis_url=redis_url)
    app = create_app(settings)
    cache.get_redis().flushdb()
    db.migrate(db.get_database().engine)
    with db.transaction() as s:
        resets.run_all_resets(s)
    source = Source()
    monkeypatch.setattr(scenarios, "create_scenario", source.create)
    yield app, source
    cache.get_redis().flushdb()
    db.get_database().dispose()


async def post(app, body=None, key="create-once"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        return await c.post(
            "/demo/scenarios",
            json=SPEC if body is None else body,
            headers={} if key is None else {"Idempotency-Key": key},
        )


def counts():
    with db.transaction() as s:
        return (
            s.scalar(select(func.count()).select_from(Company)),
            s.scalar(
                select(func.count())
                .select_from(audit.AuditRecord)
                .where(audit.AuditRecord.action == "DEMO_SCENARIO_CREATED")
            ),
        )


@pytest.mark.anyio
async def test_create_syncs_directory_and_replays_without_users_or_spec(stand):
    app, source = stand
    r = await post(app)
    assert r.status_code == 201
    result = r.json()
    assert result["persona"]["companyId"]
    assert result["persona"]["code"] == "custom-demo"
    assert result["applied"] == VIEW["applied"]
    assert "users" not in r.text
    assert "expanded" not in r.text
    assert "must-never-appear" not in r.text
    company_id = result["persona"]["companyId"]
    assert counts() == (1, 1)
    again = await post(app)
    assert again.status_code == 201
    assert again.json() == result
    assert again.headers["Idempotent-Replayed"] == "true"
    assert source.calls == 1
    assert counts() == (1, 1)
    with db.transaction() as s:
        company = companies.by_inn(s, VIEW["inn"])
        assert str(company.id) == company_id
        assert len(companies.people(s, company.id)) == 1
    reused = await post(app, {"title": "Different", "preset": "IP_HEALTHY"})
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert source.calls == 1


@pytest.mark.anyio
async def test_lost_upstream_reply_uses_same_key_and_recovers(stand):
    app, source = stand
    source.lose_reply = True
    assert (await post(app)).status_code == 502
    assert counts() == (0, 0)
    result = await post(app)
    assert result.status_code == 201
    assert source.calls == 2
    assert len(source.by_key) == 1
    assert counts() == (1, 1)


@pytest.mark.anyio
async def test_local_rollback_after_upstream_commit_can_be_recovered(stand, monkeypatch):
    app, source = stand
    original = audit.record

    def fail(*args, **kwargs):
        raise RuntimeError("audit failure")

    monkeypatch.setattr(audit, "record", fail)
    assert (await post(app)).status_code == 500
    assert counts() == (0, 0)
    monkeypatch.setattr(audit, "record", original)
    assert (await post(app)).status_code == 201
    assert len(source.by_key) == 1
    assert counts() == (1, 1)


@pytest.mark.anyio
async def test_concurrent_key_does_not_create_again(stand):
    import asyncio

    app, source = stand
    source.block = True
    first = asyncio.create_task(post(app))
    try:
        assert await asyncio.to_thread(source.entered.wait, 5)
        second = await post(app)
        assert second.status_code == 409
        assert second.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
        assert source.calls == 1
    finally:
        source.release.set()
    assert (await first).status_code == 201
    assert counts() == (1, 1)


@pytest.mark.anyio
async def test_demo_gate_header_and_provider_rejection(stand):
    app, source = stand
    assert (await post(app, key=None)).status_code == 422
    assert (await post(app, key=" ")).status_code == 422
    assert source.calls == 0
    source.rejection = scenarios.ScenarioRejectedError(422, "VALIDATION_ERROR")
    assert (await post(app, {"title": "No explicit form"})).status_code == 422
    assert counts() == (0, 0)
    source.rejection = scenarios.ScenarioRejectedError(409, "SCENARIO_EXISTS")
    assert (await post(app)).status_code == 409
    app.state.settings = app.state.settings.model_copy(update={"demo_mode": False})
    assert (await post(app)).status_code == 403
    assert counts() == (0, 0)


@pytest.mark.anyio
async def test_cloud_creation_is_open_without_stand_code_but_rate_limited(stand):
    app, source = stand
    app.state.settings = Settings(
        app_env="cloud", demo_controls_per_minute=1, **{n: f"real-{n}" for n in DEV_SECRETS}
    )
    r = await post(app)
    assert r.status_code == 201
    assert (await post(app)).status_code == 429
    assert source.calls == 1


@pytest.mark.anyio
async def test_retry_during_persona_reset_does_not_rewrite_directory(stand):
    app, source = stand
    with db.transaction() as s:
        company = companies.apply_scenario(s, VIEW)
        assert company is not None
    scope = companies.for_scenario("custom-demo")
    with operations.hold(lambda: scope, exclusive=True):
        r = await post(app)
        assert r.status_code == 409
        assert r.json()["code"] == "DEMO_RESET_IN_PROGRESS"
    assert counts() == (1, 0)
    assert (await post(app)).status_code == 201
    assert counts() == (1, 1)


@pytest.mark.anyio
async def test_generated_code_is_stable_across_lost_response(stand):
    app, source = stand
    body = {"title": "Generated", "preset": "IP_HEALTHY"}
    source.lose_reply = True
    assert (await post(app, body)).status_code == 502
    created_code = source.by_key["create-once"]["code"]
    assert created_code.startswith("demo-api-")
    assert (await post(app, body)).json()["persona"]["code"] == created_code
    assert len(source.by_key) == 1
    assert counts() == (1, 1)


@pytest.mark.anyio
async def test_unsupported_login_reference_is_rejected_before_upstream_side_effect(stand):
    app, source = stand
    r = await post(
        app, {**SPEC, "code": "c" * 64, "users": [{"login": "u" * 64, "role": "DIRECTOR"}]}
    )
    assert r.status_code == 422
    assert source.calls == 0
    assert counts() == (0, 0)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user",
    [
        {"login": "owner", "role": "ADMIN"},
        {"login": "owner", "role": "DIRECTOR", "fullName": "x" * 201},
    ],
)
async def test_unsupported_account_data_is_rejected_before_source(stand, user):
    app, source = stand
    assert (await post(app, {**SPEC, "users": [user]})).status_code == 422
    assert source.calls == 0


@pytest.mark.anyio
async def test_partial_upstream_failure_without_cached_reply_cannot_generate_second_code(
    stand, monkeypatch
):
    app, _ = stand
    codes = set()

    def partial(body, *, idempotency_key):
        if body["code"] in codes:
            raise scenarios.ScenarioRejectedError(409, "SCENARIO_EXISTS")
        codes.add(body["code"])
        raise scenarios.ScenariosUnavailableError("Saved FAILED, upstream did not cache 502")

    monkeypatch.setattr(scenarios, "create_scenario", partial)
    body = {"title": "Partial", "preset": "IP_HEALTHY"}
    assert (await post(app, body)).status_code == 502
    assert (await post(app, body)).status_code == 409
    assert len(codes) == 1
    assert counts() == (0, 0)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_view",
    [
        {**VIEW, "code": "wrong-code"},
        {**VIEW, "applied": {"registry": "OK"}},
        {**VIEW, "status": "FAILED"},
    ],
)
async def test_incomplete_or_mismatched_provider_result_does_not_sync_directory(stand, bad_view):
    app, source = stand
    source.by_key["create-once"] = bad_view
    r = await post(app)
    assert r.status_code == 502
    assert r.json()["code"] == "DEMO_SCENARIO_INVALID_RESPONSE"
    assert counts() == (0, 0)
