"""Сквозной слой запроса: X-Request-Id, задержка «как у настоящей системы», JSON-лог (2.3, 2.6).

Цепочка (8.2): этот слой → chaos (T-106) → ключ API → идемпотентность → обработчик.
Задержка действует только на бизнес-API (/api/*), не на /health, /admin и Swagger.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.inn import mask_inns_in_text

REQUEST_ID_HEADER = "x-request-id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ACCOUNT_IN_TEXT = re.compile(r"(?<!\d)\d{20}(?!\d)")
_rng = random.SystemRandom()

access_log = logging.getLogger("app.access")


def new_request_id() -> str:
    return "req_" + secrets.token_hex(6).upper()


def mask_path(path: str) -> str:
    """Путь для лога: без номеров счетов и с маской ИНН."""
    return mask_inns_in_text(_ACCOUNT_IN_TEXT.sub("[account]", path))


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, latency_ms: tuple[int, int]) -> None:
        self.app = app
        self.latency_ms = latency_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, REQUEST_ID_HEADER)
        request_id = incoming if incoming and _SAFE_REQUEST_ID.match(incoming) else new_request_id()
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)

        try:
            path: str = scope["path"]
            low, high = self.latency_ms
            if high > 0 and path.startswith("/api/"):
                await asyncio.sleep(_rng.uniform(low, high) / 1000)
            await self.app(scope, receive, send_wrapper)
        finally:
            # Пробы здоровья каждые 5 с не засоряют лог, пока всё в порядке
            quiet = scope["path"].startswith("/health/") and status < 500
            access_log.log(
                logging.DEBUG if quiet else logging.INFO,
                "request",
                extra={
                    "requestId": request_id,
                    "method": scope.get("method"),
                    "path": mask_path(scope["path"]),
                    "status": status,
                    "durationMs": round((time.perf_counter() - started) * 1000),
                    "chaos": state.get("chaos"),
                },
            )


def _header(scope: Scope, name: str) -> str | None:
    raw = name.encode("latin-1")
    for key, value in scope.get("headers", []):
        if key.lower() == raw:
            return str(value.decode("latin-1"))
    return None


_EXTRA_FIELDS = ("requestId", "method", "path", "status", "durationMs", "chaos")


class JsonFormatter(logging.Formatter):
    """Одна строка JSON на событие; ИНН в тексте сообщения маскируется."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self.service,
            "msg": mask_inns_in_text(record.getMessage()),
        }
        for field in _EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service: str, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Свой access-лог вместо uvicorn: в нём нет маскирования ИНН
    logging.getLogger("uvicorn.access").disabled = True
