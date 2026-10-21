"""Завершить откат, когда недоступный мок вернулся, в том числе после аварии процесса."""

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import Clock
from app.common.db import Database
from app.common.idempotency import forget_replies
from app.roles.scenarios.apply import clear_all
from app.roles.scenarios.gateway import AdminGateway
from app.roles.scenarios.locking import mutation_session
from app.roles.scenarios.models import Scenario, ScenarioApplication
from app.roles.scenarios.split import System
from app.settings import Settings

log = logging.getLogger("app.scenarios.recovery")


async def _clean(session: AsyncSession, code: str) -> bool:
    rows = await session.scalars(
        select(ScenarioApplication)
        .where(ScenarioApplication.scenario_code == code)
        .order_by(ScenarioApplication.id.desc())
    )
    latest: dict[str, ScenarioApplication] = {}
    for row in rows:
        latest.setdefault(row.system, row)
    return len(latest) == len(System) and all(
        row.action == "DELETE" and row.http_status == 200 and row.error is None
        for row in latest.values()
    )


async def recover_once(database: Database, gateway: AdminGateway, clock: Clock) -> None:
    async with mutation_session(database, wait=False) as session:
        if session is None:
            return
        rows = await session.scalars(
            select(Scenario)
            .where(Scenario.status.in_(["PENDING", "FAILED"]))
            .order_by(Scenario.updated_at, Scenario.code)
        )
        for row in rows:
            clean = await _clean(session, row.code)
            deleting = row.status == "FAILED" and not row.needs_reapply
            if clean and row.status == "FAILED" and not deleting:
                continue
            if not clean or deleting:
                errors = await clear_all(session, row, gateway, clock)
                if any(errors.values()):
                    row.status = "FAILED"
                    row.last_error = "Откат ожидает: " + ", ".join(
                        s.value for s, error in errors.items() if error
                    )
                    row.updated_at = clock.now()
                    await session.commit()
                    return
            if deleting:
                await forget_replies(session, {"code": {row.code}})
                await session.delete(row)
            else:
                row.status = "FAILED"
                row.needs_reapply = True
                row.applied = {system.summary_key: "SKIPPED" for system in System}
                row.last_error = "Применение прервано; откат завершён. Повторите apply"
                row.updated_at = clock.now()
            await session.commit()
            return  # одна компания за проход; не держим блокировку над всей очередью


async def recover_forever(database: Database, settings: Settings, clock: Clock) -> None:
    async with httpx.AsyncClient(timeout=settings.scenario_request_timeout_seconds) as client:
        gateway = AdminGateway(client, settings)
        while True:
            try:
                await recover_once(database, gateway, clock)
            except Exception:
                log.exception("Не удалось завершить откат сценария; повторим")
            await asyncio.sleep(2)
