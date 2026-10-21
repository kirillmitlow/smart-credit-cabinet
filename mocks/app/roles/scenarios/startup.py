"""Первое наполнение до ready (T-128, 10.6): существующие данные не стираются.

Версии, смена месяца, периодический sync и повторы применения — T-129.
В отличие от полного apply, восстановление пустой роли не трогает остальные.
"""

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import Clock
from app.common.db import Database
from app.common.problems import ProblemException
from app.roles.scenarios import service
from app.roles.scenarios.apply import apply, send_logged
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.gateway import AdminGateway
from app.roles.scenarios.locking import locked_session
from app.roles.scenarios.models import Scenario
from app.roles.scenarios.schemas import ScenarioOrigin
from app.roles.scenarios.split import System, split

log = logging.getLogger("app.scenarios.startup")


async def inventory(gateway: AdminGateway) -> dict[System, set[str] | None]:
    result: dict[System, set[str] | None] = {}
    for system, url in gateway.urls.items():
        try:
            response = await gateway.client.get(
                f"{url.rstrip('/')}/admin/scenarios", headers={"X-Admin-Key": gateway.admin_key}
            )
            response.raise_for_status()
            result[system] = {entry["scenarioCode"] for entry in response.json()}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            result[system] = None  # неизвестно, есть ли данные; PUT мог бы затереть RUNTIME
    return result


async def restore_missing(
    session: AsyncSession,
    row: Scenario,
    gateway: AdminGateway,
    clock: Clock,
    known: dict[System, set[str] | None],
) -> None:
    if row.expanded is None:
        return  # старые неподготовленные записи: T-129, не выдумываем новый снимок
    summary = dict(row.applied or {})
    errors = []
    changed = False
    for system, subjects in split(row.expanded).items():
        if not subjects:
            continue
        codes = known[system]
        if codes is not None and row.code in codes:
            continue
        changed = True
        if codes is None:
            summary[system.summary_key] = "FAILED"
            errors.append(f"{system.value}: инвентаризация недоступна, данные не менялись")
            continue
        failed = None
        for subject in subjects:
            failed = await send_logged(
                session, row, gateway, clock, system, "PUT", subject.inn, subject.body
            )
            if failed:
                break
        if failed:
            # Стираем только новую неполную роль; существующие роли и RUNTIME сохраняем.
            cleanup = await send_logged(session, row, gateway, clock, system, "DELETE")
            summary[system.summary_key] = "FAILED"
            errors.append(
                f"{system.value}: {failed}" + ("; откат не подтверждён" if cleanup else "")
            )
            known[system] = None
        else:
            summary[system.summary_key] = "OK"
            codes.add(row.code)
    if changed:
        row.applied = summary
        row.status = "PARTIAL" if errors else "APPLIED"
        row.last_error = "; ".join(errors) if errors else None
        row.updated_at = clock.now()
        await session.commit()


async def initialize(
    database: Database, gateway: AdminGateway, clock: Clock, bank_bik: str
) -> None:
    async with locked_session(database) as session:
        known = await inventory(gateway)
        handled = set()
        for spec in builtin_scenarios(clock.today(), bank_bik):
            row = await session.get(Scenario, spec.code)
            if row is None:
                row = await service.create(
                    session, spec, clock, ScenarioOrigin.BUILTIN, bank_bik=bank_bik
                )
            elif row.origin != "BUILTIN":
                log.error("Код встроенного сценария занят пользовательским; запись сохранена")
                continue
            elif row.status in ("APPLIED", "PARTIAL"):
                continue
            handled.add(row.code)
            unavailable = [system for system, codes in known.items() if codes is None]
            if unavailable:
                # Один остановленный мок не даёт N одинаковых таймаутов для N персон.
                row.status = "FAILED"
                row.needs_reapply = True
                row.last_error = "Первое применение отложено: " + ", ".join(
                    s.value for s in unavailable
                )
                row.applied = {
                    s.summary_key: "FAILED" if s in unavailable else "SKIPPED" for s in System
                }
                await session.commit()
                continue
            try:
                await apply(session, row, gateway, clock)
            except ProblemException:
                for system in System:
                    if (row.applied or {}).get(system.summary_key) == "FAILED":
                        known[system] = None
            else:
                for system, subjects in split(row.expanded or {}).items():
                    codes = known[system]
                    if subjects and codes is not None:
                        codes.add(row.code)
        rows = await session.scalars(select(Scenario).order_by(Scenario.code))
        for row in rows:
            if row.code not in handled and row.status in ("APPLIED", "PARTIAL"):
                await restore_missing(session, row, gateway, clock, known)
