"""T-372: выборочная чистка всех владельцев, сбои и реальные гонки с фоновыми задачами."""

from __future__ import annotations

import asyncio
import copy
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text

from app.main import create_app
from app.modules import applications, audit, auth, companies, pipeline
from app.modules.demo import reset_persona
from app.modules.disbursement import tasks as disbursement_tasks
from app.modules.integrations import scenarios
from app.modules.pipeline.runner import run_pipeline
from app.shared import cache, clock, db, operations, outbox, resets, tasks
from app.shared.models import OutboxMessage
from app.shared.settings import Settings
from tests.integration.support import client_for
from tests.integration.test_demo_reset import INN, SCENARIO_VIEW, TODAY, counts, fill

pytestmark = pytest.mark.integration
OTHER_INN = "001234567895"


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(tasks, "send_now", lambda *a, **kw: None)
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, app_today=TODAY))
    database = db.get_database()
    db.migrate(database.engine)
    client = cache.get_redis()
    client.flushdb()
    with db.transaction() as session:
        resets.run_all_resets(session)
        policy_id = pipeline.register_current(session).id
    fill(policy_id)
    fill(policy_id, inn=OTHER_INN, suffix="-other")
    views, company_ids, principals = {}, {}, {}
    with db.transaction() as session:
        for code, inn, suffix in (("sokolova", INN, ""), ("other", OTHER_INN, "-other")):
            company = companies.by_inn(session, inn)
            company.scenario_code = code
            company.profile = {"old": True}
            company_ids[code] = company.id
            user = session.scalar(select(auth.User).where(auth.User.login_ref == "t:old" + suffix))
            principals[code] = auth.Principal(
                user_id=user.id,
                role="CLIENT",
                zone=auth.Zone.CLIENT,
                display_name="Клиент",
                person_inn=inn,
                memberships=(auth.Membership(company.id, "DIRECTOR", frozenset()),),
                active_company_id=company.id,
            )
            view = copy.deepcopy(SCENARIO_VIEW)
            view.update(code=code, inn=inn, status="APPLIED")
            view["expanded"]["identity"]["inn"] = inn
            view["users"][0]["inn"] = inn
            views[code] = view
    calls: list[tuple[str, str]] = []

    def apply(code: str, *, idempotency_key: str) -> dict[str, Any]:
        calls.append((code, idempotency_key))
        return views[code]

    monkeypatch.setattr(scenarios, "apply_one", apply)
    yield {
        "app": app,
        "companies": company_ids,
        "principals": principals,
        "views": views,
        "calls": calls,
        "redis": client,
        "apply": apply,
    }
    with db.transaction() as session:
        resets.run_all_resets(session)
    client.flushdb()
    database.dispose()


async def post(stand: dict[str, Any], code: str = "sokolova") -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stand["app"]), base_url="http://api"
    ) as client:
        return await client.post(f"/demo/personas/{code}/reset")


async def test_full_persona_reset_preserves_every_neighbour_journal_and_login(
    stand: dict[str, Any],
) -> None:
    before = counts()
    own, foreign = stand["companies"]["sokolova"], stand["companies"]["other"]
    client = stand["redis"]
    client.set(f"scc:gov-contracts:{own}", "old")
    client.set(f"scc:gov-contracts:{foreign}", "keep")
    client.set(f"lookup:registry:company:{INN}", "old")
    client.set(f"lookup:registry:company:{OTHER_INN}", "keep")
    old_code = auth.codes.issue(INN, "LOGIN", f"person|{own}")
    keep_code = auth.codes.issue(OTHER_INN, "LOGIN", f"person|{foreign}")
    signing_code = auth.codes.issue(INN, "SIGN_CONTRACT", "opaque-hash", company_id=own)
    other_signing_code = auth.codes.issue(
        OTHER_INN, "SIGN_CONTRACT", "other-hash", company_id=foreign
    )
    async with client_for(stand, "sokolova") as logged_in:
        response = await post(stand)
        assert response.status_code == 200, response.text
        assert response.json()["companyId"] == str(own)
        assert response.json()["generation"] == 1
        assert (await logged_in.get("/me")).status_code == 200
    after = counts()
    for table in (
        "applications",
        "application_versions",
        "application_events",
        "consents",
        "pipeline_runs",
        "decisions",
        "decision_reasons",
        "source_snapshots",
        "offers",
        "offer_variants",
        "contracts",
        "signatures",
        "disbursements",
        "loans",
        "payment_schedule",
        "outbox",
        "integration_calls",
        "idempotency_keys",
    ):
        assert after[table] == before[table] // 2, (table, before[table], after[table])
    with db.transaction() as session:
        records = list(session.scalars(select(audit.AuditRecord)))
        assert len(records) == 2
        assert {r.action for r in records} == {"LOGIN", "DEMO_PERSONA_RESET"}
        row = session.get(companies.Company, own)
        assert row.demo_resetting is False
        assert row.profile is None
    assert client.get(f"scc:gov-contracts:{own}") is None
    assert client.get(f"lookup:registry:company:{INN}") is None
    assert client.get(f"scc:gov-contracts:{foreign}") == "keep"
    assert client.get(f"lookup:registry:company:{OTHER_INN}") == "keep"
    assert client.get(auth.codes.KEY_PREFIX + old_code.request_id) is None
    assert client.get(auth.codes.KEY_PREFIX + keep_code.request_id) is not None
    assert client.get(auth.codes.KEY_PREFIX + signing_code.request_id) is None
    assert client.get(auth.codes.KEY_PREFIX + other_signing_code.request_id) is not None


