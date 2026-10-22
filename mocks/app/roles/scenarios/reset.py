"""Общий сброс моков (10.4, 8.4): wipe четырёх систем, chaos в OK, встроенные из кода, apply заново.

Вызывается только под locked_session: параллельный apply, patch или второй reset ждут своей
очереди. Шаги идемпотентны, поэтому повтор после сбоя доводит сброс: до wipe все строки
помечены незавершёнными, а успешный apply возвращает им APPLIED. Досинхронизация, смена
месяца и фоновые повторы применения (T-129) здесь не делаются.
"""

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import Clock
from app.common.idempotency import forget_replies
from app.common.problems import ProblemException
from app.roles.scenarios import service
from app.roles.scenarios.apply import apply
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.gateway import AdminGateway
from app.roles.scenarios.models import Scenario
from app.roles.scenarios.schemas import ResetMode, ResetView, ScenarioOrigin
from app.roles.scenarios.split import System

UNFINISHED = "Общий сброс ещё не завершён; повторите POST /scenarios/reset"


async def _call(
    gateway: AdminGateway, system: System, method: str, path: str, body: dict[str, Any] | None
) -> str | None:
    try:
        response = await gateway.admin(system, method, path, body)
    except httpx.HTTPError as exc:
        return f"{type(exc).__name__}: ответ системы не получен"
    if response.status_code not in (200, 204):
        return f"HTTP {response.status_code}: {response.text[:300]}"
    return None


async def _reset_mocks(gateway: AdminGateway) -> dict[System, str]:
    """chaos → OK и wipe у каждого мока. Недоступный мок не мешает очистить остальные."""
    errors: dict[System, str] = {}
    for system in System:
        for method, path, body in (
            ("PUT", "/chaos", {"mode": "OK"}),
            ("POST", "/wipe", None),
        ):
            error = await _call(gateway, system, method, path, body)
            if error:
                errors[system] = f"{method} /admin{path}: {error}"
                break
    return errors


async def reset(
    session: AsyncSession, gateway: AdminGateway, clock: Clock, bank_bik: str, mode: ResetMode
) -> ResetView:
    rows = list(await session.scalars(select(Scenario)))
    for row in rows:
        # Данные в моках сейчас исчезнут: до успешного apply строка не может быть APPLIED.
        row.status = "PENDING"
        row.needs_reapply = True
        row.applied = None
        row.last_error = UNFINISHED
        row.updated_at = clock.now()
    await session.commit()

    wipe_errors = await _reset_mocks(gateway)
    if wipe_errors:
        detail = "; ".join(f"{s.value}: {e}" for s, e in wipe_errors.items())
        raise ProblemException(502, "RESET_FAILED", f"Очистка моков не удалась: {detail}")

    deleted: list[str] = []
    if mode is ResetMode.BUILTIN_ONLY:
        for row in rows:
            if row.origin == ScenarioOrigin.CUSTOM.value:
                await forget_replies(session, {"code": {row.code}})
                await session.delete(row)
                deleted.append(row.code)
        await session.commit()

    failures: list[str] = []
    for spec in builtin_scenarios(clock.today(), bank_bik):
        existing = await session.get(Scenario, spec.code)
        try:
            if existing is None:
                await service.create(
                    session, spec, clock, ScenarioOrigin.BUILTIN, bank_bik=bank_bik
                )
            elif existing.origin != ScenarioOrigin.BUILTIN.value:
                raise ProblemException(
                    409, "SCENARIO_EXISTS", "код встроенного сценария занят пользовательским"
                )
            else:
                await service.restore_builtin(session, existing, spec, clock, bank_bik)
        except ProblemException as exc:
            failures.append(f"{spec.code}: {exc.detail or exc.code}")
    await session.commit()

    pending = await session.scalars(
        select(Scenario)
        .where(Scenario.status == "PENDING")
        .order_by(Scenario.origin, Scenario.code)
    )
    for row in list(pending):
        try:
            await apply(session, row, gateway, clock)
        except ProblemException as exc:
            failures.append(f"{row.code}: {exc.detail or exc.code}")
    if failures:
        raise ProblemException(
            502, "RESET_FAILED", "Сценарии применены не полностью: " + "; ".join(failures)
        )
    return ResetView(
        mode=mode,
        chaos={system.summary_key: "OK" for system in System},
        deleted=deleted,
        scenarios=await service.list_scenarios(session, None),
    )
