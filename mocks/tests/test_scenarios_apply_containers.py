"""T-127: реальные HTTP, пять контейнеров моков, остановка/возвращение БКИ и фоновый откат."""

import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.docker_client import DockerClient
from testcontainers.core.network import Network

from tests.conftest import ADMIN_KEY, API_KEY, POSTGRES_IMAGE, database_url

pytestmark = pytest.mark.integration
ROLES = ("registry", "tax", "bki", "bank_core", "scenarios")


def wait_ready(client: httpx.Client) -> None:
    deadline = time.monotonic() + 45
    last = ""
    while time.monotonic() < deadline:
        try:
            response = client.get("/health/ready")
            if response.status_code == 200:
                return
            last = response.text
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        time.sleep(0.1)
    pytest.fail(f"Мок не стал готов: {last}")


@pytest.fixture(scope="module")
def live_roles() -> Iterator[tuple[dict[str, httpx.Client], DockerContainer]]:
    image = "scc-mocks-t127-test:local"
    DockerClient().client.images.build(
        path=str(Path(__file__).resolve().parents[1]), tag=image, rm=True
    )
    with ExitStack() as stack:
        network = stack.enter_context(Network())
        pg = stack.enter_context(
            PostgresContainer(POSTGRES_IMAGE, driver="asyncpg")
            .with_network(network)
            .with_network_aliases("database")
        )
        containers, clients = {}, {}
        for role in ROLES:
            url = database_url(pg.get_connection_url(), f"container_{role}_test")
            internal_url = f"postgresql+asyncpg://test:test@database:5432/container_{role}_test"
            assert url.endswith(f"/container_{role}_test")
            container = DockerContainer(image).with_network(network).with_network_aliases(role)
            container.with_exposed_ports(8000)
            for key, value in {
                "MOCK_ROLE": role,
                "DATABASE_URL": internal_url,
                "MOCK_ADMIN_KEY": ADMIN_KEY,
                "MOCK_API_KEYS": f"api:{API_KEY}",
                "APP_TODAY": "2026-10-21",
                "REGISTRY_URL": "http://registry:8000",
                "TAX_URL": "http://tax:8000",
                "BKI_URL": "http://bki:8000",
                "BANK_CORE_URL": "http://bank_core:8000",
            }.items():
                container.with_env(key, value)
            containers[role] = stack.enter_context(container)
            client = stack.enter_context(
                httpx.Client(
                    base_url=f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8000)}",
                    headers={"X-Admin-Key": ADMIN_KEY, "X-Api-Key": API_KEY},
                    timeout=20,
                )
            )
            clients[role] = client
            wait_ready(client)
        yield clients, containers["bki"]


def test_stopped_bki_is_cleaned_by_background_worker_after_restart(
    live_roles: tuple[dict[str, httpx.Client], DockerContainer],
) -> None:
    clients, bki = live_roles
    created = clients["scenarios"].post(
        "/api/v1/scenarios",
        json={"code": "container-stop", "title": "Остановка БКИ", "preset": "IP_HEALTHY"},
    )
    assert created.status_code == 201, created.text
    inn = created.json()["inn"]
    assert clients["registry"].get(f"/api/v1/companies/{inn}").status_code == 200
    bki.get_wrapped_container().stop(timeout=1)
    try:
        failed = clients["scenarios"].post("/api/v1/scenarios/container-stop/apply")
        assert failed.status_code == 502, failed.text
        assert failed.json()["code"] == "APPLY_FAILED"
        for role in ("registry", "tax", "bank_core"):
            assert (
                clients[role]
                .get("/admin/subjects", params={"scenario": "container-stop"})
                .json()["total"]
                == 0
            )
    finally:
        bki.get_wrapped_container().start()
    # Docker при повторном старте может назначить другой опубликованный порт.
    # Внутренний DNS сценариев остаётся bki:8000, внешний тестовый клиент обновляем.
    bki.get_wrapped_container().reload()
    clients["bki"].base_url = f"http://{bki.get_container_host_ip()}:{bki.get_exposed_port(8000)}"
    wait_ready(clients["bki"])
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        remaining = (
            clients["bki"].get("/admin/subjects", params={"scenario": "container-stop"}).json()
        )
        if remaining["total"] == 0:
            break
        time.sleep(0.1)
    assert remaining["total"] == 0
    reapplied = clients["scenarios"].post("/api/v1/scenarios/container-stop/apply")
    assert reapplied.status_code == 200, reapplied.text
    assert reapplied.json()["status"] == "APPLIED"
