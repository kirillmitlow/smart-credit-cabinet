"""Общие фикстуры unit-тестов адаптеров: подставные часы, журнал в памяти, клиент без реальных пауз."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
import structlog

from app.modules.integrations import CallJournal, CallRecord, IntegrationClient
from app.modules.integrations.breaker import CircuitBreaker
from app.shared.settings import Settings


class FakeTime:
    """Время, которое двигают пауза и «зависший» ответ; реальных ожиданий в тестах нет."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ListJournal:
    def __init__(self) -> None:
        self.records: list[CallRecord] = []
        self._lock = threading.Lock()

    def record(self, record: CallRecord) -> None:
        with self._lock:
            self.records.append(record)


@pytest.fixture(autouse=True)
def _fresh_structlog() -> None:
    """Другие тесты настраивают structlog на свой перехваченный stdout; к нашему тесту он уже закрыт."""
    structlog.reset_defaults()


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def journal() -> ListJournal:
    return ListJournal()


@pytest.fixture
def make_client(fake_time: FakeTime, journal: ListJournal) -> Callable[..., IntegrationClient]:
    """Клиент с подставными часами; паузы берём максимальные (jitter = верхняя граница)."""

    def build(
        *,
        scale: float = 1.0,
        breaker: CircuitBreaker | None = None,
        journal_override: CallJournal | None = None,
    ) -> IntegrationClient:
        return IntegrationClient(
            Settings(integration_timeout_scale=scale),
            journal=journal_override or journal,
            breaker=breaker,
            sleep=fake_time.sleep,
            monotonic=fake_time.monotonic,
            uniform=lambda _low, high: high,
        )

    return build


@pytest.fixture
def client(make_client: Callable[..., IntegrationClient]) -> IntegrationClient:
    return make_client()
