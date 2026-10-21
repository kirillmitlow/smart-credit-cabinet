"""Ключи доступа (раздел 2.3): свой ключ у каждой системы и общий админ-ключ.

Нет ключа или он не опознан — 401. Ключ опознан, но не для этого раздела
(админ-ключ на бизнес-эндпоинте или ключ потребителя на /admin/*) — 403.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from app.common.problems import ProblemException
from app.settings import Settings

api_key_header = APIKeyHeader(
    name="X-Api-Key",
    scheme_name="ApiKeyAuth",
    description="Ключ потребителя бизнес-API (у каждой системы свой)",
    auto_error=False,
)
admin_key_header = APIKeyHeader(
    name="X-Admin-Key",
    scheme_name="AdminKeyAuth",
    description="Админ-ключ для /admin/* и сервиса сценариев",
    auto_error=False,
)


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _consumer(settings: Settings, key: str) -> str | None:
    for known, consumer in settings.api_keys.items():
        if _same(known, key):
            return consumer
    return None


def _unauthorized() -> ProblemException:
    return ProblemException(401, "UNAUTHORIZED", "Нет ключа доступа или он не опознан")


def _forbidden(detail: str) -> ProblemException:
    return ProblemException(403, "FORBIDDEN", detail)


def require_api_key(
    request: Request,
    api_key: Annotated[str | None, Depends(api_key_header)],
    admin_key: Annotated[str | None, Depends(admin_key_header)],
) -> str:
    """Бизнес-эндпоинт: вернуть имя потребителя по его ключу."""
    settings = _settings(request)
    if api_key:
        if _same(api_key, settings.mock_admin_key):
            raise _forbidden("Админ-ключ не даёт доступа к бизнес-API")
        consumer = _consumer(settings, api_key)
        if consumer is None:
            raise _unauthorized()
        return consumer
    if admin_key and _same(admin_key, settings.mock_admin_key):
        raise _forbidden("Админ-ключ не даёт доступа к бизнес-API")
    raise _unauthorized()


def require_admin(
    request: Request,
    admin_key: Annotated[str | None, Depends(admin_key_header)],
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> None:
    """Админ-API и весь mock-scenarios."""
    settings = _settings(request)
    if admin_key:
        if _same(admin_key, settings.mock_admin_key):
            return
        if _consumer(settings, admin_key) is not None:
            raise _forbidden("Ключ потребителя не даёт доступа к админ-API")
        raise _unauthorized()
    if api_key and _consumer(settings, api_key) is not None:
        raise _forbidden("Ключ потребителя не даёт доступа к админ-API")
    raise _unauthorized()
