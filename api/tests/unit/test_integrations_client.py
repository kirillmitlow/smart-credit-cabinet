"""T-230: слой устойчивости. Таблица повторов из 50-08, ошибки схемы, бюджет времени, журнал вызовов."""

# ruff: noqa: PT018 — короткие составные assert читаются лучше, чем разбитые
from __future__ import annotations

import threading
from typing import Any

import httpx
import pytest
import respx
import structlog
from structlog.testing import capture_logs

from app.modules.integrations import (
    IntegrationClient,
    Ok,
    Reason,
    SourceUnavailable,
)
from app.modules.integrations import policy as rules
from app.modules.integrations.breaker import BreakerState, Permit
from app.modules.integrations.journal import DbCallJournal
from app.modules.integrations.results import System
from tests.unit.conftest import FakeTime, ListJournal
from tests.unit.integration_samples import problem

pytestmark = pytest.mark.unit

REGISTRY_URL = "http://mock-registry:8000"
BKI_URL = "http://mock-credit-bureau:8000"
PATH = "/api/v1/x/0017654322"
OK_BODY = {"v": 7, "meta": {"source": "TEST", "requestId": "req_X", "dataActualAt": "2026-10-20"}}


def parse(payload: Any) -> int:
    return int(payload["v"])


def good() -> httpx.Response:
    return httpx.Response(200, json=OK_BODY)


@pytest.fixture
def router() -> Any:
    with respx.mock(assert_all_called=False) as router:
        yield router


def call_get(client: IntegrationClient, **kw: Any) -> Any:
    return client.call(policy=rules.REGISTRY, method="GET", path=PATH, parse=parse, **kw)


def call_post_with_key(client: IntegrationClient, **kw: Any) -> Any:
    return client.call(
        policy=rules.REGISTRY,
        method="POST",
        path=PATH,
        parse=parse,
        idempotency_key="k-1",
        json_body={"a": 1},
        **kw,
    )


def in_progress() -> httpx.Response:
    return httpx.Response(
        409, json=problem("IDEMPOTENCY_IN_PROGRESS", 409), headers={"Retry-After": "1"}
    )


# --- таблица повторов (50-08): число попыток и итог --------------------------------------------

# (описание, ответы по очереди, ожидаемое число запросов, итог: "ok" или причина недоступности)
GET_ROWS: list[tuple[str, list[Any], int, Any]] = [
    ("обрыв, потом успех", [httpx.ConnectError("x"), good()], 2, "ok"),
    ("обрыв три раза", [httpx.ConnectError("x")] * 3, 3, Reason.CONNECTION_ERROR),
    ("таймаут, потом успех", [httpx.ReadTimeout("x"), good()], 2, "ok"),
    ("таймаут три раза", [httpx.ReadTimeout("x")] * 3, 3, Reason.TIMEOUT),
    ("502, потом успех", [httpx.Response(502), good()], 2, "ok"),
    ("503, потом успех", [httpx.Response(503), good()], 2, "ok"),
    ("504, потом успех", [httpx.Response(504), good()], 2, "ok"),
    ("503 три раза", [httpx.Response(503)] * 3, 3, Reason.HTTP_5XX),
    ("500 не повторяем", [httpx.Response(500)], 1, Reason.HTTP_5XX),
    ("429 с Retry-After 2 с", [httpx.Response(429, headers={"Retry-After": "2"}), good()], 2, "ok"),
    ("429 без Retry-After", [httpx.Response(429), good()], 2, "ok"),
    (
        "429 с Retry-After 9 с не ждём",
        [httpx.Response(429, headers={"Retry-After": "9"})],
        1,
        Reason.RATE_LIMITED,
    ),
    (
        "409 KEY_REUSED не повторяем",
        [httpx.Response(409, json=problem("IDEMPOTENCY_KEY_REUSED", 409))],
        1,
        Reason.REJECTED,
    ),
    (
        "404 не повторяем",
        [httpx.Response(404, json=problem("ENTITY_NOT_FOUND", 404))],
        1,
        Reason.REJECTED,
    ),
    (
        "422 не повторяем",
        [httpx.Response(422, json=problem("VALIDATION_ERROR", 422))],
        1,
        Reason.REJECTED,
    ),
    (
        "400 не повторяем",
        [httpx.Response(400, json=problem("INN_INVALID", 400))],
        1,
        Reason.REJECTED,
    ),
    (
        "401 не повторяем",
        [httpx.Response(401, json=problem("UNAUTHORIZED", 401))],
        1,
        Reason.REJECTED,
    ),
]


