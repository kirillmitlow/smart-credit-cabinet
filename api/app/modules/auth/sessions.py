"""Сессии в Redis/Valkey (T-210, 50-09): две независимые cookie `sid_client` и `sid_bank`.

Идентификатор — 256 бит случайности; в Redis лежит только JSON Principal. Простой продлевает
срок, абсолютный максимум ограничивает его сверху. Выход удаляет сессию на сервере сразу.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict
from typing import Any
from uuid import UUID

import redis

from app.modules.auth.principal import Membership, Principal, Zone
from app.shared.cache import get_redis
from app.shared.errors import AppError
from app.shared.settings import get_settings

COOKIE = {Zone.CLIENT: "sid_client", Zone.BANK: "sid_bank"}
_PREFIX = "scc:session:"


def _key(zone: Zone, sid: str) -> str:
    return f"{_PREFIX}{zone.value}:{sid}"


def store_unavailable(exc: Exception) -> AppError:
    return AppError(
        503, "SESSION_STORE_UNAVAILABLE", f"Хранилище сессий недоступно: {type(exc).__name__}"
    )


def _dump(principal: Principal, created: float) -> str:
    data: dict[str, Any] = asdict(principal)
    data.pop("session_id")
    data["memberships"] = [
        {"company_id": str(m.company_id), "role": m.role, "permissions": sorted(m.permissions)}
        for m in principal.memberships
    ]
    data["user_id"] = str(principal.user_id)
    data["active_company_id"] = (
        str(principal.active_company_id) if principal.active_company_id else None
    )
    data["zone"] = principal.zone.value
    data["created"] = created
    return json.dumps(data)


def _load(raw: str, sid: str) -> tuple[Principal, float]:
    data = json.loads(raw)
    created = float(data.pop("created"))
    memberships = tuple(
        Membership(UUID(m["company_id"]), m["role"], frozenset(m["permissions"]))
        for m in data.pop("memberships")
    )
    active = data.pop("active_company_id")
    principal = Principal(
        user_id=UUID(data.pop("user_id")),
        zone=Zone(data.pop("zone")),
        memberships=memberships,
        active_company_id=UUID(active) if active else None,
        session_id=sid,
        **data,
    )
    return principal, created


def _ttl(created: float) -> int:
    settings = get_settings()
    idle = settings.session_idle_minutes * 60
    absolute_left = int(created + settings.session_absolute_hours * 3600 - time.time())
    return max(0, min(idle, absolute_left))


def create(principal: Principal, *, replace_sid: str | None = None) -> str:
    """Новая сессия с новым идентификатором (смена id при входе); старая удаляется."""
    sid = secrets.token_urlsafe(32)
    client = get_redis()
    try:
        if replace_sid:
            client.delete(_key(principal.zone, replace_sid))
        created = time.time()
        client.set(_key(principal.zone, sid), _dump(principal, created), ex=_ttl(created))
    except redis.RedisError as exc:
        raise store_unavailable(exc) from exc
    return sid


def load(zone: Zone, sid: str) -> Principal | None:
    client = get_redis()
    try:
        raw = client.get(_key(zone, sid))
        if raw is None:
            return None
        principal, created = _load(str(raw), sid)
        ttl = _ttl(created)
        if ttl <= 0:
            client.delete(_key(zone, sid))
            return None
        client.expire(_key(zone, sid), ttl)  # простой продлевает, но не дальше абсолюта
    except redis.RedisError as exc:
        raise store_unavailable(exc) from exc
    return principal


def update(principal: Principal) -> None:
    client = get_redis()
    key = _key(principal.zone, principal.session_id)
    try:
        raw = client.get(key)
        if raw is None:
            raise AppError(401, "UNAUTHENTICATED", "Сессия истекла")
        _, created = _load(str(raw), principal.session_id)
        client.set(key, _dump(principal, created), ex=_ttl(created))
    except redis.RedisError as exc:
        raise store_unavailable(exc) from exc


def destroy(zone: Zone, sid: str) -> None:
    try:
        get_redis().delete(_key(zone, sid))
    except redis.RedisError as exc:
        raise store_unavailable(exc) from exc
