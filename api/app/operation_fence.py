"""Связка HTTP с ограждением демо-сброса; владельцы данных дают только публичные функции."""

from typing import Any
from uuid import UUID

from anyio import CancelScope
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.modules import applications, auth, companies, offers
from app.shared import db, operations
from app.shared.errors import AppError, problem


def _uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except ValueError:
        return None


def _principal(request: Request) -> auth.Principal | None:
    zone = auth.Zone.BANK if request.url.path.startswith("/bank/") else auth.Zone.CLIENT
    sid = request.cookies.get(auth.sessions.COOKIE[zone])
    return auth.sessions.load(zone, sid) if sid else None


def _scope(
    request: Request, principal: auth.Principal | None, body: dict[str, Any]
) -> operations.Scope | None:
    if request.url.path == "/auth/request-code":
        company_id = _uuid(str(body.get("companyId", "")))
        return companies.operation_scope(company_id) if company_id else None
    if request.url.path == "/auth/verify-code":
        company_id = auth.codes.company_for(str(body.get("requestId", "")))
        return companies.operation_scope(company_id) if company_id else None
    if principal is None:
        return None  # вход и выдача кода ограждены общим замком, а не доступом к чужой компании
    parts = request.url.path.strip("/").split("/")
    scope = None
    if request.url.path == "/me/active-company":
        company_id = _uuid(str(body.get("companyId", "")))
        scope = companies.operation_scope(company_id) if company_id else None
    elif parts[0] == "companies" and len(parts) > 1:
        if parts[1] == "lookup" and len(parts) == 3:
            with db.transaction() as session:
                row = companies.by_inn(session, parts[2])
                company_id = row.id if row is not None else None
        else:
            company_id = _uuid(parts[1])
        scope = companies.operation_scope(company_id) if company_id else None
    elif parts[0] in ("applications", "offers", "contracts") and len(parts) > 1:
        resource_id = _uuid(parts[1])
        if resource_id is not None:
            scope = (
                applications.operation_scope(resource_id)
                if parts[0] == "applications"
                else offers.operation_scope(parts[0], resource_id)
            )
    elif principal.active_company_id is not None:
        scope = companies.operation_scope(principal.active_company_id)
    if (
        scope is not None
        and principal.role == "CLIENT"
        and principal.membership(scope.company_id) is None
    ):
        return None
    return scope


class OperationFenceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        tracked = (
            path.startswith(
                ("/applications", "/offers", "/contracts", "/auth", "/wizard", "/companies")
            )
            or path == "/me/active-company"
        )
        writes = request.method in {"POST", "PUT", "PATCH", "DELETE"} or path.startswith(
            "/companies/"
        )
        if not tracked or not writes:
            return await call_next(request)
        body: dict[str, Any] = {}
        if path in {"/auth/request-code", "/auth/verify-code", "/me/active-company"}:
            try:
                value = await request.json()
                if isinstance(value, dict):
                    body = value
            except ValueError:
                pass  # валидатор роутера вернёт обычную ошибку формата
        try:
            principal = await run_in_threadpool(_principal, request)

            def provider() -> operations.Scope | None:
                return _scope(request, principal, body)

            held = operations.hold(provider)
            await run_in_threadpool(held.__enter__)
        except AppError as exc:
            return problem(request, exc.status, exc.code, detail=exc.detail, headers=exc.headers)
        try:
            return await call_next(request)
        finally:
            # Отмена HTTP-запроса не должна вернуть в пул соединение с забытым session lock.
            with CancelScope(shield=True):
                await run_in_threadpool(held.__exit__, None, None, None)
