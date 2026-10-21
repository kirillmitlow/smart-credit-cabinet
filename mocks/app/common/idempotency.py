"""Идемпотентность POST по заголовку Idempotency-Key (раздел 2.7 спецификации).

Ключ записывается до обработчика атомарно (уникальный индекс + INSERT … ON CONFLICT): параллельный
повтор видит «в работе» и получает 409 IDEMPOTENCY_IN_PROGRESS, а не дубль или 500. Сохраняются
только ответы 2xx; после ошибки ключ освобождается. Порядок в запросе: chaos → ключ API →
идемпотентность → обработчик, поэтому в эндпоинте зависимость ставится после require_api_key.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import Depends, Header, Request
from fastapi.responses import Response
from sqlalchemy.dialects.postgresql import insert

from app.common.clock import Clock
from app.common.db import Database
from app.common.problems import ProblemException

log = logging.getLogger("app.idempotency")

KEY_TTL = timedelta(hours=24)
ABANDONED_AFTER = timedelta(seconds=60)
PURGE_EVERY_SECONDS = 600
REPLAYED_HEADER = "Idempotent-Replayed"

metadata = sa.MetaData()


def _columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),  # IN_PROGRESS | DONE
        sa.Column("claim_token", sa.String(36), nullable=False),
        sa.Column("status_code", sa.Integer),
        sa.Column("response_body", sa.LargeBinary),
        sa.Column("media_type", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    ]


_UNIQUE = "uq_idempotency_endpoint_key"

idempotency_keys = sa.Table(
    "idempotency_keys",
    metadata,
    *_columns(),
    sa.UniqueConstraint("endpoint", "key", name=_UNIQUE),
)


def create_table_op() -> None:
    """Для миграций ролей: одна и та же таблица в базе каждой роли."""
    from alembic import op

    op.create_table(
        "idempotency_keys",
        *_columns(),
        sa.UniqueConstraint("endpoint", "key", name=_UNIQUE),
    )
    op.create_index("ix_idempotency_expires_at", "idempotency_keys", ["expires_at"])


def drop_table_op() -> None:
    from alembic import op

    op.drop_index("ix_idempotency_expires_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")


def canonical_hash(raw_body: bytes) -> str:
    """Хеш тела: JSON приводится к канонической форме, порядок полей не важен."""
    try:
        parsed = json.loads(raw_body or b"null")
        canonical = json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    except ValueError:
        canonical = raw_body
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class _Claim:
    token: str


@dataclass(frozen=True)
class _Replay:
    status_code: int
    body: bytes
    media_type: str | None


class Idempotency:
    """Состояние одного запроса; `run(handler)` выполняет обработчик не больше одного раза."""

    def __init__(
        self, database: Database, clock: Clock, endpoint: str, key: str | None, request_hash: str
    ) -> None:
        self._db = database
        self._clock = clock
        self.endpoint = endpoint
        self.key = key
        self.request_hash = request_hash

    async def run(self, handler: Callable[[], Awaitable[Response]]) -> Response:
        if self.key is None:
            return await handler()
        outcome = await self._claim()
        if isinstance(outcome, _Replay):
            return Response(
                outcome.body,
                status_code=outcome.status_code,
                media_type=outcome.media_type,
                headers={REPLAYED_HEADER: "true"},
            )
        try:
            response = await handler()
        except BaseException:
            await self._release(outcome.token)
            raise
        if 200 <= response.status_code < 300:
            await self._store(outcome.token, response)
        else:
            await self._release(outcome.token)
        return response

    async def _claim(self) -> _Claim | _Replay:
        now = self._clock.now()
        token = str(uuid.uuid4())
        fresh = {
            "request_hash": self.request_hash,
            "state": "IN_PROGRESS",
            "claim_token": token,
            "status_code": None,
            "response_body": None,
            "media_type": None,
            "created_at": now,
            "claimed_at": now,
            "expires_at": now + KEY_TTL,
        }
        t = idempotency_keys
        async with self._db.engine.begin() as conn:
            inserted = await conn.scalar(
                insert(t)
                .values(endpoint=self.endpoint, key=self.key, **fresh)
                .on_conflict_do_nothing(constraint=_UNIQUE)
                .returning(t.c.id)
            )
            if inserted is not None:
                return _Claim(token)

            row = (
                await conn.execute(
                    sa.select(t)
                    .where(t.c.endpoint == self.endpoint, t.c.key == self.key)
                    .with_for_update()
                )
            ).one()
            where = (t.c.id == row.id,)
            if row.expires_at <= now:  # срок жизни 24 ч истёк — ключ снова свободен
                await conn.execute(sa.update(t).where(*where).values(**fresh))
                return _Claim(token)
            if row.request_hash != self.request_hash:
                raise ProblemException(
                    409, "IDEMPOTENCY_KEY_REUSED", "Ключ уже использован с другим телом запроса"
                )
            if row.state == "DONE":
                return _Replay(row.status_code, row.response_body, row.media_type)
            if now - row.claimed_at > ABANDONED_AFTER:  # обработчик упал — выполняем заново
                await conn.execute(
                    sa.update(t).where(*where).values(claim_token=token, claimed_at=now)
                )
                return _Claim(token)
        raise ProblemException(
            409,
            "IDEMPOTENCY_IN_PROGRESS",
            "Запрос с этим ключом ещё выполняется, повторите позже",
            headers={"Retry-After": "1"},
        )

    async def _store(self, token: str, response: Response) -> None:
        t = idempotency_keys
        async with self._db.engine.begin() as conn:
            await conn.execute(
                sa.update(t)
                .where(t.c.endpoint == self.endpoint, t.c.key == self.key, t.c.claim_token == token)
                .values(
                    state="DONE",
                    status_code=response.status_code,
                    response_body=bytes(response.body),
                    media_type=response.media_type,
                )
            )

    async def _release(self, token: str) -> None:
        t = idempotency_keys
        try:
            async with self._db.engine.begin() as conn:
                await conn.execute(
                    sa.delete(t).where(
                        t.c.endpoint == self.endpoint,
                        t.c.key == self.key,
                        t.c.claim_token == token,
                    )
                )
        except Exception:  # не освободили — ключ станет «брошенным» через 60 с
            log.exception("Не удалось освободить ключ идемпотентности")


_KEY_HELP = {True: "Обязателен", False: "Необязателен; повтор вернёт тот же ответ"}


def idempotent(*, required: bool) -> Callable[..., Awaitable[Idempotency]]:
    """Зависимость эндпоинта. Обязательный ключ без заголовка — 422 VALIDATION_ERROR."""

    # Параметр без Annotated: аннотации здесь строковые, а описание зависит от замыкания
    key_header = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        description=_KEY_HELP[required],
    )

    async def dependency(
        request: Request,
        idempotency_key: str | None = key_header,
    ) -> Idempotency:
        if required and idempotency_key is None:
            raise ProblemException(
                422,
                "VALIDATION_ERROR",
                "Нужен заголовок Idempotency-Key",
                errors=[{"loc": ["header", "Idempotency-Key"], "msg": "Field required"}],
            )
        route: Any = request.scope.get("route")
        endpoint = f"{request.method} {getattr(route, 'path', request.url.path)}"
        return Idempotency(
            request.app.state.database,
            request.app.state.clock,
            endpoint,
            idempotency_key,
            canonical_hash(await request.body()),
        )

    return dependency


IdempotencyDep = Annotated[Idempotency, Depends(idempotent(required=True))]
OptionalIdempotencyDep = Annotated[Idempotency, Depends(idempotent(required=False))]


async def purge_expired(database: Database, clock: Clock) -> int:
    async with database.engine.begin() as conn:
        result = await conn.execute(
            sa.delete(idempotency_keys).where(idempotency_keys.c.expires_at <= clock.now())
        )
    return int(result.rowcount or 0)


async def purge_forever(database: Database, clock: Clock) -> None:
    """Фоновая очистка устаревших ключей; ошибки не роняют процесс."""
    while True:
        await asyncio.sleep(PURGE_EVERY_SECONDS)
        try:
            removed = await purge_expired(database, clock)
            if removed:
                log.info("Удалено устаревших ключей идемпотентности: %d", removed)
        except Exception:
            log.warning("Очистка ключей идемпотентности не удалась", exc_info=True)
