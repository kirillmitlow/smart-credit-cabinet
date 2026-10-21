"""API сервиса сценариев (10.4). Всё под X-Admin-Key, блока meta нет: это не внешняя система."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.common.auth import require_admin
from app.common.db import Session
from app.common.idempotency import OptionalIdempotencyDep
from app.common.schemas import problem_responses
from app.roles.scenarios import service
from app.roles.scenarios.presets import PRESETS
from app.roles.scenarios.schemas import (
    PresetView,
    ScenarioListItem,
    ScenarioOrigin,
    ScenarioSpec,
    ScenarioView,
)

router = APIRouter(prefix="/api/v1", tags=["сценарии"], dependencies=[Depends(require_admin)])
ERRORS = problem_responses(401, 403, 404, 409, 422)


@router.get("/presets", operation_id="listPresets", summary="Пресеты и их параметры по умолчанию")
async def list_presets() -> list[PresetView]:
    return [PresetView(code=code, title=title, defaults=d) for code, (title, d) in PRESETS.items()]


@router.post(
    "/scenarios/preview",
    operation_id="previewScenario",
    summary="Развернуть сценарий без сохранения",
    responses=problem_responses(401, 403, 422),
)
async def preview(request: Request, spec: ScenarioSpec, session: Session) -> dict[str, Any]:
    return await service.preview(
        session, spec, request.app.state.clock, request.app.state.settings.bank_bik
    )


@router.post(
    "/scenarios",
    operation_id="createScenario",
    summary="Создать сценарий (и применить, когда готова раскладка по мокам)",
    status_code=201,
    response_model=ScenarioView,
    responses=ERRORS,
)
async def create(
    request: Request, spec: ScenarioSpec, session: Session, idem: OptionalIdempotencyDep
) -> Response:
    async def handler() -> Response:
        row = await service.create(session, spec, request.app.state.clock)
        await session.commit()
        body = service.view(row).model_dump(mode="json", by_alias=True)
        return JSONResponse(body, status_code=201)

    return await idem.run(handler)


@router.get(
    "/scenarios",
    operation_id="listScenarios",
    summary="Список сценариев",
    response_model=list[ScenarioListItem],
    responses=ERRORS,
)
async def list_scenarios(
    session: Session, origin: ScenarioOrigin | None = None
) -> list[ScenarioListItem]:
    return await service.list_scenarios(session, origin)


@router.get(
    "/scenarios/{code}",
    operation_id="getScenario",
    summary="Параметры, ожидания, развёрнутые данные и учётки",
    response_model=ScenarioView,
    responses=ERRORS,
)
async def get_scenario(code: str, session: Session) -> ScenarioView:
    return service.view(await service.get(session, code))


@router.patch(
    "/scenarios/{code}",
    operation_id="patchScenario",
    summary="Поменять параметры (JSON Merge Patch, массивы заменяются целиком)",
    response_model=ScenarioView,
    responses=ERRORS,
)
async def patch_scenario(
    request: Request,
    code: str,
    changes: Annotated[dict[str, Any], Body(media_type="application/merge-patch+json")],
    session: Session,
) -> ScenarioView:
    row = await service.patch(session, code, changes, request.app.state.clock)
    await session.commit()
    return service.view(row)


@router.delete(
    "/scenarios/{code}",
    operation_id="deleteScenario",
    summary="Удалить пользовательский сценарий",
    status_code=204,
    responses=ERRORS,
)
async def delete_scenario(code: str, session: Session) -> Response:
    await service.delete(session, code)
    await session.commit()
    return Response(status_code=204)
