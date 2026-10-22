"""T-129 (часть): POST /scenarios/reset — очистка четырёх моков, chaos в OK, встроенные из кода."""

import asyncio
from typing import Any

import httpx
import pytest

from tests.scenarios_network import Harness
from tests.test_bank_core import disbursement
from tests.test_scenarios_apply import assert_empty, create
from tests.test_scenarios_apply import h as h
from tests.test_scenarios_apply import urls as urls

pytestmark = pytest.mark.integration
ROLES = ("registry", "tax", "bki", "bank_core")


async def reset(h: Harness, mode: str | None = None) -> Any:
    body = {"mode": mode} if mode else None
    return await h.api.post("/api/v1/scenarios/reset", json=body)


async def chaos_modes(h: Harness) -> dict[str, str]:
    return {role: (await h.clients[role].get("/admin/chaos")).json()["mode"] for role in ROLES}


async def issue_loan(h: Harness, inn: str, account: str, key: str) -> Any:
    response = await h.clients["bank_core"].post(
        "/api/v1/disbursements",
        json=disbursement(account, customerInn=inn),
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response


async def loans(h: Harness, inn: str) -> list[Any]:
    response = await h.clients["bank_core"].get(f"/api/v1/customers/{inn}/loans")
    assert response.status_code == 200, response.text
    return response.json()["loans"]


async def test_reset_removes_runtime_loan_and_returns_chaos_to_ok(h: Harness) -> None:
    first = await reset(h)
    assert first.status_code == 200, first.text
    sokolova = (await h.api.get("/api/v1/scenarios/sokolova")).json()
    inn = sokolova["inn"]
    account = sokolova["expanded"]["bankCore"]["accounts"][0]["number"]
    balance = (await h.clients["bank_core"].get(f"/api/v1/accounts/{account}")).json()["balanceRub"]
    await issue_loan(h, inn, account, "reset-loan")
    assert len(await loans(h, inn)) == 1
    for role, mode in (("bki", "DOWN"), ("tax", "ERROR"), ("registry", "SLOW")):
        put = await h.clients[role].put("/admin/chaos", json={"mode": mode})
        assert put.status_code == 200, put.text
    assert set((await chaos_modes(h)).values()) == {"DOWN", "ERROR", "SLOW", "OK"}

    response = await reset(h, "KEEP_CUSTOM")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "KEEP_CUSTOM"
    assert body["chaos"] == dict.fromkeys(("registry", "tax", "bki", "bankCore"), "OK")
    assert await chaos_modes(h) == dict.fromkeys(ROLES, "OK")
    assert await loans(h, inn) == []
    after = (await h.clients["bank_core"].get(f"/api/v1/accounts/{account}")).json()
    assert after["balanceRub"] == balance
    assert [(s["code"], s["status"]) for s in body["scenarios"]] == [("sokolova", "APPLIED")]
    # ключ идемпотентности выдачи стёрт вместе с данными: повтор создаёт новый кредит
    again = await issue_loan(h, inn, account, "reset-loan")
    assert len(await loans(h, inn)) == 1
    assert again.json()["loanId"] is not None


async def test_default_body_is_keep_custom_and_custom_survives(h: Harness) -> None:
    custom = await create(h, "kept-custom")
    response = await reset(h)
    assert response.status_code == 200, response.text
    codes = {s["code"]: s for s in response.json()["scenarios"]}
    assert codes["kept-custom"]["status"] == "APPLIED"
    assert response.json()["deleted"] == []
    assert (
        await h.clients["registry"].get(f"/api/v1/companies/{custom['inn']}")
    ).status_code == 200


async def test_builtin_only_deletes_custom_scenarios_and_their_data(h: Harness) -> None:
    custom = await create(h, "gone-custom")
    response = await reset(h, "BUILTIN_ONLY")
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] == ["gone-custom"]
    assert [s["code"] for s in response.json()["scenarios"]] == ["sokolova"]
    assert (await h.api.get("/api/v1/scenarios/gone-custom")).status_code == 404
    await assert_empty(h, "gone-custom")
    assert (
        await h.clients["registry"].get(f"/api/v1/companies/{custom['inn']}")
    ).status_code == 404


async def test_modified_builtin_returns_to_source(h: Harness) -> None:
    await reset(h)
    patched = await h.api.patch("/api/v1/scenarios/sokolova", json={"tax": {"taxDebtRub": 777}})
    assert patched.status_code == 200, patched.text
    assert patched.json()["modified"] is True
    inn = patched.json()["inn"]
    changed = await h.clients["tax"].get(f"/api/v1/tax-profile/{inn}")
    assert changed.json()["debts"]["taxDebtRub"] == 777
    assert (await reset(h)).status_code == 200
    restored = (await h.api.get("/api/v1/scenarios/sokolova")).json()
    assert restored["modified"] is False
    assert restored["status"] == "APPLIED"
    assert "tax" not in restored["spec"]
    back = await h.clients["tax"].get(f"/api/v1/tax-profile/{inn}")
    assert back.json()["debts"]["taxDebtRub"] != 777


async def test_failure_names_system_and_repeat_completes(h: Harness) -> None:
    await reset(h)
    await create(h, "before-failure")
    h.network.down.add("bki")
    failed = await reset(h)
    assert failed.status_code == 502, failed.text
    assert failed.json()["code"] == "RESET_FAILED"
    assert "BKI" in failed.json()["detail"]
    statuses = {s["code"]: s["status"] for s in (await h.api.get("/api/v1/scenarios")).json()}
    assert set(statuses.values()) == {"PENDING"}
    h.network.down.clear()
    done = await reset(h)
    assert done.status_code == 200, done.text
    assert {s["status"] for s in done.json()["scenarios"]} == {"APPLIED"}
    assert await chaos_modes(h) == dict.fromkeys(ROLES, "OK")


async def test_failed_apply_after_wipe_is_reported_and_repeat_completes(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await reset(h)
    original = h.network.handle_async_request

    async def broken_subjects(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mock-tax" and request.url.path.startswith("/admin/subjects"):
            return httpx.Response(500, json={"detail": "Тест сбоя"})
        return await original(request)

    monkeypatch.setattr(h.network, "handle_async_request", broken_subjects)
    failed = await reset(h)
    assert failed.status_code == 502, failed.text
    assert failed.json()["code"] == "RESET_FAILED"
    assert "sokolova" in failed.json()["detail"]
    assert (await h.api.get("/api/v1/scenarios/sokolova")).json()["status"] == "FAILED"
    monkeypatch.undo()
    assert (await reset(h)).status_code == 200
    assert (await h.api.get("/api/v1/scenarios/sokolova")).json()["status"] == "APPLIED"


async def test_parallel_resets_are_serialized(h: Harness) -> None:
    await reset(h)
    h.network.pause = "registry"
    h.network.entered.clear()
    first = asyncio.create_task(reset(h))
    try:
        await asyncio.wait_for(h.network.entered.wait(), 5)
        second = asyncio.create_task(reset(h))
        await asyncio.sleep(0.3)
        assert not second.done()  # ждёт advisory lock, а не мешает первому
    finally:
        h.network.pause = None
        h.network.release.set()
    results = await asyncio.gather(first, second)
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert (await h.api.get("/api/v1/scenarios/sokolova")).json()["status"] == "APPLIED"


async def test_invalid_mode_is_rejected(h: Harness) -> None:
    response = await reset(h, "EVERYTHING")
    assert response.status_code == 422
