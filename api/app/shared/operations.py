"""Ограждение операций от демо-сброса (T-372).

Обычная операция держит разделяемые session advisory locks: общий и своей компании.
Сброс компании берёт исключительный замок только этой компании, общий сброс — общий.
Замки живут и между короткими транзакциями, пока операция обращается к внешнему моку.
Поставщика Scope передаёт владелец данных; shared не импортирует бизнес-модули.
"""

import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import blake2b
from uuid import UUID

from sqlalchemy import Connection, text

from app.shared import db
from app.shared.errors import AppError

GLOBAL_RESET_KEY = zlib.crc32(b"scc-demo-reset")


@dataclass(frozen=True, slots=True)
class Scope:
    company_id: UUID
    generation: int
    resetting: bool = False


class ResetInProgress(AppError):
    def __init__(self) -> None:
        super().__init__(
            409,
            "DEMO_RESET_IN_PROGRESS",
            "Данные компании сбрасываются; повторите позже",
            headers={"Retry-After": "1"},
        )


def company_key(company_id: UUID) -> int:
    # Отрицательное пространство ключей не пересекается с положительным общим замком.
    digest = blake2b(company_id.bytes, digest_size=8, person=b"scc-reset").digest()
    return -1 - (int.from_bytes(digest, "big") & ((1 << 63) - 1))


def _take(conn: Connection, key: int, *, exclusive: bool) -> bool:
    fn = "pg_try_advisory_lock" if exclusive else "pg_try_advisory_lock_shared"
    got = bool(conn.scalar(text(f"SELECT {fn}(:key)"), {"key": key}))
    conn.commit()  # держим session lock, но не простаивающую транзакцию
    return got


def _release(conn: Connection, locks: list[tuple[int, bool]]) -> None:
    try:
        conn.rollback()
        for key, exclusive in reversed(locks):
            fn = "pg_advisory_unlock" if exclusive else "pg_advisory_unlock_shared"
            conn.execute(text(f"SELECT {fn}(:key)"), {"key": key})
        conn.commit()
    except BaseException:
        conn.invalidate()  # физическое соединение закроется и отпустит все session locks
        raise


@contextmanager
def hold(
    provider: Callable[[], Scope | None], *, exclusive: bool = False
) -> Iterator[Scope | None]:
    """Операция либо целиком проходит до сброса, либо не начинается.

    Повторное чтение после взятия замка ограждает задержку между поиском объекта и замком.
    Отсутствующий объект возвращает None: HTTP отдаст обычный 404, старая задача — SKIPPED.
    exclusive=True разрешён контроллеру сброса, в том числе для повтора незавершённого сброса.
    """
    with db.get_database().engine.connect() as conn:
        locks: list[tuple[int, bool]] = []
        try:
            if not _take(conn, GLOBAL_RESET_KEY, exclusive=False):
                raise ResetInProgress()
            locks.append((GLOBAL_RESET_KEY, False))
            before = provider()
            if before is None:
                yield None
                return
            key = company_key(before.company_id)
            if not _take(conn, key, exclusive=exclusive):
                raise ResetInProgress()
            locks.append((key, exclusive))
            current = provider()
            if current is None:
                yield None
                return
            if current.company_id != before.company_id or current.generation != before.generation:
                raise ResetInProgress()
            if current.resetting and not exclusive:
                raise ResetInProgress()
            yield current
        finally:
            _release(conn, locks)
