"""Приложение FastAPI (50-01). Запуск: `uvicorn app.main:app` или `python -m app`."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app import health
from app.modules import companies
from app.shared import clock, db
from app.shared.errors import install_error_handlers
from app.shared.logs import configure_logging
from app.shared.request_context import RequestContextMiddleware
from app.shared.settings import Settings, get_settings

log = structlog.get_logger("app.main")
MIGRATION_RETRY_SECONDS = 2.0


def _sync_companies() -> None:
    with db.transaction() as session:
        companies.sync_all(session)


async def _migrate_until_done(database: db.Database) -> None:
    """База может подняться позже api: повторяем, /health/ready до этого отвечает 503.
    Затем подтягиваем демо-учётки из сценариев; сбой не критичен — вход досинхронизирует сам."""
    while True:
        try:
            await run_in_threadpool(db.migrate, database.engine)
            log.info("migrations_applied")
            break
        except Exception as exc:
            log.warning("database_not_ready", error=str(exc))
            await asyncio.sleep(MIGRATION_RETRY_SECONDS)
    try:
        await run_in_threadpool(_sync_companies)
    except Exception as exc:
        log.warning("companies_sync_failed", error=str(exc))


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_migrate_until_done(db.get_database()))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        db.get_database().dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    clock.configure(settings.app_today)
    db.configure(settings.sqlalchemy_url)
    app = FastAPI(
        title="Умный кредитный кабинет — API",
        description="Прототип цифрового кредитного конвейера для малого бизнеса. Данные синтетические.",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    app.include_router(companies.login_router)
    return app


def build() -> FastAPI:
    settings = get_settings()
    configure_logging("api", settings.log_level)
    return create_app(settings)
