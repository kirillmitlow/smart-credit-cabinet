"""API сервиса сценариев (10.4). Всё под X-Admin-Key, блока meta нет: это не внешняя система."""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.common.auth import require_admin
from app.common.db import Session
from app.common.idempotency import OptionalIdempotencyDep
from app.common.problems import ProblemException
from app.common.schemas import problem_responses
from app.roles.scenarios import apply as transfer
from app.roles.scenarios import reset as reset_module
from app.roles.scenarios import service
from app.roles.scenarios.bank_statement import (
    CONTENT_TYPE,
    BankStatementRequest,
    build_statement,
    valid_inn,
)
from app.roles.scenarios.expand import resolved_spec
from app.roles.scenarios.gateway import Gateway
from app.roles.scenarios.locking import locked_session
from app.roles.scenarios.presets import PRESETS
from app.roles.scenarios.schemas import (
    PresetView,
    ResetMode,
    ResetRequest,
    ResetView,
    ScenarioListItem,
    ScenarioOrigin,
    ScenarioSpec,
    ScenarioView,
)

router = APIRouter(prefix="/api/v1", tags=["сценарии"], dependencies=[Depends(require_admin)])
ERRORS = problem_responses(401, 403, 404, 409, 422)
MUTATION_ERRORS = problem_responses(401, 403, 404, 409, 422, 502)
STATEMENT_RESPONSES = {
    **problem_responses(400, 401, 403, 404, 422),
    200: {
        "description": "Синтетическая выписка 1С, Windows-1251, CRLF; без JSON/meta",
        "content": {CONTENT_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        "headers": {
            "Content-Disposition": {"schema": {"type": "string"}},
            "X-Mock-Simulated": {"schema": {"type": "string", "const": "true"}},
        },
    },
}


def _statement_response(**parameters: Any) -> Response:
    try:
        content, filename = build_statement(**parameters)
    except (ValueError, ArithmeticError) as exc:
        raise ProblemException(422, "VALIDATION_ERROR", str(exc)) from exc
    return Response(
        content,
        media_type=CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Mock-Simulated": "true",
        },
    )


@router.get(
    "/scenarios/{code}/documents/bank-statement",
    operation_id="getScenarioBankStatement",
    summary="Скачать воспроизводимую демо-выписку 1С для сценария",
    response_class=Response,
    responses=STATEMENT_RESPONSES,
)
async def scenario_bank_statement(
    request: Request,
    code: str,
    session: Session,
    months: Annotated[int, Query(ge=1, le=24)] = 12,
) -> Response:
    row = await service.get(session, code)
    spec = resolved_spec(ScenarioSpec.model_validate(row.spec))
    identity = (row.expanded or {}).get("identity", {})
    if identity.get("form") == "SELF_EMPLOYED" or not identity or spec.finance is None:
        raise ProblemException(422, "VALIDATION_ERROR", "У сценария нет расчётного счёта бизнеса")
    return _statement_response(
        inn=identity["inn"],
        holder_name=identity.get("shortName") or identity["name"],
        okved=identity["okved"],
        finance=spec.finance,
        regime=spec.finance.tax_regime or "USN_INCOME",
        code=code,
        today=request.app.state.clock.today(),
        months=months,
        turnover=(row.expanded or {}).get("bankCore", {}).get("turnover", []),
    )


@router.post(
    "/documents/bank-statement",
    operation_id="generateBankStatement",
    summary="Сгенерировать демо-выписку 1С для ИНН без чтения или сохранения сценария",
    response_class=Response,
    responses=STATEMENT_RESPONSES,
)
async def generate_bank_statement(request: Request, body: BankStatementRequest) -> Response:
    if not valid_inn(body.inn):
        raise ProblemException(400, "INN_INVALID", "Неверный ИНН владельца выписки")
    seed = str(body.seed) if body.seed is not None else secrets.token_hex(16)
    return _statement_response(
        inn=body.inn,
        holder_name=body.holder_name or f"Демо-владелец {body.inn} (симуляция)",
        okved=body.okved,
        finance=body.finance(),
        regime="OSNO",
        code=f"statement:{body.inn}:{seed}",
        today=request.app.state.clock.today(),
        months=body.months,
    )


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
    summary="Создать сценарий и применить во всех нужных моках",
    status_code=201,
    response_model=ScenarioView,
    responses=MUTATION_ERRORS,
)
async def create(
    request: Request, spec: ScenarioSpec, gateway: Gateway, idem: OptionalIdempotencyDep
) -> Response:
    async def handler() -> Response:
        # Сначала claim ключа идемпотентности, затем очередь изменений сценариев:
        # конкурент того же ключа получает 409 IN_PROGRESS без ожидания HTTP к мокам.
        async with locked_session(request.app.state.database) as session:
            row = await service.create(
                session, spec, request.app.state.clock, bank_bik=request.app.state.settings.bank_bik
            )
            await transfer.apply(session, row, gateway, request.app.state.clock)
            body = (await service.view_with_log(session, row)).model_dump(
                mode="json", by_alias=True
            )
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
    return await service.view_with_log(session, await service.get(session, code))


@router.patch(
    "/scenarios/{code}",
    operation_id="patchScenario",
    summary="Поменять параметры и переприменить (JSON Merge Patch)",
    response_model=ScenarioView,
    responses=MUTATION_ERRORS,
)
async def patch_scenario(
    request: Request,
    code: str,
    changes: Annotated[dict[str, Any], Body(media_type="application/merge-patch+json")],
    gateway: Gateway,
) -> ScenarioView:
    async with locked_session(request.app.state.database) as session:
        row = await service.patch(
            session,
            code,
            changes,
            request.app.state.clock,
            bank_bik=request.app.state.settings.bank_bik,
        )
        await transfer.apply(session, row, gateway, request.app.state.clock)
        return await service.view_with_log(session, row)


@router.post(
    "/scenarios/{code}/apply",
    operation_id="applyScenario",
    summary="Вернуть одну компанию в исходное состояние, включая RUNTIME",
    response_model=ScenarioView,
    responses=MUTATION_ERRORS,
)
async def apply_scenario(
    request: Request, code: str, gateway: Gateway, idem: OptionalIdempotencyDep
) -> Response:
    async def handler() -> Response:
        async with locked_session(request.app.state.database) as session:
            row = await service.get(session, code)
            await transfer.apply(session, row, gateway, request.app.state.clock)
            body = (await service.view_with_log(session, row)).model_dump(
                mode="json", by_alias=True
            )
        return JSONResponse(body)

    return await idem.run(handler)


@router.delete(
    "/scenarios/{code}",
    operation_id="deleteScenario",
    summary="Удалить пользовательский сценарий",
    status_code=204,
    responses=MUTATION_ERRORS,
)
async def delete_scenario(request: Request, code: str, gateway: Gateway) -> Response:
    async with locked_session(request.app.state.database) as session:
        row = await service.get(session, code)
        await transfer.delete(session, row, gateway, request.app.state.clock)
    return Response(status_code=204)


@router.post(
    "/scenarios/reset",
    operation_id="resetScenarios",
    summary="Вернуть все моки в исходное состояние: очистка, chaos в OK, сценарии заново",
    response_model=ResetView,
    responses=MUTATION_ERRORS,
)
async def reset_scenarios(
    request: Request, gateway: Gateway, body: ResetRequest | None = None
) -> ResetView:
    mode = body.mode if body is not None else ResetMode.KEEP_CUSTOM
    async with locked_session(request.app.state.database) as session:
        return await reset_module.reset(
            session,
            gateway,
            request.app.state.clock,
            request.app.state.settings.bank_bik,
            mode,
        )