@pytest.mark.parametrize("stage", ["MOCKS", "CACHE", "DATABASE"])
async def test_partial_failure_freezes_only_company_and_retry_finishes(
    stand: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    target, name = {
        "MOCKS": (scenarios, "apply_one"),
        "CACHE": (resets, "reset_persona_cache"),
        "DATABASE": (resets, "reset_persona_rows"),
    }[stage]
    real = getattr(target, name)
    own_principal = stand["principals"]["sokolova"]
    company_id = stand["companies"]["sokolova"]
    challenge = auth.codes.issue(
        INN, "LOGIN", f"{own_principal.user_id}|{company_id}", company_id=company_id
    )

    def broken(*args: Any, **kwargs: Any) -> Any:
        if stage == "DATABASE":
            real(*args, **kwargs)  # откат уже сделанных DELETE, включая журналы
        raise RuntimeError("принудительный сбой")

    monkeypatch.setattr(target, name, broken)
    failed = await post(stand)
    assert failed.status_code == 502, failed.text
    assert failed.json()["errors"][0]["step"] == stage
    assert counts()["applications"] == 2
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stand["app"]), base_url="http://api"
    ) as anonymous:
        issued = await anonymous.post(
            "/auth/request-code",
            json={"userId": str(own_principal.user_id), "companyId": str(company_id)},
        )
        assert issued.status_code == 409
        if stage == "MOCKS":  # кэш ещё не чистился: старый код существует, но вход ограждён
            verified = await anonymous.post(
                "/auth/verify-code",
                json={"requestId": challenge.request_id, "code": challenge.code},
            )
            assert verified.status_code == 409
    async with client_for(stand, "sokolova") as own, client_for(stand, "other") as foreign:
        blocked = await own.post("/applications", json={})
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "DEMO_RESET_IN_PROGRESS"
        assert blocked.headers["Retry-After"] == "1"
        blocked_lookup = await own.get(f"/companies/{stand['companies']['sokolova']}")
        assert blocked_lookup.status_code == 409
        assert (await foreign.get(f"/companies/{stand['companies']['other']}")).status_code == 200
    monkeypatch.setattr(target, name, real)
    done = await post(stand)
    assert done.status_code == 200, done.text
    assert done.json()["generation"] == 2
    assert counts()["applications"] == 1


