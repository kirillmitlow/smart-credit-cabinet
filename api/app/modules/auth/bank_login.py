"""Демо-вход банка и отдельная банковская сессия (T-213, D-085, D-090)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.modules.auth import service, sessions
from app.modules.auth.dependencies import BankPrincipal
from app.modules.auth.principal import Principal, Zone
from app.shared import db
from app.shared.errors import AppError

router = APIRouter(tags=["вход банка"])


class BankAuditRecorder(Protocol):
    def __call__(
        self,
        session: Session,
        action: str,
        *,
        actor_id: UUID,
        actor_role: str,
        details: dict[str, Any],
    ) -> None: ...


_audit_record: BankAuditRecorder | None = None


def register_bank_audit_recorder(recorder: BankAuditRecorder) -> None:
    """Sibling-модули auth/audit связывает app.wiring, без импорта через границу R1."""
    global _audit_record
    _audit_record = recorder


def _record(session: Session, action: str, principal: Principal) -> None:
    if _audit_record is None:
        raise RuntimeError("Не настроен аудит входа банка")
    _audit_record(
        session,
        action,
        actor_id=principal.user_id,
        actor_role=principal.role,
        details={"zone": Zone.BANK.value, "level": principal.level},
    )


class BankDemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: service.BankRole = "UNDERWRITER"


class BankMeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: UUID
    display_name: str
    role: Literal["UNDERWRITER", "ADMIN"]
    level: Literal["L1", "L2"]


def _me(principal: Principal) -> BankMeResponse:
    return BankMeResponse.model_validate(
        {
            "user_id": principal.user_id,
            "display_name": principal.display_name,
            "role": principal.role,
            "level": principal.level,
        }
    )


def _login(body: BankDemoLoginRequest, old_sid: str | None) -> tuple[str, BankMeResponse]:
    with db.transaction() as session:
        user = service.demo_bank_user(session, body.role)
        if user.status != "ACTIVE" or user.role != body.role or user.level != "L2":
            raise AppError(403, "FORBIDDEN", "Демо-вход сотрудника банка недоступен")
        principal = Principal(
            user_id=user.id,
            role=user.role,
            zone=Zone.BANK,
            display_name=user.display_name,
            level=user.level,
        )
        sid = sessions.create(principal, replace_sid=old_sid)
        _record(session, "LOGIN", principal)
        return sid, _me(principal)


def _require_demo(request: Request) -> None:
    if not request.app.state.settings.demo_mode:
        raise AppError(403, "DEMO_MODE_DISABLED", "Демо-режим выключен")


@router.post(
    "/auth/bank-demo-login",
    operation_id="bankDemoLogin",
    summary="Войти как демо-андеррайтер L2 или администратор",
    response_model=BankMeResponse,
    response_model_by_alias=True,
    dependencies=[Depends(_require_demo)],
    responses={
        403: {"description": "DEMO_MODE_DISABLED: демо выключено; FORBIDDEN: доступ отозван"},
        422: {"description": "VALIDATION_ERROR: разрешены только роли UNDERWRITER и ADMIN"},
        503: {"description": "SESSION_STORE_UNAVAILABLE: хранилище сессий недоступно"},
    },
)
async def bank_demo_login(
    request: Request,
    response: Response,
    body: BankDemoLoginRequest | None = None,
    sid_bank: Annotated[str | None, Cookie()] = None,
) -> BankMeResponse:
    sid, me = await run_in_threadpool(_login, body or BankDemoLoginRequest(), sid_bank)
    response.set_cookie(
        sessions.COOKIE[Zone.BANK],
        sid,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.cookie_secure,
        path="/",
    )
    return me


@router.get(
    "/auth/bank-me",
    operation_id="getBankMe",
    summary="Кто я в банковской зоне и мой уровень полномочий",
    response_model=BankMeResponse,
    response_model_by_alias=True,
    responses={
        401: {"description": "UNAUTHENTICATED: нет банковской сессии или доступ отозван"},
        403: {"description": "FORBIDDEN: сессия не даёт права работать в банковской зоне"},
        503: {"description": "SESSION_STORE_UNAVAILABLE: хранилище сессий недоступно"},
    },
)
def bank_me(principal: BankPrincipal) -> BankMeResponse:
    return _me(principal)


def _logout(sid: str) -> None:
    principal = sessions.load(Zone.BANK, sid)
    sessions.destroy(Zone.BANK, sid)
    if principal is None or principal.zone is not Zone.BANK:
        return
    if principal.role not in {"UNDERWRITER", "ADMIN"}:
        return
    with db.transaction() as session:
        _record(session, "LOGOUT", principal)


@router.post(
    "/auth/bank-logout",
    operation_id="bankLogout",
    summary="Выйти из банковской зоны",
    status_code=204,
    responses={
        503: {"description": "SESSION_STORE_UNAVAILABLE: хранилище сессий недоступно"},
    },
)
async def bank_logout(sid_bank: Annotated[str | None, Cookie()] = None) -> Response:
    if sid_bank:
        await run_in_threadpool(_logout, sid_bank)
    result = Response(status_code=204)
    result.delete_cookie(sessions.COOKIE[Zone.BANK], path="/")
    return result
