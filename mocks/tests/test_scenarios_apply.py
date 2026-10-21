"""T-127: публичное применение, откат, изоляция компаний и конкурентные запросы."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select

from app.common.clock import Clock
from app.main import create_app
from app.roles.scenarios.credit_uid import contract_uid
from app.roles.scenarios.gateway import AdminGateway, get_gateway
from app.roles.scenarios.models import Scenario, ScenarioApplication
from app.roles.scenarios.presets import PRESETS
from app.roles.scenarios.recovery import recover_once
from tests.conftest import ADMIN_KEY, API_KEY, database_url, make_settings
from tests.scenarios_network import Harness, RoleNetwork
from tests.test_bank_core import disbursement

pytestmark = pytest.mark.integration
ROLES = ("registry", "tax", "bki", "bank_core", "scenarios")


@pytest.fixture(scope="module")
def urls(postgres_url: str) -> dict[str, str]:
    return {role: database_url(postgres_url, f"apply_{role}_test") for role in ROLES}


@pytest.fixture
async def h(urls: dict[str, str]) -> AsyncIterator[Harness]:
    apps = {
        role: create_app(
            make_settings(mock_role=role, database_url=url, app_today=date(2026, 10, 21))
        )
        for role, url in urls.items()
    }
    try:
        async with AsyncExitStack() as stack:
            clients = {}
            for role, app in apps.items():
                app.state.clock = Clock(
                    date(2026, 10, 21), real_now=lambda: datetime(2026, 10, 21, 12, tzinfo=UTC)
                )
                await app.state.database.migrate()
                clients[role] = await stack.enter_async_context(
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                        base_url="http://mock",
                        headers={"X-Admin-Key": ADMIN_KEY, "X-Api-Key": API_KEY},
                    )
                )
                if role != "scenarios":
                    assert (await clients[role].post("/admin/wipe")).status_code == 204
            async with apps["scenarios"].state.database.sessions() as session:
                await session.execute(delete(Scenario))
                await session.commit()
            network = RoleNetwork(apps)
            remote = await stack.enter_async_context(httpx.AsyncClient(transport=network))
            gateway = AdminGateway(remote, apps["scenarios"].state.settings)

            async def dependency() -> AdminGateway:
                return gateway

            apps["scenarios"].dependency_overrides[get_gateway] = dependency
            yield Harness(apps, clients, network)
    finally:
        for app in apps.values():
            await app.state.database.dispose()


def spec(code: str, **kwargs: Any) -> dict[str, Any]:
    return {"code": code, "title": "Компания для применения", "preset": "IP_HEALTHY", **kwargs}


async def create(h: Harness, code: str, **kwargs: Any) -> dict[str, Any]:
    response = await h.api.post("/api/v1/scenarios", json=spec(code, **kwargs))
    assert response.status_code == 201, response.text
    return response.json()


async def assert_empty(h: Harness, code: str) -> None:
    for role in ROLES[:-1]:
        response = await h.clients[role].get("/admin/subjects", params={"scenario": code})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0, (role, response.text)


async def recover(h: Harness) -> None:
    async with httpx.AsyncClient(transport=h.network) as remote:
        app = h.apps["scenarios"]
        await recover_once(
            app.state.database, AdminGateway(remote, app.state.settings), app.state.clock
        )


async def test_create_is_visible_in_business_apis_with_log(h: Harness) -> None:
    body = await create(h, "success")
    assert body["status"] == "APPLIED"
    assert body["applied"] == dict.fromkeys(("registry", "tax", "bki", "bankCore"), "OK")
    inn = body["inn"]
    for role, path in (
        ("registry", f"/api/v1/companies/{inn}"),
        ("tax", f"/api/v1/tax-profile/{inn}"),
        ("bank_core", f"/api/v1/customers/{inn}"),
    ):
        assert (await h.clients[role].get(path)).status_code == 200
    assert (
        body["applications"]
        == (await h.api.get("/api/v1/scenarios/success")).json()["applications"]
    )
    puts = [entry for entry in body["applications"] if entry["action"] == "PUT"]
    assert {entry["system"] for entry in puts} == {"REGISTRY", "TAX", "BKI", "BANK_CORE"}
    assert all(entry["httpStatus"] == 201 and entry["error"] is None for entry in puts)
    assert [r for r, action, _ in h.network.calls if action == "PUT"] == [
        "registry",
        "tax",
        "bki",
        "bank_core",
    ]


async def test_self_employed_skips_empty_roles_and_non_customer_keeps_screening(h: Harness) -> None:
    own = await create(h, "self", preset="SELF_EMPLOYED")
    assert own["applied"]["bankCore"] == own["applied"]["bki"] == "SKIPPED"
    body = await create(h, "non-customer", preset="LLC_HEALTHY")
    assert body["applied"]["bankCore"] == "OK"
    customer = await h.clients["bank_core"].get(f"/api/v1/customers/{body['inn']}")
    assert customer.status_code == 404
    screening = await h.clients["bank_core"].post(
        "/api/v1/compliance/screening", json={"subjects": [{"inn": body["inn"], "role": "COMPANY"}]}
    )
    assert screening.status_code == 200
    assert screening.json()["results"][0]["zsk"]["riskLevel"] == "GREEN"


@pytest.mark.parametrize("role", ROLES[:-1])
async def test_unreachable_role_leaves_other_roles_empty_and_error_durable(
    h: Harness, role: str
) -> None:
    h.network.down.add(role)
    response = await h.api.post("/api/v1/scenarios", json=spec("unreachable"))
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "APPLY_FAILED"
    assert role.upper() in response.json()["detail"]
    stored = (await h.api.get("/api/v1/scenarios/unreachable")).json()
    assert stored["status"] == "FAILED"
    assert len(stored["applications"]) == 8
    assert any(entry["error"] for entry in stored["applications"])
    await assert_empty(h, "unreachable")
    h.network.down.clear()
    await recover(h)
    assert (
        "откат завершён" in (await h.api.get("/api/v1/scenarios/unreachable")).json()["lastError"]
    )


@pytest.mark.parametrize("role", ["tax", "bki", "bank_core"])
async def test_lost_response_after_write_is_cleaned_when_system_returns(
    h: Harness, role: str
) -> None:
    h.network.lose_after_put = role
    response = await h.api.post("/api/v1/scenarios", json=spec("lost-response"))
    assert response.status_code == 502, response.text
    subjects = (
        await h.clients[role].get("/admin/subjects", params={"scenario": "lost-response"})
    ).json()
    assert subjects["total"] > 0  # запись закоммичена, её ответ потерян
    for other in set(ROLES[:-1]) - {role}:
        assert (
            await h.clients[other].get("/admin/subjects", params={"scenario": "lost-response"})
        ).json()["total"] == 0
    # Новый экземпляр приложения/worker читает долговечный журнал, а не память запроса.
    h.network.down.clear()
    await recover(h)
    await assert_empty(h, "lost-response")
    result = await h.api.post("/api/v1/scenarios/lost-response/apply")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "APPLIED"


async def test_http_error_stops_sequence_and_rolls_back(h: Harness) -> None:
    h.network.bad_status = ("tax", 422)
    response = await h.api.post("/api/v1/scenarios", json=spec("remote-error"))
    assert response.status_code == 502
    await assert_empty(h, "remote-error")
    assert not any(role == "bki" and action == "PUT" for role, action, _ in h.network.calls)


async def test_apply_resets_runtime_and_preserves_other_company(h: Harness) -> None:
    """TS-101: часть сброса моков; общий demo/reset и данные api проверяются позже."""
    first = await create(h, "runtime-reset")
    other = await create(h, "untouched")
    other_report_body = {
        "subject": other["expanded"]["bki"][0]["body"]["subject"],
        "purpose": "LOAN_APPLICATION",
        "consent": {
            "consentId": "other",
            "subjectInn": other["inn"],
            "signedAt": "2026-10-21T10:00:00Z",
            "validUntil": "2026-11-21",
            "purpose": "LOAN_APPLICATION",
        },
    }
    other_report = await h.clients["bki"].post(
        "/api/v1/credit-reports",
        json=other_report_body,
        headers={"Idempotency-Key": "other-report"},
    )
    assert other_report.status_code == 200, other_report.text
    inn = first["inn"]
    account = first["expanded"]["bankCore"]["accounts"][0]["number"]
    initial = (await h.clients["bank_core"].get(f"/api/v1/accounts/{account}")).json()["balanceRub"]
    body = disbursement(
        account,
        customerInn=inn,
        contract={
            "number": "DEMO",
            "uid": contract_uid("run", inn, "one"),
            "signedAt": "2026-10-21T10:00:00Z",
        },
    )
    issued = await h.clients["bank_core"].post(
        "/api/v1/disbursements", json=body, headers={"Idempotency-Key": "runtime-one"}
    )
    assert issued.status_code == 201, issued.text
    bki = first["expanded"]["bki"][0]["body"]["subject"]
    report = await h.clients["bki"].post(
        "/api/v1/credit-reports",
        headers={"Idempotency-Key": "runtime-report"},
        json={
            "subject": bki,
            "purpose": "LOAN_APPLICATION",
            "consent": {
                "consentId": "one",
                "subjectInn": inn,
                "signedAt": "2026-10-21T10:00:00Z",
                "validUntil": "2026-11-21",
                "purpose": "LOAN_APPLICATION",
            },
        },
    )
    assert report.status_code == 200, report.text
    response = await h.api.post("/api/v1/scenarios/runtime-reset/apply")
    assert response.status_code == 200, response.text
    assert response.json()["inn"] == inn
    assert (await h.clients["bank_core"].get(f"/api/v1/accounts/{account}")).json()[
        "balanceRub"
    ] == initial
    assert (await h.clients["bank_core"].get(f"/api/v1/customers/{inn}/loans")).json()[
        "loans"
    ] == []
    assert (
        await h.clients["bki"].get(f"/api/v1/credit-reports/{report.json()['reportId']}")
    ).status_code == 404
    other_after = (await h.api.get("/api/v1/scenarios/untouched")).json()
    assert other_after == other
    assert (
        await h.clients["bank_core"].get(f"/api/v1/customers/{other['inn']}")
    ).status_code == 200

    reissued = await h.clients["bank_core"].post(
        "/api/v1/disbursements", json=body, headers={"Idempotency-Key": "runtime-one"}
    )
    assert reissued.status_code == 201, reissued.text
    assert reissued.json()["loanId"] != issued.json()["loanId"]
    again = await h.clients["bki"].post(
        "/api/v1/credit-reports",
        content=report.request.content,
        headers={"Idempotency-Key": "runtime-report", "Content-Type": "application/json"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["reportId"] != report.json()["reportId"]
    replay = await h.clients["bki"].post(
        "/api/v1/credit-reports",
        json=other_report_body,
        headers={"Idempotency-Key": "other-report"},
    )
    assert replay.content == other_report.content
    assert replay.headers["Idempotent-Replayed"] == "true"


async def test_concurrent_same_key_is_in_progress_without_second_apply(h: Harness) -> None:
    h.network.pause = "registry"
    body, headers = spec("concurrent"), {"Idempotency-Key": "apply-concurrent"}
    first = asyncio.create_task(h.api.post("/api/v1/scenarios", json=body, headers=headers))
    try:
        await asyncio.wait_for(h.network.entered.wait(), 5)
        second = await asyncio.wait_for(
            h.api.post("/api/v1/scenarios", json=body, headers=headers), 2
        )
        assert second.status_code == 409, second.text
        assert second.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
        await recover(h)  # worker видит занятый mutex и не откатывает активную операцию
    finally:
        h.network.release.set()
        result = await first
    assert result.status_code == 201, result.text
    again = await h.api.post("/api/v1/scenarios", json=body, headers=headers)
    assert again.content == result.content
    assert sum(action == "PUT" and role == "registry" for role, action, _ in h.network.calls) == 1


async def test_patch_reapplies_and_delete_cleans_all_roles(h: Harness) -> None:
    before = await create(h, "patch-delete")
    patched = await h.api.patch(
        "/api/v1/scenarios/patch-delete", json={"tax": {"taxDebtRub": 12345}}
    )
    assert patched.status_code == 200, patched.text
    tax = await h.clients["tax"].get(f"/api/v1/tax-profile/{before['inn']}")
    assert tax.json()["debts"]["taxDebtRub"] == 12345
    assert (await h.api.delete("/api/v1/scenarios/patch-delete")).status_code == 204
    await assert_empty(h, "patch-delete")
    assert (await h.api.get("/api/v1/scenarios/patch-delete")).status_code == 404


async def test_failed_delete_is_completed_after_restart(h: Harness) -> None:
    await create(h, "failed-delete")
    h.network.down.add("tax")
    response = await h.api.delete("/api/v1/scenarios/failed-delete")
    assert response.status_code == 502
    h.network.down.clear()
    await recover(h)
    await assert_empty(h, "failed-delete")
    assert (await h.api.get("/api/v1/scenarios/failed-delete")).status_code == 404


async def test_crash_after_put_intent_is_recovered_from_journal(h: Harness) -> None:
    await create(h, "crash")
    db = h.apps["scenarios"].state.database
    async with db.sessions() as session:
        row = await session.get(Scenario, "crash")
        row.status = "PENDING"
        row.needs_reapply = True
        session.add(
            ScenarioApplication(
                scenario_code="crash",
                system="BKI",
                action="PUT",
                at=h.apps["scenarios"].state.clock.now(),
            )
        )
        await session.commit()
    await recover(h)
    await assert_empty(h, "crash")
    async with db.sessions() as session:
        assert (
            await session.scalar(select(Scenario.status).where(Scenario.code == "crash"))
            == "FAILED"
        )


async def test_cancelled_request_releases_mutex_and_rolls_back_partial_writes(h: Harness) -> None:
    h.network.pause = "bank_core"
    pending = asyncio.create_task(h.api.post("/api/v1/scenarios", json=spec("cancelled")))
    await asyncio.wait_for(h.network.entered.wait(), 5)
    pending.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pending
    assert (await h.clients["bki"].get("/admin/subjects", params={"scenario": "cancelled"})).json()[
        "total"
    ] > 0
    await asyncio.wait_for(recover(h), 5)
    await assert_empty(h, "cancelled")
    assert (await h.api.get("/api/v1/scenarios/cancelled")).json()["status"] == "FAILED"


@pytest.mark.parametrize("preset", list(PRESETS))
async def test_every_preset_applies_all_bki_people(h: Harness, preset: str) -> None:
    view = await create(h, "all-people", preset=preset)
    assert view["status"] == "APPLIED"
    for subject in view["expanded"]["bki"]:
        stored = await h.clients["bki"].get(f"/admin/subjects/{subject['inn']}")
        assert stored.status_code == 200, stored.text
        assert stored.json()["scenarioCode"] == "all-people"


async def test_deleted_scenario_is_not_replayed_from_idempotency_cache(h: Harness) -> None:
    body, headers = spec("recreate"), {"Idempotency-Key": "recreate-key"}
    first = await h.api.post("/api/v1/scenarios", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert (await h.api.delete("/api/v1/scenarios/recreate")).status_code == 204
    again = await h.api.post("/api/v1/scenarios", json=body, headers=headers)
    assert again.status_code == 201, again.text
    assert "Idempotent-Replayed" not in again.headers
    assert (await h.api.get("/api/v1/scenarios/recreate")).status_code == 200
