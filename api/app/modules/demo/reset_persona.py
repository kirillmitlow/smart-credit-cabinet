"""Сброс одной компании; частичный сбой закрывает её до успешного повтора (T-372)."""

import time
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import structlog
from sqlalchemy import text

from app.modules import audit, companies
from app.modules.integrations import scenarios
from app.shared import db, operations, resets
from app.shared.errors import AppError, not_found

log = structlog.get_logger(__name__)


class Step(StrEnum):
    MOCKS = "MOCKS"
    CACHE = "CACHE"
    DATABASE = "DATABASE"


TITLES = {Step.MOCKS: "моки", Step.CACHE: "кэш", Step.DATABASE: "база"}


@dataclass(frozen=True)
class Done:
    company_id: UUID
    generation: int
    duration_ms: int


def run(code: str) -> Done:
    started = time.perf_counter()
    with operations.hold(lambda: companies.for_scenario(code), exclusive=True) as scope:
        if scope is None:
            raise not_found()
        step = Step.DATABASE
        try:
            # Флаг коммитится до внешних действий и переживает падение процесса.
            with db.transaction() as session:
                inn, generation = companies.begin_reset(session, scope.company_id)
            step = Step.MOCKS
            view = scenarios.apply_one(
                code, idempotency_key=f"persona-reset:{scope.company_id}:{generation}"
            )
            identity = (view.get("expanded") or {}).get("identity") or {}
            if view.get("code") != code or (identity.get("inn") or view.get("inn")) != inn:
                raise RuntimeError("Сценарий больше не соответствует компании")
            with db.transaction() as session:
                resources = resets.collect_persona(session, scope.company_id, inn)
            # Если кэш недоступен, сохраняем старые id в БД для безопасного повтора.
            step = Step.CACHE
            resets.reset_persona_cache(resources)
            step = Step.DATABASE
            with db.transaction() as session:
                session.execute(text("SET LOCAL lock_timeout = '15s'"))
                modules = resets.reset_persona_rows(session, resources)
                restored = companies.apply_scenario(session, view)
                if restored is None or restored.id != scope.company_id:
                    raise RuntimeError("Не удалось восстановить исходную компанию")
                companies.finish_reset(session, scope.company_id)
                audit.record(
                    session,
                    "DEMO_PERSONA_RESET",
                    company_id=scope.company_id,
                    object_type="COMPANY",
                    object_id=str(scope.company_id),
                    details={"generation": generation, "modules": modules},
                )
        except Exception as exc:
            log.warning("persona_reset_failed", company_id=str(scope.company_id), step=step.value)
            raise AppError(
                502,
                "DEMO_RESET_FAILED",
                f"Сброс остановился на шаге «{TITLES[step]}». Повторите сброс компании.",
                errors=[{"step": step.value, "title": TITLES[step]}],
            ) from exc
    return Done(scope.company_id, generation, int((time.perf_counter() - started) * 1000))
