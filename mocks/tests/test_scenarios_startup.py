"""T-128: первое наполнение и восстановление только пустой роли без стирания RUNTIME."""

from datetime import date

import httpx
import pytest

from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.gateway import AdminGateway
from app.roles.scenarios.startup import initialize
from tests.scenarios_network import Harness
from tests.test_bank_core import disbursement
from tests.test_scenarios_apply import h as h
from tests.test_scenarios_apply import urls as urls

BUILTIN_CODES = sorted(s.code for s in builtin_scenarios(date(2026, 10, 21)))

pytestmark = pytest.mark.integration


async def fill(h: Harness) -> None:
    app = h.apps["scenarios"]
    async with httpx.AsyncClient(transport=h.network) as client:
        await initialize(
            app.state.database,
            AdminGateway(client, app.state.settings),
            app.state.clock,
            app.state.settings.bank_bik,
        )


async def view(h: Harness) -> dict:
    response = await h.api.get("/api/v1/scenarios/sokolova")
    assert response.status_code == 200, response.text
    return response.json()


async def test_initial_fill_and_second_start_preserve_runtime(h: Harness) -> None:
    ready = await h.api.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["db"] == "ok"
    await fill(h)
    before = await view(h)
    assert before["status"] == "APPLIED"
    account = before["expanded"]["bankCore"]["accounts"][0]["number"]
    issued = await h.clients["bank_core"].post(
        "/api/v1/disbursements",
        json=disbursement(account),
        headers={"Idempotency-Key": "startup-preserve"},
    )
    assert issued.status_code == 201, issued.text
    count = len(h.network.calls)
    await fill(h)
    assert all(action == "GET" for _, action, _ in h.network.calls[count:])
    assert await view(h) == before
    balance = (await h.clients["bank_core"].get(f"/api/v1/accounts/{account}")).json()["balanceRub"]
    assert balance == 912300


async def test_one_unavailable_system_marks_first_attempt_failed_without_puts(h: Harness) -> None:
    h.network.down.add("bki")
    await fill(h)
    record = await view(h)
    assert record["status"] == "FAILED"
    assert "BKI" in record["lastError"]
    assert not any(action == "PUT" for _, action, _ in h.network.calls)


async def test_only_empty_role_is_restored_from_stored_snapshot(h: Harness) -> None:
    await fill(h)
    before = await view(h)
    assert (await h.clients["tax"].post("/admin/wipe")).status_code == 204
    count = len(h.network.calls)
    await fill(h)
    # налоговая запись по каждой встроенной персоне: восстанавливается только пустая роль
    assert [(role, action) for role, action, _ in h.network.calls[count:] if action != "GET"] == [
        ("tax", "PUT")
    ] * len(BUILTIN_CODES)
    restored = await h.clients["tax"].get(f"/api/v1/tax-profile/{before['inn']}")
    assert restored.status_code == 200
    assert (await view(h))["expanded"] == before["expanded"]


async def test_unknown_inventory_does_not_overwrite_existing_data(h: Harness) -> None:
    await fill(h)
    before = await view(h)
    h.network.down.add("tax")
    count = len(h.network.calls)
    await fill(h)
    assert (await view(h))["status"] == "PARTIAL"
    assert all(action == "GET" for _, action, _ in h.network.calls[count:])
    h.network.down.clear()
    assert (await h.clients["tax"].get(f"/api/v1/tax-profile/{before['inn']}")).status_code == 200
