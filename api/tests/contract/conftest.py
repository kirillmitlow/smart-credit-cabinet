"""Контрактные тесты адаптеров против живых моков (T-232..T-235, 70-04).

Стенд поднимается один раз на сессию командой `docker compose up -d --wait` из корня репозитория
(Postgres, db-init, четыре мока и сервис сценариев). Если моки уже запущены (кем-то другим или
в прошлый раз), используем их и не гасим. `make check` эти тесты не запускает (маркер `contract`).

Персоны. Встроенный сценарий берём как есть, если он уже есть в сервисе сценариев. Сейчас в моках
есть только `sokolova`; для остальных (romashka, vektor, orlov…) в тесте создаётся временный
сценарий `ct-<имя>` через `POST /scenarios` с параметрами из спецификации моков 10.2 и 10.5. Когда
в моках появятся встроенные `romashka` и др., тесты сами начнут брать их (проверки точных чисел
включаются только для встроенных).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.modules.integrations import (
    CallRecord,
    IntegrationClient,
    Integrations,
    build_integrations,
)
from app.shared.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES = [
    "postgres",
    "db-init",
    "mock-registry",
    "mock-tax",
    "mock-credit-bureau",
    "mock-bank-core",
    "mock-scenarios",
]
HOST = "http://127.0.0.1"
PORTS = {"registry": 8101, "tax": 8102, "bki": 8103, "bank_core": 8104, "scenarios": 8105}
ADMIN = {"X-Admin-Key": "dev-admin-key"}

# Параметры временных сценариев (спецификация моков 10.2/10.5), имена как у персон
CUSTOM_SPECS: dict[str, dict[str, Any]] = {
    "romashka": {
        "preset": "LLC_HEALTHY",
        "company": {"form": "LLC", "name": "Ромашка", "ageMonths": 84, "okved": "46.73"},
        "finance": {
            "avgMonthlyRevenueRub": 7_900_000,
            "taxRegime": "USN_INCOME_MINUS_EXPENSES",
            "hasStatements": True,
        },
        "tax": {"taxDebtRub": 1_150_000},
        "bki": {
            "company": {
                "historyYears": 7,
                "activeLoans": [
                    {"kind": "LOAN", "amountRub": 3_000_000, "termMonths": 36, "ratePercent": 21}
                ],
                "currentOverdueDays": 94,
                "inquiries30d": 6,
                "rejectedApplications90d": 2,
            }
        },
    },
    "vektor": {
        "preset": "LLC_HEALTHY",
        "company": {
            "form": "LLC",
            "name": "Вектор",
            "status": "LIQUIDATING",
            "unreliableAddress": True,
            "ageMonths": 48,
        },
    },
    "orlov": {"preset": "SELF_EMPLOYED"},
    "garipov": {
        "preset": "IP_HEALTHY",
        "company": {"form": "IP", "ageMonths": 60, "okved": "96.02"},
        "finance": {"avgMonthlyRevenueRub": 700_000, "taxRegime": "PSN", "hasStatements": False},
        "bank": {"isCustomer": False, "customerSinceMonths": None, "balanceRub": None},
    },
    "snabkontrakt": {
        "preset": "LLC_HEALTHY",
        "company": {"form": "LLC", "name": "СнабКонтракт", "ageMonths": 72, "okved": "46.46"},
        "finance": {
            "avgMonthlyRevenueRub": 15_000_000,
            "taxRegime": "OSNO",
            "vatRatePercent": 22,
            "hasStatements": True,
            "noisePercent": 0,
        },
        "bank": {"isCustomer": True, "customerSinceMonths": 24, "balanceRub": 1_100_000},
        "contracts": [
            {
                "customer": {"name": "ГБУЗ Городская больница 5"},
                "subject": "Поставка медицинских изделий",
                "priceRub": 12_000_000,
                "concluded": "-1M",
                "executionIn": "+2M",
                "paymentIn": "+3M",
                "status": "IN_PROGRESS",
                "paidRub": 0,
            }
        ],
    },
    "quick-start": {
        "preset": "STARTUP",
        "company": {"form": "LLC", "ageMonths": 3, "okved": "62.01"},
        "bank": {"isCustomer": True, "customerSinceMonths": 3, "balanceRub": 300_000},
        "bki": {
            "company": {"historyYears": 0},
            "owner": {
                "historyYears": 3,
                "closedLoans": [
                    {
                        "kind": "CONSUMER_LOAN",
                        "amountRub": 300_000,
                        "openedAt": "-3y",
                        "closedAt": "-1y",
                    }
                ],
                "activeLoans": [{"kind": "CREDIT_CARD", "limitRub": 100_000, "balanceRub": 0}],
            },
        },
    },
    "t-aml": {
        "preset": "LLC_HEALTHY",
        "compliance": {"amlListed": "DIRECTOR"},
        "bank": {"isCustomer": True, "customerSinceMonths": 24, "balanceRub": 300_000},
    },
    "t-overdue-45": {
        "preset": "LLC_HEALTHY",
        "bki": {
            "company": {
                "historyYears": 3,
                "currentOverdueDays": 45,
                "activeLoans": [
                    {
                        "kind": "LOAN",
                        "amountRub": 1_500_000,
                        "termMonths": 24,
                        "ratePercent": 21,
                        "openedAt": "-12M",
                    }
                ],
            }
        },
    },
    "t-bankrupt": {
        "preset": "LLC_HEALTHY",
        "people": {
            "director": {"ref": "director"},
            "founders": [
                {"ref": "director", "sharePercent": 60},
                {"ref": "second", "sharePercent": 40},
            ],
        },
        "bankruptcies": [
            {
                "subject": "founder:second",
                "stage": "COMPLETED",
                "startedYearsAgo": 4,
                "completedYearsAgo": 2,
            }
        ],
    },
    # Кредит нашего банка виден и в АБС, и в БКИ под одним УИд (7.5)
    "our-loan": {
        "preset": "LLC_HEALTHY",
        "bank": {"isCustomer": True, "customerSinceMonths": 24, "balanceRub": 500_000},
        "bki": {
            "company": {
                "historyYears": 3,
                "activeLoans": [
                    {
                        "kind": "LOAN",
                        "amountRub": 1_000_000,
                        "termMonths": 12,
                        "ratePercent": 24,
                        "ourBank": True,
                    }
                ],
            }
        },
    },
}


@dataclass(frozen=True)
class Persona:
    name: str
    code: str
    inn: str
    builtin: bool
    detail: dict[str, Any] = field(repr=False)

    @property
    def identity(self) -> dict[str, Any]:
        identity: dict[str, Any] = self.detail["expanded"]["identity"]
        return identity

    def person(self, role: str) -> dict[str, Any]:
        """`director`, `owner` или `founder:<ref>` из развёрнутого сценария."""
        found = self.identity["subjectRefs"].get(role)
        for person in self.identity["persons"]:
            if person["inn"] == found:
                person_data: dict[str, Any] = person
                return person_data
        raise KeyError(role)


class ListJournal:
    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def record(self, record: CallRecord) -> None:
        self.records.append(record)


def _ready() -> bool:
    try:
        return httpx.get(f"{HOST}:{PORTS['scenarios']}/health/ready", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def mocks_stack() -> Iterator[None]:
    started_here = False
    if not _ready():
        subprocess.run(  # noqa: S603 — фиксированная команда стенда, не пользовательский ввод
            ["docker", "compose", "up", "-d", "--wait", *SERVICES],  # noqa: S607
            cwd=REPO_ROOT,
            check=True,
            timeout=900,
        )
        started_here = True
        deadline = time.monotonic() + 60
        while not _ready() and time.monotonic() < deadline:
            time.sleep(1)
    yield
    if started_here:
        subprocess.run(  # noqa: S603
            ["docker", "compose", "down"],  # noqa: S607
            cwd=REPO_ROOT,
            check=False,
            timeout=300,
        )


@pytest.fixture(scope="session")
def scenarios_http(mocks_stack: None) -> Iterator[httpx.Client]:
    with httpx.Client(
        base_url=f"{HOST}:{PORTS['scenarios']}/api/v1", headers=ADMIN, timeout=60
    ) as http:
        yield http


@pytest.fixture(scope="session")
def persona(scenarios_http: httpx.Client) -> Iterator[Callable[[str], Persona]]:
    """`persona("romashka")`: встроенный сценарий или временный `ct-romashka`; временные удаляются в конце."""
    builtin = {
        row["code"] for row in scenarios_http.get("/scenarios", params={"origin": "BUILTIN"}).json()
    }
    created: list[str] = []
    cache: dict[str, Persona] = {}

    def get(name: str) -> Persona:
        if name in cache:
            return cache[name]
        if name in builtin:
            code, is_builtin = name, True
            scenarios_http.post(f"/scenarios/{code}/apply").raise_for_status()
        else:
            if name not in CUSTOM_SPECS:
                pytest.skip(
                    f"Персона {name}: нет ни встроенного сценария, ни параметров генератора"
                )
            code, is_builtin = f"ct-{name}", False
            if scenarios_http.get(f"/scenarios/{code}").status_code == 200:
                scenarios_http.post(f"/scenarios/{code}/apply").raise_for_status()
            else:
                response = scenarios_http.post(
                    "/scenarios",
                    json={"code": code, "title": f"contract test {name}", **CUSTOM_SPECS[name]},
                )
                if response.status_code != 201:
                    pytest.skip(
                        f"Генератор не создал {name}: {response.status_code} {response.text[:200]}"
                    )
            created.append(code)
        detail = scenarios_http.get(f"/scenarios/{code}").json()
        cache[name] = Persona(name, code, detail["inn"], is_builtin, detail)
        return cache[name]

    yield get
    for code in created:
        scenarios_http.delete(f"/scenarios/{code}")


def make_settings() -> Settings:
    return Settings(
        registry_url=f"{HOST}:{PORTS['registry']}",
        tax_url=f"{HOST}:{PORTS['tax']}",
        bki_url=f"{HOST}:{PORTS['bki']}",
        bank_core_url=f"{HOST}:{PORTS['bank_core']}",
    )


@pytest.fixture
def journal() -> ListJournal:
    return ListJournal()


@pytest.fixture
def live(mocks_stack: None, journal: ListJournal) -> Iterator[Integrations]:
    client = IntegrationClient(make_settings(), journal=journal)
    yield build_integrations(client)
    client.close()


class OneShotScenario(httpx.BaseTransport):
    """Добавляет `X-Mock-Scenario` только к первому запросу: сбой один, повтор идёт без него (8.2)."""

    def __init__(self, scenario: str) -> None:
        self._inner = httpx.HTTPTransport()
        self._scenario = scenario
        self._used = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not self._used:
            self._used = True
            request.headers["X-Mock-Scenario"] = self._scenario
        return self._inner.handle_request(request)


@pytest.fixture
def live_with_first_failure(
    mocks_stack: None, journal: ListJournal
) -> Iterator[Callable[[str], Integrations]]:
    clients: list[IntegrationClient] = []

    def build(scenario: str) -> Integrations:
        client = IntegrationClient(
            make_settings(), journal=journal, transport=OneShotScenario(scenario)
        )
        clients.append(client)
        return build_integrations(client)

    yield build
    for client in clients:
        client.close()
