"""Демо-ручки (T-370, T-371, 60-05, D-081, D-086): только при `DEMO_MODE=true`.

Локально открыты без входа (D-086, Q-090): панель — для жюри, а не для сотрудников банка. Код стенда
для облака проверяет T-374. На админ-API моков и рабочее место банка это исключение не распространяется.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Cookie, Depends, Header, Path, Request, Response
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from app.modules.demo import (
    catalog,
    chaos,
    create_scenario,
    persona_login,
    reset_all,
    reset_persona,
)
from app.modules.demo.control_guard import limit_demo_request, require_control
from app.modules.integrations import System
from app.shared import clock
from app.shared.errors import AppError
from app.shared.settings import get_settings


def require_demo_mode(request: Request) -> None:
    """Вне `DEMO_MODE` все `/demo/*` отвечают `403 DEMO_MODE_DISABLED` (50-07)."""
    if not request.app.state.settings.demo_mode or not get_settings().demo_mode:
        raise AppError(403, "DEMO_MODE_DISABLED", "Демо-режим выключен")


router = APIRouter(prefix="/demo", tags=["демо"], dependencies=[Depends(require_demo_mode)])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ResetStepOut(Camel):
    step: reset_all.ResetStep
    title: str
    status: Literal["DONE"] = "DONE"


class ResetOut(Camel):
    status: Literal["DONE"] = "DONE"
    steps: list[ResetStepOut]
    duration_ms: int
    finished_at: datetime


def _reset() -> ResetOut:
    done = reset_all.run()
    return ResetOut(
        steps=[ResetStepOut(step=d.step, title=reset_all.TITLES[d.step]) for d in done.steps],
        duration_ms=done.duration_ms,
        finished_at=clock.system_now(),
    )


@router.post(
    "/reset",
    dependencies=[Depends(require_control)],
    operation_id="demoReset",
    summary="Единый сброс стенда: моки, база api, сессии и кэш",
    description=(
        "Отвечает по факту завершения, а не по таймеру. При ошибке `502 DEMO_RESET_FAILED` "
        "в `errors[0].step` стоит шаг (`MOCKS`, `DATABASE`, `SESSIONS`); повторный вызов "
        "безопасно доводит сброс. Параллельный вызов: `409 DEMO_RESET_IN_PROGRESS`."
    ),
    response_model=ResetOut,
    response_model_by_alias=True,
    responses={
        403: {"description": "DEMO_MODE выключен (`DEMO_MODE_DISABLED`)"},
        409: {"description": "Сброс уже выполняется (`DEMO_RESET_IN_PROGRESS`)"},
        502: {"description": "Сброс остановился на одном из шагов (`DEMO_RESET_FAILED`)"},
    },
)
async def reset() -> ResetOut:
    return await run_in_threadpool(_reset)


class PersonaResetStepOut(Camel):
    step: reset_persona.Step
    title: str
    status: Literal["DONE"] = "DONE"


class PersonaResetOut(Camel):
    status: Literal["DONE"] = "DONE"
    company_id: UUID
    generation: int
    steps: list[PersonaResetStepOut]
    duration_ms: int
    finished_at: datetime


@router.post(
    "/personas/{code}/reset",
    dependencies=[Depends(require_control)],
    operation_id="demoResetPersona",
    summary="Вернуть одну компанию к исходному сценарию",
    description=(
        "Не затрагивает соседние компании. Сохраняет идентификатор компании и вход пользователя. "
        "При частичном сбое компания закрыта для изменений до успешного повтора. "
        "409 DEMO_RESET_IN_PROGRESS: операция компании или сброс ещё выполняется. "
        "502 DEMO_RESET_FAILED: errors[0].step содержит MOCKS, CACHE или DATABASE."
    ),
    response_model=PersonaResetOut,
    response_model_by_alias=True,
    responses={
        403: {"description": "Демо-режим выключен"},
        404: {"description": "Компания сценария не найдена"},
        409: {"description": "Операция компании или сброс ещё выполняется"},
        502: {"description": "Частичный сбой; повторите сброс компании"},
    },
)
async def reset_one_persona(
    code: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")],
) -> PersonaResetOut:
    done = await run_in_threadpool(reset_persona.run, code)
    return PersonaResetOut(
        company_id=done.company_id,
        generation=done.generation,
        steps=[
            PersonaResetStepOut(step=step, title=reset_persona.TITLES[step])
            for step in reset_persona.Step
        ],
        duration_ms=done.duration_ms,
        finished_at=clock.system_now(),
    )


@router.get("/personas", operation_id="demoListPersonas", response_model=list[catalog.Persona])
def personas() -> list[catalog.Persona]:
    return catalog.list_personas()


@router.get("/chaos", operation_id="demoGetChaos", response_model=list[chaos.ChaosView])
def get_chaos() -> list[chaos.ChaosView]:
    return chaos.list_chaos()


@router.put(
    "/chaos/{system}",
    operation_id="demoSetChaos",
    response_model=chaos.ChaosView,
    dependencies=[Depends(require_control)],
)
def put_chaos(system: System, body: chaos.ChaosInput) -> chaos.ChaosView:
    return chaos.set_chaos(system, body)


@router.post(
    "/scenarios",
    operation_id="demoCreateScenario",
    status_code=201,
    response_model=create_scenario.CreatedScenario,
    summary="Создать тестовую компанию и применить сценарий",
    description="Тело — ScenarioSpec сервиса сценариев; форма или preset обязательны. "
    "Если code не задан, он стабильно определяется ключом запроса. Учётки — только клиентские роли. "
    "Idempotency-Key сохраняйте при повторе после таймаута. "
    "Моки и каталог api обновляются до подтверждения успеха; учётки/полный spec не возвращаются.",
    dependencies=[Depends(limit_demo_request)],
    responses={
        400: {"description": "INN_INVALID"},
        503: {"description": "DEMO_CONTROL_UNAVAILABLE"},
        403: {"description": "DEMO_MODE_DISABLED"},
        409: {
            "description": (
                "SCENARIO_EXISTS / SCENARIO_INN_EXISTS / IDEMPOTENCY_KEY_REUSED / "
                "IDEMPOTENCY_IN_PROGRESS / DEMO_RESET_IN_PROGRESS"
            )
        },
        422: {"description": "VALIDATION_ERROR"},
        429: {"description": "RATE_LIMITED"},
        502: {"description": "DEMO_SCENARIOS_UNAVAILABLE / DEMO_SCENARIO_INVALID_RESPONSE"},
    },
)
def create_demo_scenario(
    body: Annotated[
        create_scenario.ScenarioInput,
        Body(
            examples=[
                {
                    "title": "Тестовый ИП",
                    "preset": "IP_HEALTHY",
                    "users": [{"login": "owner", "role": "DIRECTOR", "personRef": "self"}],
                }
            ]
        ),
    ],
    key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"^\S+$")
    ],
    response: Response,
) -> create_scenario.CreatedScenario:
    result = create_scenario.create(
        body.model_dump(mode="json", by_alias=True, exclude_unset=True), key
    )
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return create_scenario.CreatedScenario.model_validate(result.body)


@router.post(
    "/personas/{code}/login",
    operation_id="demoLoginPersona",
    response_model=persona_login.LoginResult,
    summary="Служебный вход персоны для интеграционных тестов",
    description="Только при DEMO_MODE. Логин существующей активной учётки указывается явно. "
    "Пользовательский UI и e2e используют обычный вход по ИНН и коду. "
    "Создаёт только sid_client; банковская сессия не меняется.",
    dependencies=[Depends(limit_demo_request)],
    responses={
        403: {"description": "DEMO_MODE_DISABLED / FORBIDDEN"},
        404: {"description": "NOT_FOUND: персона или активное членство отсутствуют"},
        409: {"description": "DEMO_RESET_IN_PROGRESS"},
        422: {"description": "VALIDATION_ERROR"},
        429: {"description": "RATE_LIMITED"},
        503: {"description": "SESSION_STORE_UNAVAILABLE / DEMO_CONTROL_UNAVAILABLE"},
    },
)
def login_demo_persona(
    code: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")],
    body: persona_login.LoginInput,
    request: Request,
    response: Response,
    sid_client: Annotated[str | None, Cookie()] = None,
) -> persona_login.LoginResult:
    done = persona_login.login(code, body.login, sid_client)
    response.set_cookie(
        "sid_client",
        done.sid,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return done.result
