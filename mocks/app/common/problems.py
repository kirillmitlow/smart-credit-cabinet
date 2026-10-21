"""Ошибки в формате RFC 7807 (application/problem+json) с машинным полем code (раздел 2.4).

Правило: 400 — только INN_INVALID, всё прочее, не прошедшее схему, — 422 VALIDATION_ERROR.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import FastAPI, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.inn import IdentifierError, validate_inn

PROBLEM_JSON = "application/problem+json"
PROBLEM_BASE = "https://mocks.smart-credit.local/problems/"

log = logging.getLogger("app.problems")


class ProblemException(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        detail: str | None = None,
        *,
        title: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail or code)
        self.status = status
        self.code = code
        self.detail = detail
        self.title = title or HTTPStatus(status).phrase
        self.errors = errors
        self.headers = dict(headers or {})


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def problem_response(
    request: Request,
    status: int,
    code: str,
    *,
    title: str | None = None,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + code.lower().replace("_", "-"),
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "detail": detail,
        "requestId": request_id_of(request),
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(
        jsonable_encoder(body), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


async def _on_problem(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ProblemException):  # чужой класс сюда не попадает
        raise exc
    return problem_response(
        request,
        exc.status,
        exc.code,
        title=exc.title,
        detail=exc.detail,
        errors=exc.errors,
        headers=exc.headers,
    )


async def _on_validation(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # чужой класс сюда не попадает
        raise exc
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return problem_response(
        request,
        422,
        "VALIDATION_ERROR",
        detail="Запрос не прошёл проверку схемы",
        errors=errors,
    )


_HTTP_CODES = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
}


async def _on_http(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # чужой класс сюда не попадает
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(request, exc.status_code, code, detail=detail, headers=exc.headers)


async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Необработанная ошибка", extra={"requestId": request_id_of(request)})
    return problem_response(request, 500, "INTERNAL_ERROR", detail="Внутренняя ошибка мока")


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemException, _on_problem)
    app.add_exception_handler(RequestValidationError, _on_validation)
    app.add_exception_handler(StarletteHTTPException, _on_http)
    app.add_exception_handler(Exception, _on_unexpected)


InnPath = Annotated[str, Path(description="ИНН: 10 цифр (ЮЛ) или 12 (ИП, физлицо)")]


def valid_inn(inn: InnPath) -> str:
    """Зависимость для пути `/{inn}`: неверный ИНН — единственный случай 400 (2.4)."""
    try:
        return validate_inn(inn)
    except IdentifierError as exc:
        raise ProblemException(400, "INN_INVALID", str(exc)) from exc
