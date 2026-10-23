"""HTTP-результат действия в транзакции владельца; shared пишет только свою таблицу (50-07).

Незавершённый запрос не коммитится отдельно: откат откатывает и действие, и его ключ.
Advisory xact lock даёт немедленный IN_PROGRESS вместо ожидания незакоммиченной строки.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.shared import clock
from app.shared.errors import AppError
from app.shared.models import IdempotencyKey


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict[str, Any]
    replayed: bool = False


def run_once(
    session: Session, *, scope: str, key: str, request: dict[str, Any], action: Callable[[], Reply]
) -> Reply:
    digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    lock = int.from_bytes(
        hashlib.blake2b(
            f"{scope}\0{key}".encode(), digest_size=8, person=b"scc-http-once"
        ).digest(),
        signed=True,
    )
    if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock}):
        raise AppError(
            409, "IDEMPOTENCY_IN_PROGRESS", "Запрос уже выполняется", headers={"Retry-After": "1"}
        )
    now = clock.system_now()
    row = session.scalars(
        select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
    ).first()
    if row is not None and row.expires_at <= now:
        session.delete(row)
        session.flush()
        row = None
    if row is not None:
        if row.request_hash != digest:
            raise AppError(
                409, "IDEMPOTENCY_KEY_REUSED", "Ключ уже использован для другого запроса"
            )
        if row.response_status is None or row.response_body is None:
            raise AppError(
                409,
                "IDEMPOTENCY_IN_PROGRESS",
                "Запрос уже выполняется",
                headers={"Retry-After": "1"},
            )
        return Reply(row.response_status, json.loads(row.response_body), replayed=True)
    row = IdempotencyKey(
        scope=scope,
        key=key,
        request_hash=digest,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    session.add(row)
    session.flush()
    result = action()
    if not 200 <= result.status < 300:
        raise ValueError("Идемпотентный результат должен быть 2xx")
    row.response_status = result.status
    row.response_body = json.dumps(result.body, ensure_ascii=False, separators=(",", ":")).encode()
    session.flush()
    return result
