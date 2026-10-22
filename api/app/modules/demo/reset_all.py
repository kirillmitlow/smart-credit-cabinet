"""Единый сброс стенда (T-371, Q-038): моки → база → сессии и кэш → запись в аудит.

Каждый шаг безопасно повторять: при ошибке шаг называется в ответе, а повтор проходит всё заново.
Модули `api` не импортируются: свои таблицы и ключи кэша они зарегистрировали в `shared.resets`.
Параллельный прогон и двойное нажатие отсекает advisory lock Postgres (работает и между процессами).
"""

from __future__ import annotations

import time
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy import text

from app.modules import audit
from app.modules.integrations import scenarios
from app.shared import cache, clock, db, outbox, resets
from app.shared.errors import AppError

log = structlog.get_logger("app.demo.reset")

RESET_LOCK = zlib.crc32(b"scc-demo-reset")
DB_LOCK_TIMEOUT = "15s"  # чужая долгая транзакция не должна подвесить сброс навсегда
AUDIT_ACTION = "DEMO_RESET"
# Режим сценариев: пользовательские компании жюри остаются и применяются заново (10.4)
SCENARIOS_MODE = "KEEP_CUSTOM"


class ResetStep(StrEnum):
    MOCKS = "MOCKS"
    DATABASE = "DATABASE"
    SESSIONS = "SESSIONS"


# Названия шагов для человека: «Сброс остановился на шаге «моки»» (60-05)
TITLES = {ResetStep.MOCKS: "моки", ResetStep.DATABASE: "база", ResetStep.SESSIONS: "сессии"}


@dataclass(frozen=True, slots=True)
class StepDone:
    step: ResetStep
    summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ResetDone:
    steps: list[StepDone]
    duration_ms: int


@contextmanager
def exclusive() -> Iterator[None]:
    """Один сброс за раз. Блокировка сессии Postgres держится на отдельном соединении."""
    with db.get_database().engine.connect() as conn:
        got = conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": RESET_LOCK})
        conn.commit()
        if not got:
            raise AppError(
                409, "DEMO_RESET_IN_PROGRESS", "Сброс уже выполняется, дождитесь его окончания"
            )
        try:
            yield
        finally:
            try:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": RESET_LOCK})
                conn.commit()
            except BaseException:
                conn.invalidate()  # закрытое соединение отпускает блокировку само
                raise


def failed(step: ResetStep, exc: Exception) -> AppError:
    title = TITLES[step]
    reason = f"{type(exc).__name__}: {exc}"[:500]
    return AppError(
        502,
        "DEMO_RESET_FAILED",
        f"Сброс остановился на шаге «{title}». Повторите. Причина: {reason}",
        errors=[{"step": step.value, "title": title, "msg": reason}],
    )


def _reset_mocks() -> dict[str, Any]:
    # Сначала гасим доставку из outbox: иначе сообщение «в пути» долетит в мок после очистки
    quiet = outbox.quiesce()
    if quiet.in_flight:
        log.warning("demo_reset_outbox_in_flight", in_flight=quiet.in_flight)
    result = scenarios.reset_all(SCENARIOS_MODE)
    return {
        "scenarios": len(result.get("scenarios") or []),
        "outboxDropped": quiet.dropped,
        "outboxInFlight": quiet.in_flight,
    }


def _reset_database() -> dict[str, Any]:
    with db.transaction() as session:
        session.execute(text(f"SET LOCAL lock_timeout = '{DB_LOCK_TIMEOUT}'"))
        modules = resets.run_all_resets(session)
    # Компании и учётки подтягиваем отдельной транзакцией: она ходит в сервис сценариев по сети
    with db.transaction() as session:
        after = resets.run_after_resets(session)
    return {"modules": modules, "after": after}


def _reset_sessions() -> dict[str, Any]:
    return {"keysDeleted": cache.delete_prefixes(resets.cache_prefixes())}


def _write_audit(done: list[StepDone]) -> None:
    with db.transaction() as session:
        audit.record(
            session,
            AUDIT_ACTION,
            object_type="DEMO",
            details={"steps": [s.step.value for s in done]},
        )


def run() -> ResetDone:
    started = time.perf_counter()
    plan: list[tuple[ResetStep, Callable[[], dict[str, Any]]]] = [
        (ResetStep.MOCKS, _reset_mocks),
        (ResetStep.DATABASE, _reset_database),
        (ResetStep.SESSIONS, _reset_sessions),
    ]
    with exclusive():
        done: list[StepDone] = []
        for step, action in plan:
            try:
                done.append(StepDone(step, action()))
            except Exception as exc:
                log.warning("demo_reset_failed", step=step.value, error=str(exc))
                raise failed(step, exc) from exc
            log.info("demo_reset_step_done", step=step.value)
        try:
            _write_audit(done)
        except Exception as exc:
            log.warning("demo_reset_failed", step=ResetStep.DATABASE.value, error=str(exc))
            raise failed(ResetStep.DATABASE, exc) from exc
    log.info("demo_reset_done", at=clock.system_now().isoformat())
    return ResetDone(done, int((time.perf_counter() - started) * 1000))