async def test_two_resets_run_in_parallel_and_second_same_company_is_busy(
    stand: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = threading.Event(), threading.Event()

    def delayed(code: str, **kwargs: Any) -> Any:
        if code == "sokolova":
            entered.set()
            assert release.wait(10)
        return stand["apply"](code, **kwargs)

    monkeypatch.setattr(scenarios, "apply_one", delayed)
    first = asyncio.create_task(post(stand))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        assert (await post(stand)).status_code == 409
        neighbour = await post(stand, "other")
        assert neighbour.status_code == 200, neighbour.text
    finally:
        release.set()
    assert (await first).status_code == 200
    assert counts()["applications"] == 0


async def test_old_pipeline_and_disbursement_tasks_cannot_write_after_reset(
    stand: dict[str, Any],
) -> None:
    with db.transaction() as session:
        old_id = session.scalar(
            select(applications.Application.id).where(
                applications.Application.company_id == stand["companies"]["sokolova"]
            )
        )
    assert (await post(stand)).status_code == 200
    before = counts()
    assert run_pipeline(old_id).value == "SKIPPED"
    assert disbursement_tasks.run(old_id) == "SKIPPED"
    assert counts() == before
    async with client_for(stand, "sokolova") as client:
        fresh = await client.post(
            "/applications",
            json={"productCode": "EXPRESS"},
            headers={"Idempotency-Key": "after-reset"},
        )
        assert fresh.status_code == 201, fresh.text


def test_active_outbox_delivery_blocks_reset_until_final_audit_commits(
    stand: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.disbursement.delivery import _delivery_guard

    entered, release = threading.Event(), threading.Event()

    def handler(item: outbox.OutboxItem) -> outbox.Outcome:
        entered.set()
        assert release.wait(10)
        return outbox.Dead("test error")

    def dead_hook(session: Any, item: outbox.OutboxItem, error: str) -> None:
        audit.record(session, "OUTBOX_FAILED", object_type="outbox", object_id=str(item.id))

    outbox.register_handler("BKI", "E", handler, guard=_delivery_guard)
    outbox.set_dead_letter_hook(dead_hook)
    # Соседнее сообщение не участвует в этом тесте доставки.
    with db.transaction() as session:
        foreign_app = session.scalar(
            select(applications.Application.id).where(
                applications.Application.company_id == stand["companies"]["other"]
            )
        )
        session.execute(text("DELETE FROM outbox WHERE aggregate_id = :i"), {"i": str(foreign_app)})
    with ThreadPoolExecutor(max_workers=1) as pool:
        session_now = clock.system_now()
        with db.transaction() as session:
            session.execute(
                text("UPDATE outbox SET created_at = :t, next_attempt_at = :t"), {"t": session_now}
            )
        future = pool.submit(outbox.relay, budget_s=5)
        try:
            assert entered.wait(10)
            with pytest.raises(operations.ResetInProgress):
                reset_persona.run("sokolova")
            assert stand["calls"] == []
        finally:
            release.set()
        future.result(timeout=10)
    reset_persona.run("sokolova")
    with db.transaction() as session:
        assert session.scalar(select(OutboxMessage.id)) is None
        assert (
            session.scalar(
                select(audit.AuditRecord.id).where(audit.AuditRecord.action == "OUTBOX_FAILED")
            )
            is None
        )
    outbox.clear_handlers()
    outbox.set_dead_letter_hook(None)


async def test_unknown_persona_has_no_side_effects(stand: dict[str, Any]) -> None:
    before = counts()
    assert (await post(stand, "missing")).status_code == 404
    assert counts() == before
    assert stand["calls"] == []


def test_claimed_outbox_delayed_before_guard_does_not_deliver_after_reset(
    stand: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.applications import operations as application_operations
    from app.modules.disbursement.delivery import _delivery_guard

    entered, release = threading.Event(), threading.Event()
    original = application_operations.scope
    first = True
    delivered: list[int] = []

    def delayed(application_id: Any) -> operations.Scope | None:
        nonlocal first
        result = original(application_id)
        if first:
            first = False
            entered.set()
            assert release.wait(10)
        return result

    def handler(item: outbox.OutboxItem) -> outbox.Outcome:
        delivered.append(item.id)
        return outbox.Delivered()

    monkeypatch.setattr(application_operations, "scope", delayed)
    outbox.register_handler("BKI", "E", handler, guard=_delivery_guard)
    with db.transaction() as session:
        foreign_app = session.scalar(
            select(applications.Application.id).where(
                applications.Application.company_id == stand["companies"]["other"]
            )
        )
        session.execute(text("DELETE FROM outbox WHERE aggregate_id = :i"), {"i": str(foreign_app)})
        session.execute(
            text("UPDATE outbox SET created_at = :t, next_attempt_at = :t"),
            {"t": clock.system_now()},
        )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(outbox.relay, budget_s=5)
            try:
                assert entered.wait(10)
                reset_persona.run("sokolova")
                before = counts()
            finally:
                release.set()
            future.result(timeout=10)
        assert delivered == []
        assert counts() == before
    finally:
        outbox.clear_handlers()


def test_apply_one_uses_admin_and_distinct_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "APPLIED", "code": "sokolova"})

    real = httpx.Client
    monkeypatch.setattr(
        scenarios.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    assert scenarios.apply_one("sokolova", idempotency_key="reset:1")["status"] == "APPLIED"
    assert requests[0].url.path == "/api/v1/scenarios/sokolova/apply"
    assert requests[0].headers["Idempotency-Key"] == "reset:1"
    assert requests[0].headers["X-Admin-Key"]
