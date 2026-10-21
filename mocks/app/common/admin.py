"""Админ-API данных (раздел 8.3): одинаковый набор запросов у всех четырёх моков.

Роль описывает только своё хранение через AdminHandler, а маршруты, ключ X-Admin-Key, JSON Merge
Patch (RFC 7396) и ошибки общие. Тело PUT — в терминах ответа бизнес-API без meta: роль передаёт
сюда ту же Pydantic-схему, второй схемы не пишем. `api` эти маршруты не вызывает
(кроме demo, D-081).

Модуль без `from __future__ import annotations`: тип тела PUT подставляется в маршрут динамически.
"""

import copy
from abc import ABC, abstractmethod
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import require_admin
from app.common.db import Origin, Session
from app.common.problems import InnPath, ProblemException, valid_inn
from app.common.schemas import CamelModel, problem_responses


class SubjectView(CamelModel):
    """Всё, что система знает о субъекте: данные сценария и записи, появившиеся в работе."""

    inn: str
    scenario_code: str | None
    origin: Literal["SCENARIO", "RUNTIME"]
    data: dict[str, Any]
    runtime: dict[str, Any] = {}


class SubjectSummary(CamelModel):
    inn: str
    scenario_code: str | None
    origin: Literal["SCENARIO", "RUNTIME"]
    title: str | None = None


class SubjectPage(CamelModel):
    items: list[SubjectSummary]
    total: int
    limit: int
    offset: int


class ScenarioCount(CamelModel):
    scenario_code: str
    subjects: int


class Deleted(CamelModel):
    deleted: int


class AdminHandler[BodyT: BaseModel](ABC):
    """Хранение одной роли. Методы получают открытую сессию; коммит делает общий слой."""

    body_model: type[BodyT]

    @abstractmethod
    async def put(
        self, session: AsyncSession, inn: str, body: BodyT, scenario_code: str | None
    ) -> None:
        """Создать или полностью заменить данные субъекта (вместе с его RUNTIME-записями)."""

    @abstractmethod
    async def get_body(self, session: AsyncSession, inn: str) -> BodyT | None:
        """Данные субъекта в терминах тела PUT (для PATCH и GET)."""

    @abstractmethod
    async def view(self, session: AsyncSession, inn: str) -> SubjectView | None: ...

    @abstractmethod
    async def list_subjects(
        self,
        session: AsyncSession,
        scenario: str | None,
        origin: Origin | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SubjectSummary], int]: ...

    @abstractmethod
    async def delete(self, session: AsyncSession, inn: str) -> bool:
        """Удалить субъекта со всеми записями, включая RUNTIME."""

    @abstractmethod
    async def scenarios(self, session: AsyncSession) -> list[ScenarioCount]: ...

    @abstractmethod
    async def delete_scenario(self, session: AsyncSession, code: str) -> int:
        """Удалить созданное сценарием вместе с RUNTIME-записями; вернуть число субъектов."""

    @abstractmethod
    async def wipe(self, session: AsyncSession) -> None:
        """Очистить данные мока, не трогая справочники."""

    def check(self, inn: str, body: BodyT) -> None:  # noqa: B027 — проверка по умолчанию пустая
        """Межполевые проверки роли; ошибка — ProblemException 422 с понятной причиной."""


