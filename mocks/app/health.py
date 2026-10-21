"""Здоровье (раздел 8.1): live — процесс жив; ready — база доступна и схема на последней ревизии."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", summary="Процесс жив", operation_id="healthLive")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Готов принимать запросы",
    operation_id="healthReady",
    responses={503: {"description": "База недоступна или миграции не применены"}},
)
async def ready(request: Request) -> JSONResponse:
    database = request.app.state.database
    if database is None:
        return JSONResponse({"status": "not_ready", "db": "not_configured"}, status_code=503)
    if not await database.is_ready():
        return JSONResponse({"status": "not_ready", "db": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})
