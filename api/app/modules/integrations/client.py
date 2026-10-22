"""Слой устойчивости: один на все адаптеры (50-08, T-230).

Синхронный `httpx.Client` на систему, таймауты по политике (с множителем `INTEGRATION_TIMEOUT_SCALE`),
повторы через tenacity, сквозной `X-Request-Id`, журнал `integration_calls` на каждую попытку.
Недоступность источника — результат (`SourceUnavailable`), а не исключение.

Повторяем только `GET` и `POST` с `Idempotency-Key` (плюс `POST`, которые только читают и помечены
`read_only_post`). Потокобезопасен: состояние вызова живёт в локальном контексте, `httpx.Client`
и предохранитель общие и рассчитаны на параллельные потоки (пул из нескольких потоков в конвейере).
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, overload
from uuid import UUID

import httpx
import structlog
from tenacity import Retrying, retry_if_exception_type

from app.modules.integrations import policy as rules
from app.modules.integrations.breaker import BreakerState, CircuitBreaker, NullBreaker, Permit
from app.modules.integrations.journal import CallJournal, CallRecord, DbCallJournal
from app.modules.integrations.policy import CallPolicy
from app.modules.integrations.results import (
    Ok,
    Reason,
    Result,
    SnapshotMeta,
    SourceUnavailable,
    System,
)
from app.shared import clock
from app.shared.ids import new_request_id
from app.shared.logs import mask_inn, mask_text
from app.shared.settings import Settings, get_settings

log = structlog.get_logger("app.integrations")

# Меньше этого на попытку не остаётся смысла: считаем бюджет исчерпанным
MIN_ATTEMPT_S = 0.05
IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"


class _Retry(Exception):  # noqa: N818 — служебный сигнал для tenacity, наружу не выходит
    """Попытка не удалась по причине, после которой можно повторить."""

    def __init__(self, final: SourceUnavailable, wait: float | None, consume: bool) -> None:
        super().__init__(final.reason)
        self.final = final
        self.wait = wait
        self.consume = consume


@dataclass(slots=True)
class _Call:
    """Состояние одного логического вызова (живёт только внутри `call`, между потоками не делится)."""

    policy: CallPolicy
    method: str
    path: str
    resource: str
    parse: Callable[[Any], Any]
    params: Mapping[str, Any] | None
    json_body: Any
    idempotency_key: str | None
    subject_inn_masked: str | None
    application_id: UUID | None
    allow_404: bool
    can_retry: bool
    request_id: str
    deadline: float
    attempt: int = 0
    consumed: int = 0
    in_progress_waits: int = 0


class IntegrationClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        journal: CallJournal | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = clock.monotonic,
        uniform: Callable[[float, float], float] = random.uniform,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = settings or get_settings()
        self._scale = settings.integration_timeout_scale
        self._targets: dict[System, tuple[str, str]] = {
            System.REGISTRY: (settings.registry_url, settings.registry_api_key),
            System.TAX: (settings.tax_url, settings.tax_api_key),
            System.CREDIT_BUREAU: (settings.bki_url, settings.bki_api_key),
            System.BANK_CORE: (settings.bank_core_url, settings.bank_core_api_key),
        }
        self._journal: CallJournal = journal if journal is not None else DbCallJournal()
        self._breaker: CircuitBreaker = breaker if breaker is not None else NullBreaker()
        self._sleep = sleep
        self._monotonic = monotonic
        self._uniform = uniform
        self._transport = transport
        self._http: dict[System, httpx.Client] = {}
        self._lock = threading.Lock()

    # --- публичный вызов ----------------------------------------------------------------------

    @overload
    def call[T](
        self,
        *,
        policy: CallPolicy,
        method: str,
        path: str,
        parse: Callable[[Any], T],
        allow_404: Literal[True],
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        idempotency_key: str | None = None,
        subject_inn: str | None = None,
        application_id: UUID | None = None,
        read_only_post: bool = False,
        resource: str = "",
    ) -> Result[T | None]: ...

    @overload
    def call[T](
        self,
        *,
        policy: CallPolicy,
        method: str,
        path: str,
        parse: Callable[[Any], T],
        allow_404: Literal[False] = False,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        idempotency_key: str | None = None,
        subject_inn: str | None = None,
        application_id: UUID | None = None,
        read_only_post: bool = False,
        resource: str = "",
    ) -> Result[T]: ...

    def call(
        self,
        *,
        policy: CallPolicy,
        method: str,
        path: str,
        parse: Callable[[Any], Any],
        allow_404: bool = False,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        idempotency_key: str | None = None,
        subject_inn: str | None = None,
        application_id: UUID | None = None,
        read_only_post: bool = False,
        resource: str = "",
    ) -> Result[Any]:
        """Один логический вызов: попытки, паузы, журнал. Наружу — `Ok` или `SourceUnavailable`.

        `parse` получает разобранный JSON и возвращает внутреннюю модель; любая её ошибка —
        дрейф формата, то есть `SCHEMA_ERROR`. `allow_404`: ответ `404` — нормальный (`Ok(None)`).
        """
        policy = policy.scaled(self._scale)
        method = method.upper()
        ctx = _Call(
            policy=policy,
            method=method,
            path=path,
            resource=resource or path,
            parse=parse,
            params=params,
            json_body=json_body,
            idempotency_key=idempotency_key,
            subject_inn_masked=mask_inn(subject_inn) if subject_inn else None,
            application_id=application_id,
            allow_404=allow_404,
            can_retry=method == "GET" or idempotency_key is not None or read_only_post,
            request_id=structlog.contextvars.get_contextvars().get("requestId") or new_request_id(),
            deadline=self._monotonic() + policy.budget_s,
        )
        retrying = Retrying(
            retry=retry_if_exception_type(_Retry),
            stop=lambda rs: self._should_stop(ctx, rs),
            wait=lambda rs: self._pause(ctx, rs),
            sleep=self._sleep,
            retry_error_callback=lambda rs: self._give_up(rs),
        )
        result: Result[Any] = retrying(self._attempt, ctx)
        return result

    def close(self) -> None:
        with self._lock:
            for client in self._http.values():
                client.close()
            self._http.clear()

    # --- политика повторов (tenacity) ----------------------------------------------------------

    def _should_stop(self, ctx: _Call, retry_state: Any) -> bool:
        exc = retry_state.outcome.exception()
        if exc.consume and ctx.consumed >= ctx.policy.attempts:
            return True
        if not exc.consume and ctx.in_progress_waits > rules.MAX_IN_PROGRESS_WAITS:
            return True
        left = ctx.deadline - self._monotonic() - (retry_state.upcoming_sleep or 0.0)
        return left < MIN_ATTEMPT_S

    def _pause(self, ctx: _Call, retry_state: Any) -> float:
        exc = retry_state.outcome.exception()
        if exc.wait is not None:
            return float(exc.wait)
        step = max(ctx.consumed, 1)
        ceiling = min(rules.BACKOFF_CAP_S, rules.BACKOFF_BASE_S * 2 ** (step - 1))
        return self._uniform(0.0, ceiling)

    @staticmethod
    def _give_up(retry_state: Any) -> SourceUnavailable:
        exc = retry_state.outcome.exception()
        final: SourceUnavailable = exc.final
        return final

    # --- одна попытка --------------------------------------------------------------------------

    def _client(self, system: System) -> httpx.Client:
        with self._lock:
            client = self._http.get(system)
            if client is None:
                base_url, api_key = self._targets[system]
                client = httpx.Client(
                    base_url=base_url,
                    headers={"X-Api-Key": api_key, "Accept": "application/json"},
                    transport=self._transport,
                    follow_redirects=False,
                )
                self._http[system] = client
            return client

    def _attempt(self, ctx: _Call) -> Result[Any]:
        ctx.attempt += 1
        system = ctx.policy.system
        permit = self._breaker.acquire(system)
        if not permit.allowed:
            self._write(ctx, permit, status=None, error=Reason.CIRCUIT_OPEN.value, started=None)
            return self._unavailable(ctx, Reason.CIRCUIT_OPEN)
        timeout = min(ctx.policy.timeout_s, max(ctx.deadline - self._monotonic(), MIN_ATTEMPT_S))
        headers = {"X-Request-Id": ctx.request_id}
        if ctx.idempotency_key:
            headers["Idempotency-Key"] = ctx.idempotency_key
        started = self._monotonic()
        try:
            response = self._client(system).request(
                ctx.method,
                ctx.path,
                params=ctx.params,
                json=ctx.json_body,
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return self._failed(
                ctx, permit, Reason.TIMEOUT, None, started, retry=ctx.policy.retry_on_timeout
            )
        except httpx.TransportError:
            return self._failed(ctx, permit, Reason.CONNECTION_ERROR, None, started, retry=True)
        return self._answered(ctx, permit, response, started)

    def _answered(
        self, ctx: _Call, permit: Permit, response: httpx.Response, started: float
    ) -> Result[Any]:
        status = response.status_code
        replayed = response.headers.get("idempotent-replayed", "").lower() == "true"
        if 200 <= status < 300:
            return self._succeeded(ctx, permit, response, started, replayed)
        code = _problem_code(response)
        if status == 404 and ctx.allow_404:
            self._breaker.success(ctx.policy.system, permit)
            self._write(ctx, permit, status=status, error=None, started=started)
            meta = SnapshotMeta(
                system=ctx.policy.system,
                source=None,
                request_id=response.headers.get("x-request-id"),
                retrieved_at=clock.system_now(),
            )
            return Ok(None, meta, raw=None)
        if status == 429:
            self._breaker.success(
                ctx.policy.system, permit
            )  # система жива, просто просит подождать
            self._write(
                ctx, permit, status=status, error=Reason.RATE_LIMITED.value, started=started
            )
            wait = _retry_after(response)
            final = self._unavailable(ctx, Reason.RATE_LIMITED, status)
            if ctx.can_retry and (wait is None or wait <= rules.MAX_RETRY_AFTER_S):
                ctx.consumed += 1
                raise _Retry(final, wait, consume=True)
            return final
        if status == 409 and code == IN_PROGRESS and ctx.can_retry:
            self._breaker.success(ctx.policy.system, permit)
            self._write(ctx, permit, status=status, error=code, started=started)
            ctx.in_progress_waits += 1
            wait = min(_retry_after(response) or 1.0, rules.MAX_RETRY_AFTER_S)
            final = self._unavailable(ctx, Reason.REJECTED, status, code)
            raise _Retry(final, wait, consume=False)
        if status >= 500:
            retry = status in ctx.policy.retry_statuses
            return self._failed(
                ctx, permit, Reason.HTTP_5XX, status, started, retry=retry, code=code
            )
        # Прочие 4xx (и 3xx): ошибка нашего запроса, повтор не поможет
        self._breaker.success(ctx.policy.system, permit)
        self._write(ctx, permit, status=status, error=code, started=started)
        if code == KEY_REUSED:
            log.error(
                "integration_idempotency_key_reused",
                system=ctx.policy.system.value,
                path=mask_text(ctx.path),
            )
        return self._unavailable(ctx, Reason.REJECTED, status, code)

    def _succeeded(
        self, ctx: _Call, permit: Permit, response: httpx.Response, started: float, replayed: bool
    ) -> Result[Any]:
        status = response.status_code
        try:
            payload = response.json()
            data = ctx.parse(payload)
        except Exception:  # noqa: BLE001 — любой сбой разбора = дрейф формата, а не падение конвейера
            self._breaker.failure(ctx.policy.system, permit)
            self._write(
                ctx, permit, status=status, error=Reason.SCHEMA_ERROR.value, started=started
            )
            return self._unavailable(ctx, Reason.SCHEMA_ERROR, status)
        self._breaker.success(ctx.policy.system, permit)
        self._write(ctx, permit, status=status, error=None, started=started, replayed=replayed)
        meta = _snapshot_meta(ctx.policy.system, payload, response, replayed)
        return Ok(data, meta, raw=payload)

    def _failed(
        self,
        ctx: _Call,
        permit: Permit,
        reason: Reason,
        status: int | None,
        started: float,
        *,
        retry: bool,
        code: str | None = None,
    ) -> Result[Any]:
        self._breaker.failure(ctx.policy.system, permit)
        self._write(ctx, permit, status=status, error=code or reason.value, started=started)
        final = self._unavailable(ctx, reason, status, code)
        if retry and ctx.can_retry:
            ctx.consumed += 1
            raise _Retry(final, None, consume=True)
        return final

    # --- журнал и мелочи -----------------------------------------------------------------------

    def _unavailable(
        self, ctx: _Call, reason: Reason, status: int | None = None, code: str | None = None
    ) -> SourceUnavailable:
        return SourceUnavailable(
            system=ctx.policy.system,
            reason=reason,
            status_code=status,
            error_code=code,
            attempts=ctx.attempt,
            resource=mask_text(ctx.resource),
        )

    def _write(
        self,
        ctx: _Call,
        permit: Permit,
        *,
        status: int | None,
        error: str | None,
        started: float | None,
        replayed: bool = False,
    ) -> None:
        duration = 0 if started is None else round((self._monotonic() - started) * 1000)
        record = CallRecord(
            system=ctx.policy.system.value,
            method=ctx.method,
            path=mask_text(ctx.path),
            subject_inn_masked=ctx.subject_inn_masked,
            status_code=status,
            error_code=error,
            duration_ms=duration,
            attempt=ctx.attempt,
            circuit_state=permit.state.value,
            request_id=ctx.request_id,
            application_id=ctx.application_id,
            idempotent_replayed=replayed,
        )
        try:
            self._journal.record(record)
        except Exception as exc:  # noqa: BLE001 — сбой журнала не ломает вызов
            log.warning("integration_call_log_failed", error=type(exc).__name__)
        # Тела и заголовки в лог не идут; ИНН маскирует фильтр логов
        emit = log.info if error is None else log.warning
        emit(
            "integration_call",
            system=record.system,
            method=record.method,
            path=record.path,
            status=status,
            attempt=ctx.attempt,
            durationMs=duration,
            error=error,
            circuit=permit.state.value if permit.state is not BreakerState.CLOSED else None,
            replayed=replayed or None,
        )


def _problem_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _parse_moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _snapshot_meta(
    system: System, payload: Any, response: httpx.Response, replayed: bool
) -> SnapshotMeta:
    """Блок `meta` бизнес-ответа мока; у НПД его нет — берём заголовки."""
    meta = payload.get("meta") if isinstance(payload, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    actual: date | None = None
    if isinstance(meta.get("dataActualAt"), str):
        try:
            actual = date.fromisoformat(meta["dataActualAt"])
        except ValueError:
            actual = None
    simulated = meta.get("simulated")
    if simulated is None:
        simulated = response.headers.get("x-mock-simulated", "true").lower() == "true"
    return SnapshotMeta(
        system=system,
        source=meta.get("source") if isinstance(meta.get("source"), str) else None,
        request_id=meta.get("requestId") or response.headers.get("x-request-id"),
        retrieved_at=_parse_moment(meta.get("retrievedAt")) or clock.system_now(),
        data_actual_at=actual,
        simulated=bool(simulated),
        replayed=replayed,
    )