def merge_patch(target: Any, patch: Any) -> Any:
    """JSON Merge Patch (RFC 7396): объекты склеиваются, массивы заменяются, null удаляет."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def subject_not_found(inn: str) -> ProblemException:
    return ProblemException(404, "SUBJECT_NOT_FOUND", f"Субъект {inn} в этой системе не найден")


def _validate[BodyT: BaseModel](
    handler: AdminHandler[BodyT], inn: str, raw: dict[str, Any]
) -> BodyT:
    try:
        body = handler.body_model.model_validate(raw)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise ProblemException(
            422, "VALIDATION_ERROR", "Данные субъекта не прошли проверку", errors=errors
        ) from exc
    handler.check(inn, body)
    return body


ScenarioHeader = Annotated[
    str | None,
    Header(
        alias="X-Scenario-Code",
        max_length=64,
        description="Код сценария: записи получат origin = SCENARIO и этот scenario_code",
    ),
]

ERRORS = problem_responses(400, 401, 403, 404, 422)


def make_admin_router(handler: AdminHandler[Any]) -> APIRouter:
    router = APIRouter(
        prefix="/admin", tags=["admin: данные"], dependencies=[Depends(require_admin)]
    )
    body_model = handler.body_model

    @router.put(
        "/subjects/{inn}",
        summary="Создать или полностью заменить данные субъекта",
        operation_id="adminPutSubject",
        response_model=SubjectView,
        responses=ERRORS,
    )
    async def put_subject(
        inn: InnPath,
        body: Annotated[body_model, Body()],  # type: ignore[valid-type]
        session: Session,
        response: Response,
        scenario_code: ScenarioHeader = None,
    ) -> SubjectView:
        valid_inn(inn)
        handler.check(inn, body)
        existed = await handler.get_body(session, inn) is not None
        await handler.put(session, inn, body, scenario_code)
        await session.commit()
        response.status_code = 200 if existed else 201
        return await _view(session, inn)

    @router.patch(
        "/subjects/{inn}",
        summary="Частичная правка (JSON Merge Patch, массивы заменяются целиком)",
        operation_id="adminPatchSubject",
        response_model=SubjectView,
        responses=ERRORS,
    )
    async def patch_subject(
        inn: InnPath,
        patch: Annotated[dict[str, Any], Body(media_type="application/merge-patch+json")],
        session: Session,
    ) -> SubjectView:
        valid_inn(inn)
        current = await handler.get_body(session, inn)
        if current is None:
            raise subject_not_found(inn)
        merged = merge_patch(current.model_dump(mode="json", by_alias=True), patch)
        view = await handler.view(session, inn)
        scenario_code = view.scenario_code if view else None
        await handler.put(session, inn, _validate(handler, inn, merged), scenario_code)
        await session.commit()
        return await _view(session, inn)

    @router.get(
        "/subjects/{inn}",
        summary="Всё о субъекте, включая RUNTIME-записи",
        operation_id="adminGetSubject",
        response_model=SubjectView,
        responses=ERRORS,
    )
    async def get_subject(inn: InnPath, session: Session) -> SubjectView:
        valid_inn(inn)
        return await _view(session, inn)

    @router.get(
        "/subjects",
        summary="Список субъектов",
        operation_id="adminListSubjects",
        response_model=SubjectPage,
        responses=ERRORS,
    )
    async def list_subjects(
        session: Session,
        scenario: Annotated[str | None, Query(max_length=64)] = None,
        origin: Origin | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SubjectPage:
        items, total = await handler.list_subjects(session, scenario, origin, limit, offset)
        return SubjectPage(items=items, total=total, limit=limit, offset=offset)

    @router.delete(
        "/subjects/{inn}",
        summary="Удалить субъекта со всеми записями",
        operation_id="adminDeleteSubject",
        status_code=204,
        responses=ERRORS,
    )
    async def delete_subject(inn: InnPath, session: Session) -> Response:
        valid_inn(inn)
        if not await handler.delete(session, inn):
            raise subject_not_found(inn)
        await session.commit()
        return Response(status_code=204)

    @router.get(
        "/scenarios",
        summary="Какие сценарии есть и сколько у каждого субъектов",
        operation_id="adminListScenarios",
        response_model=list[ScenarioCount],
        responses=ERRORS,
    )
    async def list_scenarios(session: Session) -> list[ScenarioCount]:
        return await handler.scenarios(session)

    @router.delete(
        "/scenarios/{code}",
        summary="Удалить всё, что создано сценарием, вместе с RUNTIME-записями",
        operation_id="adminDeleteScenario",
        response_model=Deleted,
        responses=ERRORS,
    )
    async def delete_scenario(code: str, session: Session) -> Deleted:
        deleted = await handler.delete_scenario(session, code)
        await session.commit()
        return Deleted(deleted=deleted)

    @router.post(
        "/wipe",
        summary="Очистить данные мока (справочники остаются)",
        operation_id="adminWipe",
        status_code=204,
        responses=ERRORS,
    )
    async def wipe(session: Session) -> Response:
        await handler.wipe(session)
        await session.commit()
        return Response(status_code=204)

    async def _view(session: AsyncSession, inn: str) -> SubjectView:
        view = await handler.view(session, inn)
        if view is None:
            raise subject_not_found(inn)
        return view

    return router