@pytest.mark.parametrize(
    ("responses", "calls", "outcome"), [r[1:] for r in GET_ROWS], ids=[r[0] for r in GET_ROWS]
)
def test_get_retry_table(
    client: IntegrationClient,
    router: Any,
    journal: ListJournal,
    responses: list[Any],
    calls: int,
    outcome: Any,
) -> None:
    route = router.get(f"{REGISTRY_URL}{PATH}")
    route.side_effect = responses
    result = call_get(client)
    assert route.call_count == calls
    assert len(journal.records) == calls  # каждая попытка — строка журнала
    if outcome == "ok":
        assert isinstance(result, Ok)
        assert result.data == 7
    else:
        assert isinstance(result, SourceUnavailable)
        assert result.reason is outcome
        assert result.attempts == calls


def test_409_in_progress_waits_and_does_not_spend_attempt(
    client: IntegrationClient, router: Any, fake_time: FakeTime
) -> None:
    # Попыток на вызов 3, а «в работе» отвечает пять раз подряд: попытки не потрачены
    route = router.post(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [in_progress()] * 5 + [good()]
    result = call_post_with_key(client)
    assert isinstance(result, Ok)
    assert route.call_count == 6
    assert fake_time.sleeps == [1.0] * 5


def test_409_in_progress_gives_up_after_limit(client: IntegrationClient, router: Any) -> None:
    route = router.post(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [in_progress()] * 20
    result = call_post_with_key(client)
    assert isinstance(result, SourceUnavailable)
    assert result.error_code == "IDEMPOTENCY_IN_PROGRESS"
    assert result.retryable_later is True
    assert route.call_count == rules.MAX_IN_PROGRESS_WAITS + 1


def test_409_in_progress_without_key_is_not_retried(client: IntegrationClient, router: Any) -> None:
    route = router.post(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [in_progress(), good()]
    result = client.call(policy=rules.REGISTRY, method="POST", path=PATH, parse=parse)
    assert isinstance(result, SourceUnavailable)
    assert route.call_count == 1


def test_key_reused_is_logged_as_error(client: IntegrationClient, router: Any) -> None:
    router.post(f"{REGISTRY_URL}{PATH}").side_effect = [
        httpx.Response(409, json=problem("IDEMPOTENCY_KEY_REUSED", 409))
    ]
    with capture_logs() as logs:
        result = call_post_with_key(client)
    assert isinstance(result, SourceUnavailable)
    assert result.error_code == "IDEMPOTENCY_KEY_REUSED"
    assert [e["event"] for e in logs if e["log_level"] == "error"] == [
        "integration_idempotency_key_reused"
    ]


def test_post_without_key_is_never_retried(client: IntegrationClient, router: Any) -> None:
    route = router.post(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [httpx.Response(503), good()]
    result = client.call(policy=rules.REGISTRY, method="POST", path=PATH, parse=parse)
    assert isinstance(result, SourceUnavailable)
    assert route.call_count == 1


def test_post_with_key_is_retried(client: IntegrationClient, router: Any) -> None:
    route = router.post(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [httpx.Response(503), good()]
    assert isinstance(call_post_with_key(client), Ok)
    assert route.call_count == 2
    assert route.calls[0].request.headers["Idempotency-Key"] == "k-1"
    assert route.calls[1].request.headers["Idempotency-Key"] == "k-1"


def test_read_only_post_is_retried(client: IntegrationClient, router: Any) -> None:
    route = router.post(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [httpx.ConnectError("x"), good()]
    result = client.call(
        policy=rules.REGISTRY, method="POST", path=PATH, parse=parse, read_only_post=True
    )
    assert isinstance(result, Ok)
    assert route.call_count == 2


def test_allowed_404_is_ok_none(
    client: IntegrationClient, router: Any, journal: ListJournal
) -> None:
    router.get(f"{REGISTRY_URL}{PATH}").side_effect = [
        httpx.Response(
            404, json=problem("ENTITY_NOT_FOUND", 404), headers={"X-Request-Id": "req_N"}
        )
    ]
    result = call_get(client, allow_404=True)
    assert isinstance(result, Ok)
    assert result.data is None
    assert result.snapshot_meta.request_id == "req_N"
    assert journal.records[0].status_code == 404
    assert journal.records[0].error_code is None  # для адаптера это нормальный ответ


# --- отчёт БКИ: один повтор, только после 503 или обрыва ---------------------------------------

BKI_ROWS: list[tuple[str, list[Any], int, Any]] = [
    ("503, потом успех", [httpx.Response(503), good()], 2, "ok"),
    ("обрыв (LOST_RESPONSE), потом успех", [httpx.RemoteProtocolError("x"), good()], 2, "ok"),
    ("503 дважды — больше одного повтора нет", [httpx.Response(503)] * 3, 2, Reason.HTTP_5XX),
    ("502 не повторяем", [httpx.Response(502), good()], 1, Reason.HTTP_5XX),
    ("таймаут не повторяем", [httpx.ReadTimeout("x"), good()], 1, Reason.TIMEOUT),
    (
        "403 нет согласия не повторяем",
        [httpx.Response(403, json=problem("CONSENT_EXPIRED", 403)), good()],
        1,
        Reason.REJECTED,
    ),
]


@pytest.mark.parametrize(
    ("responses", "calls", "outcome"), [r[1:] for r in BKI_ROWS], ids=[r[0] for r in BKI_ROWS]
)
def test_bureau_report_retry_rules(
    client: IntegrationClient, router: Any, responses: list[Any], calls: int, outcome: Any
) -> None:
    route = router.post(f"{BKI_URL}/api/v1/credit-reports")
    route.side_effect = responses
    result = post_report(client)
    assert route.call_count == calls
    if outcome == "ok":
        assert isinstance(result, Ok)
    else:
        assert isinstance(result, SourceUnavailable)
        assert result.reason is outcome
    for sent in route.calls:  # повтор идёт с тем же ключом, иначе второй платный запрос
        assert sent.request.headers["Idempotency-Key"] == "bki-report:APP-1:0015557771"


def post_report(client: IntegrationClient) -> Any:
    return client.call(
        policy=rules.BUREAU_REPORT,
        method="POST",
        path="/api/v1/credit-reports",
        parse=parse,
        json_body={"secret": "body"},
        idempotency_key="bki-report:APP-1:0015557771",
        subject_inn="0015557771",
    )


# --- схема, метаданные, заголовки --------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"unexpected": 1}),
        httpx.Response(200, json={"v": "not-a-number"}),
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.Response(200, json=[1, 2, 3]),
    ],
    ids=["нет поля", "не тот тип", "не JSON", "не объект"],
)
def test_schema_drift_is_source_unavailable(
    client: IntegrationClient, router: Any, journal: ListJournal, response: httpx.Response
) -> None:
    route = router.get(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [response, good()]
    result = call_get(client)
    assert isinstance(result, SourceUnavailable)
    assert result.reason is Reason.SCHEMA_ERROR
    assert route.call_count == 1  # повтор не лечит
    assert journal.records[0].error_code == "SCHEMA_ERROR"


def test_snapshot_meta_comes_from_response(client: IntegrationClient, router: Any) -> None:
    router.get(f"{REGISTRY_URL}{PATH}").side_effect = [
        httpx.Response(
            200,
            json={
                "v": 1,
                "meta": {
                    "source": "EGRUL",
                    "simulated": True,
                    "requestId": "req_A",
                    "retrievedAt": "2026-10-21T09:12:03Z",
                    "dataActualAt": "2026-10-19",
                },
            },
            headers={"Idempotent-Replayed": "true"},
        )
    ]
    result = call_get(client)
    assert isinstance(result, Ok)
    meta = result.snapshot_meta
    assert (meta.system, meta.source, meta.request_id) == (System.REGISTRY, "EGRUL", "req_A")
    assert meta.data_actual_at is not None and meta.data_actual_at.isoformat() == "2026-10-19"
    assert meta.replayed is True
    assert result.raw["v"] == 1


def test_request_carries_key_request_id_and_idempotency_header(
    client: IntegrationClient, router: Any, journal: ListJournal
) -> None:
    route = router.get(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [httpx.ConnectError("x"), good()]
    with structlog.contextvars.bound_contextvars(requestId="req_TRACE"):
        call_get(client)
    first, second = (c.request for c in route.calls)
    assert first.headers["X-Api-Key"] == "dev-registry-key"
    assert first.headers["X-Request-Id"] == second.headers["X-Request-Id"] == "req_TRACE"
    assert {r.request_id for r in journal.records} == {"req_TRACE"}
    assert "Idempotency-Key" not in first.headers


def test_timeout_is_multiplied_by_scale(make_client: Any, router: Any) -> None:
    client = make_client(scale=2.5)
    route = router.get(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [good()]
    call_get(client)
    assert route.calls[0].request.extensions["timeout"]["read"] == pytest.approx(5.0)


# --- бюджет времени ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy",
    [rules.REGISTRY, rules.TAX, rules.BANK_CORE_READ, rules.BUREAU_REPORT, rules.BUREAU_SUBMIT],
    ids=lambda p: f"{p.system.value}-{p.timeout_s}s",
)
@pytest.mark.parametrize("scale", [1.0, 3.0])
def test_all_attempts_fit_into_budget(
    make_client: Any, router: Any, fake_time: FakeTime, policy: rules.CallPolicy, scale: float
) -> None:
    """Каждая попытка висит до своего таймаута, паузы максимальные: сумма не выходит за бюджет."""
    client = make_client(scale=scale)

    def hang(request: httpx.Request) -> httpx.Response:
        fake_time.advance(request.extensions["timeout"]["read"])
        raise httpx.ReadTimeout("hang", request=request)

    router.get(url__regex=r".*").mock(side_effect=hang)
    router.post(url__regex=r".*").mock(side_effect=hang)
    started = fake_time.now
    result = client.call(
        policy=policy,
        method="POST" if policy.system is System.CREDIT_BUREAU else "GET",
        path="/api/v1/x",
        parse=parse,
        idempotency_key="k",
    )
    assert isinstance(result, SourceUnavailable)
    assert fake_time.now - started <= policy.budget_s * scale + 1e-9


def test_budget_cuts_retries_when_attempts_are_slow(
    make_client: Any, router: Any, fake_time: FakeTime
) -> None:
    """Если Retry-After съедает бюджет, лишних попыток нет, а время не выходит за бюджет."""
    client = make_client()

    def slow_429(request: httpx.Request) -> httpx.Response:
        fake_time.advance(min(1.9, request.extensions["timeout"]["read"]))
        return httpx.Response(429, headers={"Retry-After": "5"})

    route = router.get(f"{REGISTRY_URL}{PATH}")
    route.side_effect = slow_429
    started = fake_time.now
    result = call_get(client)
    assert isinstance(result, SourceUnavailable)
    assert fake_time.now - started <= rules.REGISTRY.budget_s
    assert route.call_count == 2  # третья попытка и её пауза в бюджет не влезают


# --- журнал ------------------------------------------------------------------------------------


def test_journal_masks_inn_and_has_no_bodies(
    client: IntegrationClient, router: Any, journal: ListJournal
) -> None:
    router.post(f"{BKI_URL}/api/v1/credit-reports").side_effect = [good()]
    post_report(client)
    record = journal.records[0]
    assert record.path == "/api/v1/credit-reports"
    assert record.subject_inn_masked == "0015****71"
    assert not hasattr(record, "body")
    dumped = repr(record)
    assert "0015557771" not in dumped
    assert "secret" not in dumped


def test_journal_masks_inn_in_path(
    client: IntegrationClient, router: Any, journal: ListJournal
) -> None:
    router.get(f"{REGISTRY_URL}{PATH}").side_effect = [good()]
    call_get(client, subject_inn="0017654322")
    record = journal.records[0]
    assert record.path == "/api/v1/x/0017****22"
    assert record.subject_inn_masked == "0017****22"
    assert record.system == "registry" and record.method == "GET"
    assert record.status_code == 200 and record.attempt == 1
    assert record.circuit_state == "CLOSED"


def test_logs_do_not_contain_inn_or_body(client: IntegrationClient, router: Any) -> None:
    router.post(f"{BKI_URL}/api/v1/credit-reports").side_effect = [good()]
    with capture_logs() as logs:
        post_report(client)
    assert logs
    flat = repr(logs)
    assert "0015557771" not in flat and "secret" not in flat


def test_replay_header_is_journaled(
    client: IntegrationClient, router: Any, journal: ListJournal
) -> None:
    router.post(f"{BKI_URL}/api/v1/credit-reports").side_effect = [
        httpx.Response(200, json=OK_BODY, headers={"Idempotent-Replayed": "true"})
    ]
    post_report(client)
    assert journal.records[0].idempotent_replayed is True


def test_journal_failure_does_not_break_the_call(make_client: Any, router: Any) -> None:
    class Broken:
        def record(self, record: Any) -> None:
            raise RuntimeError("база недоступна")

    client = make_client(journal_override=Broken())
    router.get(f"{REGISTRY_URL}{PATH}").side_effect = [good()]
    with capture_logs() as logs:
        result = call_get(client)
    assert isinstance(result, Ok)
    assert any(e["event"] == "integration_call_log_failed" for e in logs)


def test_db_journal_without_database_does_not_raise() -> None:
    from app.modules.integrations import CallRecord

    DbCallJournal().record(
        CallRecord("registry", "GET", "/x", None, 200, None, 5, 1, "CLOSED", "req_1", None)
    )  # база не настроена: исключение глотается, остаётся предупреждение в логе


# --- предохранитель ----------------------------------------------------------------------------


class ClosedThenOpen:
    """Предохранитель-заглушка: система «в аварии», пускать нельзя."""

    def __init__(self) -> None:
        self.failures = 0
        self.successes = 0

    def acquire(self, system: System) -> Permit:
        return Permit(False, BreakerState.OPEN)

    def success(self, system: System, permit: Permit) -> None:
        self.successes += 1

    def failure(self, system: System, permit: Permit) -> None:
        self.failures += 1


def test_open_breaker_means_no_network(make_client: Any, router: Any, journal: ListJournal) -> None:
    client = make_client(breaker=ClosedThenOpen())
    route = router.get(f"{REGISTRY_URL}{PATH}")
    route.side_effect = [good()]
    result = call_get(client)
    assert isinstance(result, SourceUnavailable)
    assert result.reason is Reason.CIRCUIT_OPEN
    assert route.call_count == 0
    assert journal.records[0].error_code == "CIRCUIT_OPEN"
    assert journal.records[0].circuit_state == "OPEN"


class CountingBreaker:
    def __init__(self) -> None:
        self.events: list[str] = []

    def acquire(self, system: System) -> Permit:
        return Permit(True, BreakerState.CLOSED)

    def success(self, system: System, permit: Permit) -> None:
        self.events.append("ok")

    def failure(self, system: System, permit: Permit) -> None:
        self.events.append("fail")


def test_breaker_counts_only_source_failures(make_client: Any, router: Any) -> None:
    breaker = CountingBreaker()
    client = make_client(breaker=breaker)
    router.get(f"{REGISTRY_URL}{PATH}").side_effect = [
        httpx.ReadTimeout("x"),  # ошибка
        httpx.Response(503),  # ошибка
        httpx.Response(200, json={"bad": 1}),  # ошибка схемы
        httpx.Response(404, json=problem("ENTITY_NOT_FOUND", 404)),  # не ошибка
        httpx.Response(400, json=problem("INN_INVALID", 400)),  # не ошибка
        good(),
    ]
    for _ in range(4):
        call_get(client)
    assert breaker.events == ["fail", "fail", "fail", "ok", "ok", "ok"]


# --- потоки ------------------------------------------------------------------------------------


def test_concurrent_calls_are_isolated(make_client: Any, router: Any, journal: ListJournal) -> None:
    client = make_client()
    router.get(url__regex=rf"{REGISTRY_URL}/api/v1/x/.*").mock(return_value=good())
    results: list[Any] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        for n in range(10):
            res = client.call(
                policy=rules.REGISTRY,
                method="GET",
                path=f"/api/v1/x/{i}-{n}",
                parse=parse,
                subject_inn=None,
            )
            with lock:
                results.append(res)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 80 and all(isinstance(r, Ok) for r in results)
    assert len(journal.records) == 80
    assert len({r.request_id for r in journal.records}) == 80  # у каждого вызова свой X-Request-Id
