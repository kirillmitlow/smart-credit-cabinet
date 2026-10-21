"""Здоровье api (T-209, 50-10): live — процесс жив; ready — Postgres, Redis и схема на head;
deps — внешние системы, предохранители и свежесть сигнала воркера. Моки в ready не входят:
падение БКИ не должно выключать кабинет.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.shared import db
from app.shared.cache import WORKER_HEARTBEAT_KEY, get_redis
from app.shared.clock import system_now
from app.shared.errors import problem

router = APIRouter(prefix="/health", tags=["health"])

WORKER_STALE_SECONDS = 60
EXTERNAL_SYSTEMS = ("registry", "tax", "bki", "bank_core")


@router.get("/live", operation_id="healthLive", summary="Процесс жив")
async def live() -> dict[str, str]:
    return {"status": "ok"}


def _check_postgres() -> bool:
    try:
        return db.schema_is_current(db.get_database().engine)
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False


@router.get(
    "/ready",
    operation_id="healthReady",
    summary="Готов принимать запросы",
    responses={503: {"description": "Postgres, Redis или схема БД не готовы"}},
)
async def ready(request: Request) -> JSONResponse:
    checks = {
        "postgres": await run_in_threadpool(_check_postgres),
        "redis": await run_in_threadpool(_check_redis),
    }
    if all(checks.values()):
        return JSONResponse({"status": "ok", "checks": checks})
    failed = ", ".join(name for name, ok in checks.items() if not ok)
    response = problem(request, 503, "NOT_READY", detail=f"Не готовы: {failed}")
    return response


def _worker_age_seconds() -> int | None:
    try:
        raw = get_redis().get(WORKER_HEARTBEAT_KEY)
    except Exception:
        return None
    if not raw:
        return None
    return int((system_now() - datetime.fromisoformat(str(raw))).total_seconds())


@router.get("/deps", operation_id="healthDeps", summary="Внешние системы и воркер")
async def deps() -> dict[str, object]:
    age = await run_in_threadpool(_worker_age_seconds)
    return {
        # Состояние предохранителей появится с T-231; до этого честно «неизвестно»
        "systems": {name: {"circuit": "UNKNOWN"} for name in EXTERNAL_SYSTEMS},
        "worker": {
            "lastHeartbeatAgeSeconds": age,
            "stale": age is None or age > WORKER_STALE_SECONDS,
        },
    }
