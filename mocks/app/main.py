"""Сборка приложения мока: одна кодовая база, роль по MOCK_ROLE (разделы 1, 3.3)."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI

from app import chaos, health
from app.common.clock import Clock
from app.common.db import Database
from app.common.idempotency import purge_forever
from app.common.middleware import RequestContextMiddleware
from app.common.problems import install_problem_handlers
from app.settings import ROLE_TITLE, Role, Settings


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    database: Database | None = app.state.database
    migrations: asyncio.Task[None] | None = None
    if database is not None:

        async def maintain(db: Database) -> None:
            # Не блокируем старт: /health/live отвечает сразу, ready — после миграций
            await db.migrate_until_done()
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(purge_forever(db, app.state.clock))
                if db.role == Role.SCENARIOS:
                    from app.roles.scenarios.recovery import recover_forever

                    tasks.create_task(recover_forever(db, app.state.settings, app.state.clock))

        migrations = asyncio.create_task(maintain(database))
    try:
        yield
    finally:
        if migrations is not None:
            migrations.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await migrations
        if database is not None:
            await database.dispose()


def _role_routers(role: Role) -> list[APIRouter]:
    """Роль подключает себя сама: `roles/<роль>/router.py` с `router` (бизнес-API) и
    `admin_router` (админ-API, обычно make_admin_router(handler)). main.py при этом не меняется."""
    try:
        module = importlib.import_module(f"app.roles.{role.value}.router")
    except ModuleNotFoundError as exc:
        if exc.name == f"app.roles.{role.value}.router":
            return []  # роль ещё не реализована
        raise
    return [r for name in ("router", "admin_router") if (r := getattr(module, name, None))]


def create_app(settings: Settings) -> FastAPI:
    role = settings.mock_role
    app = FastAPI(
        title=f"{settings.service_name} — {ROLE_TITLE[role]}",
        description=(
            "Имитация внешней системы для прототипа «Умный кредитный кабинет». "
            "Все данные синтетические (`meta.simulated: true`). Контракт: docs/specs/mocks.md."
        ),
        version="1.0.0",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.clock = Clock(settings.app_today)
    app.state.database = Database(settings.database_url, role) if settings.database_url else None

    app.state.chaos = chaos.ChaosState(app.state.clock)

    install_problem_handlers(app)
    # Последний добавленный — внешний: request-id и лог → chaos → маршрут (порядок 8.2)
    app.add_middleware(chaos.ChaosMiddleware)
    app.add_middleware(RequestContextMiddleware, latency_ms=settings.latency_range_ms)
    app.include_router(health.router)
    app.include_router(chaos.router)
    for router in _role_routers(role):
        app.include_router(router)
    return app
