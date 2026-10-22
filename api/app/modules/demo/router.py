"""Демо-ручки (T-370, T-371, 60-05, D-081, D-086): только при `DEMO_MODE=true`.

Локально открыты без входа (D-086, Q-090): панель — для жюри, а не для сотрудников банка. Код стенда
для облака добавит T-374. На админ-API моков и рабочее место банка это исключение не распространяется.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from app.modules.demo import reset_all
from app.shared import clock
from app.shared.errors import AppError
from app.shared.settings import get_settings


def require_demo_mode() -> None:
    """Вне `DEMO_MODE` все `/demo/*` отвечают `403 DEMO_MODE_DISABLED` (50-07)."""
    if not get_settings().demo_mode:
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
