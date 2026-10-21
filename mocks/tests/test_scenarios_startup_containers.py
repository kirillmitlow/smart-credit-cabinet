"""T-128: реальный старт до ready и перезапуск процесса без потери выданного кредита."""

import time

import httpx
import pytest
from testcontainers.core.container import DockerContainer

from tests.test_bank_core import disbursement
from tests.test_scenarios_apply_containers import live_roles as live_roles
from tests.test_scenarios_apply_containers import wait_ready

pytestmark = pytest.mark.integration


def restart(client: httpx.Client, container: DockerContainer) -> float:
    started = time.monotonic()
    container.get_wrapped_container().stop(timeout=1)
    container.get_wrapped_container().start()
    container.get_wrapped_container().reload()
    client.base_url = (
        f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8000)}"
    )
    wait_ready(client)
    return time.monotonic() - started


def test_ready_contains_builtin_and_restart_preserves_runtime(
    live_roles: tuple[dict[str, httpx.Client], DockerContainer, DockerContainer],
) -> None:
    clients, bki, scenarios = live_roles
    record = clients["scenarios"].get("/api/v1/scenarios/sokolova")
    assert record.status_code == 200, record.text
    before = record.json()
    assert before["status"] == "APPLIED"
    account = before["expanded"]["bankCore"]["accounts"][0]["number"]
    issued = clients["bank_core"].post(
        "/api/v1/disbursements",
        json=disbursement(account),
        headers={"Idempotency-Key": "container-startup-preserve"},
    )
    assert issued.status_code == 201, issued.text
    report = clients["bki"].post(
        "/api/v1/credit-reports",
        json={
            "subject": before["expanded"]["bki"][0]["body"]["subject"],
            "purpose": "LOAN_APPLICATION",
            "consent": {
                "consentId": "startup",
                "subjectInn": before["inn"],
                "signedAt": "2026-10-21T10:00:00Z",
                "validUntil": "2026-11-21",
                "purpose": "LOAN_APPLICATION",
            },
        },
    )
    assert report.status_code == 200, report.text
    elapsed = restart(clients["scenarios"], scenarios)
    print(f"T-128 scenarios restart to ready: {elapsed:.2f}s")
    assert elapsed < 60
    assert clients["scenarios"].get("/api/v1/scenarios/sokolova").json() == before
    account_view = clients["bank_core"].get(f"/api/v1/accounts/{account}")
    assert account_view.json()["balanceRub"] == 912300
    assert clients["bank_core"].get(f"/api/v1/loans/{issued.json()['loanId']}").status_code == 200
    assert (
        clients["bki"].get(f"/api/v1/credit-reports/{report.json()['reportId']}").status_code == 200
    )
    bki.get_wrapped_container().stop(timeout=1)
    try:
        assert restart(clients["scenarios"], scenarios) < 60
        assert clients["scenarios"].get("/health/ready").status_code == 200
        assert clients["scenarios"].get("/api/v1/scenarios/sokolova").json()["status"] == "PARTIAL"
        assert (
            clients["bank_core"].get(f"/api/v1/accounts/{account}").json()["balanceRub"] == 912300
        )
    finally:
        bki.get_wrapped_container().start()
