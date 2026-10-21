"""X-Request-Id и X-Instance-Id, контекст логов на время запроса, access-лог (T-202)."""

from __future__ import annotations

import re
import socket
import time

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.ids import new_request_id
from app.shared.logs import mask_text

INSTANCE_ID = socket.gethostname()
_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
access_log = structlog.get_logger("app.access")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next(
            (v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-request-id"),
            None,
        )
        request_id = incoming if incoming and _SAFE.match(incoming) else new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(requestId=request_id)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
                headers["X-Instance-Id"] = INSTANCE_ID
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path: str = scope["path"]
            if not (path.startswith("/health/") and status < 500):
                access_log.info(
                    "request",
                    method=scope.get("method"),
                    path=mask_text(path),
                    status=status,
                    durationMs=round((time.perf_counter() - started) * 1000),
                )
            structlog.contextvars.unbind_contextvars("requestId")
