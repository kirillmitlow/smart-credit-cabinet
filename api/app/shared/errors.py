"""Ошибки RFC 7807 с машинным `code` (50-07, T-202).

`detail` — для разработчика и логов, не для клиента: текст на экране фронт берёт из словаря по
`code` (60-06). Стек наружу не отдаётся никогда.
"""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
PROBLEM_BASE = "https://smart-credit.local/problems/"

log = structlog.get_logger("app.errors")


class AppError(Exception):
    """Ожидаемая ошибка сценария: статус HTTP, машинный код, подробности для разработчика."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail or code)
        self.status = status
        self.code = code
        self.detail = detail
        self.errors = errors
        self.headers = dict(headers or {})


def not_found(what: str = "Ресурс") -> AppError:
    """Чужое и несуществующее неразличимы: всегда 404 (R11)."""
    return AppError(404, "NOT_FOUND", f"{what} не найден")


def conflict(code: str, detail: str | None = None) -> AppError:
    return AppError(409, code, detail)


def problem(
    request: Request,
    status: int,
    code: str,
    *,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + code.lower().replace("_", "-"),
        "title": HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "detail": detail,
        "requestId": getattr(request.state, "request_id", None),
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(
        jsonable_encoder(body), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


async def _on_app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # чужой класс сюда не попадает
        raise exc
    return problem(
        request, exc.status, exc.code, detail=exc.detail, errors=exc.errors, headers=exc.headers
    )


async def _on_validation(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return problem(request, 422, "VALIDATION_ERROR", errors=errors)


_HTTP_CODES = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


async def _on_http(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    return problem(request, exc.status_code, code, headers=exc.headers)


async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_error", exc_info=exc)
    return problem(request, 500, "INTERNAL_ERROR")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _on_app_error)
    app.add_exception_handler(RequestValidationError, _on_validation)
    app.add_exception_handler(StarletteHTTPException, _on_http)
    app.add_exception_handler(Exception, _on_unexpected)
