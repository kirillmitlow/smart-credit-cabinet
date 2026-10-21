"""Хранение и правка сценариев (10.4, 10.7). Разворачивание и раскладка по мокам — expand/apply."""

from __future__ import annotations

import secrets
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.admin import merge_patch
from app.common.clock import Clock
from app.common.problems import ProblemException
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.expand import expand
from app.roles.scenarios.models import Scenario
from app.roles.scenarios.schemas import (
    AppliedSummary,
    DirectorSummary,
    ScenarioListItem,
    ScenarioOrigin,
    ScenarioSpec,
    ScenarioView,
)


def spec_dump(spec: ScenarioSpec) -> dict[str, Any]:
    """Параметры так, как их прислали: camelCase, без незаданных полей."""
    return spec.model_dump(mode="json", by_alias=True, exclude_unset=True)


async def preview(
    session: AsyncSession, spec: ScenarioSpec, clock: Clock, bank_bik: str | None = None
) -> dict[str, Any]:
    """Чтение занятых ИНН, без резервирования: preview не меняет ни одной таблицы.

    При переприменении исключаем собственный снимок. Гонку записей защищает уникальный
    индекс Scenario.inn в apply (T-127), предпросмотр ничего не обещает зарезервировать.
    """
    query = select(Scenario.inn, Scenario.expanded, Scenario.spec)
    if spec.code is not None:
        query = query.where(Scenario.code != spec.code)
    reserved: set[str] = set()
    for inn, expanded, stored_spec in (await session.execute(query)).all():
        if inn:
            reserved.add(inn)
        if expanded:
            for person in expanded.get("identity", {}).get("persons", []):
                reserved.add(person["inn"])
        stored_people = stored_spec.get("people") or {}
        for person in [stored_people.get("director")] + (stored_people.get("founders") or []):
            if person and person.get("inn"):
                reserved.add(person["inn"])
    try:
        settings = ScenarioSettings(bank_bik=bank_bik) if bank_bik is not None else None
        return expand(spec, clock.today(), reserved, settings=settings)
    except ValueError as exc:
        raise ProblemException(422, "VALIDATION_ERROR", str(exc)) from exc


def not_found(code: str) -> ProblemException:
    return ProblemException(404, "SCENARIO_NOT_FOUND", f"Сценарий {code} не найден")


def _new_code() -> str:
    return f"custom-{secrets.token_hex(2)}"


async def create(
    session: AsyncSession,
    spec: ScenarioSpec,
    clock: Clock,
    origin: ScenarioOrigin = ScenarioOrigin.CUSTOM,
    *,
    bank_bik: str | None = None,
) -> Scenario:
    code = spec.code or _new_code()
    while spec.code is None and await session.get(Scenario, code) is not None:
        code = _new_code()
    if await session.get(Scenario, code) is not None:
        raise ProblemException(409, "SCENARIO_EXISTS", f"Сценарий {code} уже есть")
    inn = spec.company.inn if spec.company else None
    if inn is not None and await session.scalar(select(Scenario.code).where(Scenario.inn == inn)):
        raise ProblemException(409, "SCENARIO_INN_EXISTS", "Сценарий с этим ИНН уже есть")
    snapshot = await preview(session, spec.model_copy(update={"code": code}), clock, bank_bik)
    now = clock.now()
    row = Scenario(
        code=code,
        title=spec.title,
        origin=origin.value,
        builtin_version=spec.builtin_version,
        modified=False,
        expected_outcome=spec.expected_outcome,
        expected_final_outcome=spec.expected_final_outcome,
        expected_reason_codes=list(spec.expected_reason_codes),
        inn=snapshot["identity"]["inn"],
        spec={**spec_dump(spec), "code": code},
        expanded=snapshot,
        status="PENDING",
        needs_reapply=True,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def get(session: AsyncSession, code: str) -> Scenario:
    row = await session.get(Scenario, code)
    if row is None:
        raise not_found(code)
    return row


async def list_scenarios(
    session: AsyncSession, origin: ScenarioOrigin | None
) -> list[ScenarioListItem]:
    query = select(Scenario).order_by(Scenario.origin, Scenario.code)
    if origin is not None:
        query = query.where(Scenario.origin == origin.value)
    rows = (await session.scalars(query)).all()
    return [
        ScenarioListItem(
            code=r.code,
            title=r.title,
            origin=ScenarioOrigin(r.origin),
            inn=r.inn,
            expected_outcome=r.expected_outcome,
            status=r.status,
            modified=r.modified,
        )
        for r in rows
    ]


def validate_spec(raw: dict[str, Any]) -> ScenarioSpec:
    try:
        return ScenarioSpec.model_validate(raw)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise ProblemException(
            422, "VALIDATION_ERROR", "Сценарий не прошёл проверку", errors=errors
        ) from exc


async def patch(
    session: AsyncSession,
    code: str,
    changes: dict[str, Any],
    clock: Clock,
    *,
    bank_bik: str | None = None,
) -> Scenario:
    """JSON Merge Patch параметров; компания будет пересоздана при применении (needs_reapply)."""
    row = await get(session, code)
    if "code" in changes and changes["code"] != code:
        raise ProblemException(422, "VALIDATION_ERROR", "Код сценария менять нельзя")
    spec = validate_spec(merge_patch(row.spec, changes))
    snapshot = await preview(session, spec, clock, bank_bik)
    row.spec = {**spec_dump(spec), "code": code}
    row.title = spec.title
    row.expected_outcome = spec.expected_outcome
    row.expected_final_outcome = spec.expected_final_outcome
    row.expected_reason_codes = list(spec.expected_reason_codes)
    row.inn = snapshot["identity"]["inn"]
    row.expanded = snapshot
    row.modified = row.modified or row.origin == ScenarioOrigin.BUILTIN.value
    row.needs_reapply = True
    row.updated_at = clock.now()
    await session.flush()
    return row


async def delete(session: AsyncSession, code: str) -> None:
    row = await get(session, code)
    if row.origin == ScenarioOrigin.BUILTIN.value:
        raise ProblemException(
            409, "BUILTIN_SCENARIO", "Встроенный сценарий удалить нельзя; вернуть исходник — reset"
        )
    await session.delete(row)
    await session.flush()


def view(row: Scenario) -> ScenarioView:
    spec = ScenarioSpec.model_validate(row.spec)
    expanded = row.expanded or {}
    identity = expanded.get("identity", {}) if isinstance(expanded, dict) else {}
    director = identity.get("director")
    return ScenarioView(
        code=row.code,
        title=row.title,
        origin=ScenarioOrigin(row.origin),
        builtin_version=row.builtin_version,
        modified=row.modified,
        status=row.status,
        inn=row.inn,
        ogrn=identity.get("ogrn"),
        short_name=identity.get("shortName"),
        director=DirectorSummary.model_validate(director) if director else None,
        expected_outcome=spec.expected_outcome,
        expected_final_outcome=spec.expected_final_outcome,
        expected_reason_codes=spec.expected_reason_codes,
        application=spec.application,
        users=spec.users,
        spec=row.spec,
        applied=AppliedSummary.model_validate(row.applied) if row.applied else None,
        expanded=row.expanded,
        last_error=row.last_error,
        applied_at=row.applied_at,
    )
