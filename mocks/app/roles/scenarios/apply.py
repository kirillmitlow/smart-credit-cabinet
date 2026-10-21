"""Применение и компенсация (10.4). Намерение записано ДО HTTP, результат — после.

Потерянный ответ не доказывает отсутствие записи. При сбое чистим все системы, включая
не ответившую; незавершённые DELETE повторяет recovery после возвращения мока.
Вызывается только под mutation_session, вместе с проверкой и резервированием ИНН.
"""

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import Clock
from app.common.idempotency import forget_replies
from app.common.problems import ProblemException
from app.roles.scenarios.gateway import AdminGateway
from app.roles.scenarios.models import Scenario, ScenarioApplication
from app.roles.scenarios.split import System, split


async def send_logged(
    session: AsyncSession,
    row: Scenario,
    gateway: AdminGateway,
    clock: Clock,
    system: System,
    action: str,
    inn: str | None = None,
    body: dict[str, Any] | None = None,
) -> str | None:
    entry = ScenarioApplication(
        scenario_code=row.code, system=system.value, action=action, at=clock.now()
    )
    session.add(entry)
    await session.commit()
    return await _finish(session, entry, gateway, inn, body)


async def _finish(
    session: AsyncSession,
    entry: ScenarioApplication,
    gateway: AdminGateway,
    inn: str | None = None,
    body: dict[str, Any] | None = None,
) -> str | None:
    try:
        response = await gateway.send(
            System(entry.system), entry.action, entry.scenario_code, inn, body
        )
    except httpx.HTTPError as exc:
        entry.error = f"{type(exc).__name__}: ответ системы не получен"
    else:
        entry.http_status = response.status_code
        allowed = (200, 201) if entry.action == "PUT" else (200,)
        if response.status_code not in allowed:
            entry.error = f"HTTP {response.status_code}: {response.text[:500]}"
    await session.commit()
    return entry.error


async def clear_all(
    session: AsyncSession, row: Scenario, gateway: AdminGateway, clock: Clock
) -> dict[System, str | None]:
    # Не прерываем откат, даже если один из моков по-прежнему недоступен.
    entries = {
        system: ScenarioApplication(
            scenario_code=row.code, system=system.value, action="DELETE", at=clock.now()
        )
        for system in System
    }
    session.add_all(entries.values())
    # Статус PENDING/намерение удалить и все четыре DELETE фиксируются атомарно:
    # после аварии прошлый успешный DELETE нельзя принять за очистку новой попытки.
    await session.commit()
    errors = {}
    for system, entry in entries.items():
        errors[system] = await _finish(session, entry, gateway)
    return errors


def failure_detail(system: System, error: str, cleanup: dict[System, str | None]) -> str:
    pending = ", ".join(s.value for s, e in cleanup.items() if e)
    suffix = f"; откат ожидает восстановления: {pending}" if pending else "; данные удалены"
    return f"{system.value}: {error}{suffix}"


async def apply(session: AsyncSession, row: Scenario, gateway: AdminGateway, clock: Clock) -> None:
    if row.expanded is None:
        raise ProblemException(422, "VALIDATION_ERROR", "У сценария ещё нет развёрнутого снимка")
    targets = split(row.expanded)
    row.status = "PENDING"
    row.needs_reapply = True
    row.last_error = None
    row.applied = None
    row.updated_at = clock.now()
    # Повторное применение очищает также RUNTIME и людей, удалённых из нового spec.
    cleared = await clear_all(session, row, gateway, clock)
    failed = next(((s, e) for s, e in cleared.items() if e), None)
    summary: dict[str, str] = {}
    if failed is None:
        for system, subjects in targets.items():
            summary[system.summary_key] = "SKIPPED"
            for subject in subjects:
                error = await send_logged(
                    session, row, gateway, clock, system, "PUT", subject.inn, subject.body
                )
                if error:
                    failed = (system, error)
                    break
                summary[system.summary_key] = "OK"
            if failed:
                break
    if failed:
        cleanup = await clear_all(session, row, gateway, clock)
        row.status = "FAILED"
        row.applied = {
            s.summary_key: "FAILED" if cleanup[s] or s == failed[0] else "SKIPPED" for s in System
        }
        row.last_error = failure_detail(*failed, cleanup)
        row.updated_at = clock.now()
        await session.commit()
        raise ProblemException(502, "APPLY_FAILED", row.last_error)

    row.status = "APPLIED"
    row.applied = summary
    row.needs_reapply = False
    row.applied_at = row.updated_at = clock.now()
    row.applied_month = clock.today().replace(day=1)
    await session.commit()


async def delete(session: AsyncSession, row: Scenario, gateway: AdminGateway, clock: Clock) -> None:
    if row.origin == "BUILTIN":
        raise ProblemException(409, "BUILTIN_SCENARIO", "Встроенный сценарий удалить нельзя")
    # FAILED + needs_reapply=false — долговечное намерение удалить custom-сценарий.
    # При аварии recovery сначала очистит оставшиеся моки, затем удалит саму строку.
    row.status = "FAILED"
    row.needs_reapply = False
    row.last_error = "Удаление данных сценария ещё не завершено"
    row.updated_at = clock.now()
    cleanup = await clear_all(session, row, gateway, clock)
    failed = next(((s, e) for s, e in cleanup.items() if e), None)
    if failed:
        row.last_error = failure_detail(*failed, cleanup)
        await session.commit()
        raise ProblemException(502, "APPLY_FAILED", row.last_error)
    await forget_replies(session, {"code": {row.code}})
    await session.delete(row)
    await session.commit()
