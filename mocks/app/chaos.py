"""Управляемые сбои (раздел 8.2): режим мока и сбой одного запроса заголовком X-Mock-Scenario.

ERROR, DOWN, TIMEOUT, SLOW и 429 срабатывают до обработчика: ни данных, ни ключа идемпотентности.
LOST_RESPONSE выполняет запрос до конца и обрывает соединение, не отправив ответ. Режим живёт
в памяти процесса (поэтому один воркер), рестарт возвращает OK. На /health и /admin не действует.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.auth import require_admin
from app.common.clock import Clock
from app.common.problems import problem_response
from app.common.schemas import CamelModel, problem_responses

DEFAULT_SLOW_MS = 5000
TIMEOUT_SECONDS = 60.0
SERVER_SEND_KEY = "mock.server_send"
_rng = random.SystemRandom()


class ChaosMode(StrEnum):
    OK = "OK"
    SLOW = "SLOW"
    ERROR = "ERROR"
    DOWN = "DOWN"
    TIMEOUT = "TIMEOUT"
    LOST_RESPONSE = "LOST_RESPONSE"


class ChaosConfig(CamelModel):
    mode: ChaosMode = ChaosMode.OK
    error_rate: float = Field(default=1.0, ge=0, le=1, description="Доля сломанных запросов")
    latency_ms: int | None = Field(default=None, ge=0, le=120_000, description="Для SLOW")
    paths: list[str] | None = Field(default=None, description="null — все /api/v1/*")
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    until: datetime | None = Field(default=None, description="Когда само вернётся в OK")


class ChaosState:
    """Текущий режим и окно лимита запросов; один экземпляр на процесс."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.config = ChaosConfig()
        self._hits: deque[float] = deque()

    def set(self, config: ChaosConfig) -> ChaosConfig:
        self.config = config
        self._hits.clear()
        return self.current()

    def current(self) -> ChaosConfig:
        until = self.config.until
        if until is not None and self._clock.now() >= until:
            self.config = ChaosConfig()
        return self.config

    def applies_to(self, path: str) -> bool:
        paths = self.current().paths
        return paths is None or any(path.startswith(p) for p in paths)

    def rate_limited(self) -> int | None:
        """Секунд до следующей попытки, если лимит в минуту исчерпан."""
        limit = self.current().rate_limit_per_minute
        if limit is None:
            return None
        now = time.monotonic()
        while self._hits and now - self._hits[0] >= 60:
            self._hits.popleft()
        if len(self._hits) >= limit:
            return max(1, int(60 - (now - self._hits[0])) + 1)
        self._hits.append(now)
        return None


def parse_scenario_header(raw: str) -> tuple[ChaosMode, int | None] | None:
    """`ERROR`, `SLOW`, `SLOW:3000`, `TIMEOUT`, `LOST_RESPONSE`; иное — None."""
    name, _, arg = raw.strip().partition(":")
    allowed = {ChaosMode.ERROR, ChaosMode.SLOW, ChaosMode.TIMEOUT, ChaosMode.LOST_RESPONSE}
    if name not in {m.value for m in allowed}:
        return None
    mode = ChaosMode(name)
    if arg:
        if mode is not ChaosMode.SLOW or not arg.isdigit():
            return None
        return mode, int(arg)
    return mode, None


class ChaosMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        state: ChaosState = scope["app"].state.chaos
        request_state = scope.setdefault("state", {})

        header = _header(scope, b"x-mock-scenario")
        if header is not None:
            parsed = parse_scenario_header(header)
            if parsed is None:
                await _problem(
                    scope,
                    receive,
                    send,
                    422,
                    "VALIDATION_ERROR",
                    "X-Mock-Scenario: допустимо ERROR, SLOW, SLOW:<мс>, TIMEOUT, LOST_RESPONSE",
                )
                return
            mode, latency = parsed
            rate = 1.0
        elif state.applies_to(path):
            config = state.current()
            retry_after = state.rate_limited()
            if retry_after is not None:
                request_state["chaos"] = "RATE_LIMITED"
                await _problem(
                    scope,
                    receive,
                    send,
                    429,
                    "RATE_LIMITED",
                    "Превышен лимит запросов",
                    {"Retry-After": str(retry_after)},
                )
                return
            mode, latency, rate = config.mode, config.latency_ms, config.error_rate
        else:
            mode, latency, rate = ChaosMode.OK, None, 0.0

        if mode is ChaosMode.OK:
            await self.app(scope, receive, send)
            return
        request_state["chaos"] = mode.value

        if mode is ChaosMode.SLOW:
            await asyncio.sleep((latency if latency is not None else DEFAULT_SLOW_MS) / 1000)
            await self.app(scope, receive, send)
        elif mode is ChaosMode.DOWN or (mode is ChaosMode.ERROR and _rng.random() < rate):
            await _problem(
                scope,
                receive,
                send,
                503,
                "SERVICE_UNAVAILABLE",
                "Система временно недоступна",
                {"Retry-After": "1"},
            )
        elif mode is ChaosMode.TIMEOUT:
            await asyncio.sleep(TIMEOUT_SECONDS)
            await _problem(scope, receive, send, 503, "SERVICE_UNAVAILABLE", "Нет ответа")
        elif mode is ChaosMode.LOST_RESPONSE and _rng.random() < rate:
            await self._lose_response(scope, receive, send)
        else:
            request_state["chaos"] = None
            await self.app(scope, receive, send)

    async def _lose_response(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обработчик отрабатывает и коммитит, а ответ не уходит: соединение рвётся."""

        async def swallow(message: Message) -> None:
            return None

        await self.app(scope, receive, swallow)
        drop_connection(scope)


class LostResponseError(ConnectionError):
    """Сервер без доступа к сокету (тестовый транспорт): обрыв имитируется исключением."""


def drop_connection(scope: Scope) -> None:
    server_send: Any = scope.get(SERVER_SEND_KEY)
    transport = getattr(getattr(server_send, "__self__", None), "transport", None)
    if transport is None:
        raise LostResponseError("LOST_RESPONSE: ответ не отправлен")
    transport.close()


class ServerSendShim:
    """Внешняя обёртка для uvicorn: хранит исходный send, чтобы LOST_RESPONSE оборвал сокет."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope[SERVER_SEND_KEY] = send
        await self.app(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None


async def _problem(
    scope: Scope,
    receive: Receive,
    send: Send,
    status: int,
    code: str,
    detail: str,
    headers: dict[str, str] | None = None,
) -> None:
    request = Request(scope, receive)
    response = problem_response(request, status, code, detail=detail, headers=headers)
    await response(scope, receive, send)


router = APIRouter(
    prefix="/admin/chaos", tags=["admin: chaos"], dependencies=[Depends(require_admin)]
)

AdminProblems = problem_responses(401, 403, 422)


@router.get("", summary="Текущий режим сбоев", operation_id="getChaos", responses=AdminProblems)
async def get_chaos(request: Request) -> ChaosConfig:
    state: ChaosState = request.app.state.chaos
    return state.current()


@router.put("", summary="Включить режим сбоев", operation_id="putChaos", responses=AdminProblems)
async def put_chaos(request: Request, config: ChaosConfig) -> ChaosConfig:
    state: ChaosState = request.app.state.chaos
    return state.set(config)
