"""Идентификаторы: UUID v7 для записей (упорядочены по времени, не угадываются) и requestId."""

from __future__ import annotations

import secrets
import time
import uuid

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def uuid7() -> uuid.UUID:
    """UUID версии 7 (RFC 9562): 48 бит миллисекунд Unix + 74 случайных бита."""
    millis = time.time_ns() // 1_000_000
    rand = secrets.randbits(74)
    value = (millis & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # версия
    value |= (rand >> 62) << 64  # 12 бит rand_a
    value |= 0b10 << 62  # вариант RFC
    value |= rand & ((1 << 62) - 1)  # 62 бита rand_b
    return uuid.UUID(int=value)


def ulid_like() -> str:
    """26 символов Crockford base32 от UUID v7: сортируется по времени, как ULID."""
    number = uuid7().int
    return "".join(_CROCKFORD[(number >> shift) & 31] for shift in range(125, -1, -5))


def new_request_id() -> str:
    return "req_" + ulid_like()
