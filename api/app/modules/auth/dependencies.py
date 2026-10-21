"""Зависимости FastAPI: текущий клиент или сотрудник банка из своей cookie (T-210)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.modules.auth import sessions
from app.modules.auth.principal import Principal, Zone
from app.shared.errors import AppError


def _unauthenticated() -> AppError:
    return AppError(401, "UNAUTHENTICATED", "Нужно войти")


def _principal(zone: Zone) -> Callable[[Request], Principal]:
    def dependency(request: Request) -> Principal:
        sid = request.cookies.get(sessions.COOKIE[zone])
        if not sid:
            raise _unauthenticated()
        principal = sessions.load(zone, sid)
        if principal is None:
            raise _unauthenticated()
        return principal

    return dependency


current_client = _principal(Zone.CLIENT)
current_bank = _principal(Zone.BANK)

ClientPrincipal = Annotated[Principal, Depends(current_client)]
BankPrincipal = Annotated[Principal, Depends(current_bank)]


def require(permission: str) -> Callable[[Principal], Principal]:
    """Право внутри активной компании (матрица 10-03). Нет права — 403 FORBIDDEN."""

    def dependency(principal: ClientPrincipal) -> Principal:
        company = principal.active_company_id
        member = principal.membership(company) if company else None
        if member is None or (permission not in member.permissions and member.role != "DIRECTOR"):
            raise AppError(403, "FORBIDDEN", f"Нет права {permission}")
        return principal

    return dependency
