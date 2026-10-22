"""Одноразовые коды для входа и подписи (T-211, 50-09).

В Redis хранится только HMAC кода, привязанный к человеку, цели и предмету; 5 минут, 3 попытки.
Сам код возвращается вызывающему только в демо-режиме (D-062) и никогда не пишется в лог.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

import redis

from app.modules.auth.sessions import store_unavailable
from app.shared.cache import get_redis
from app.shared.errors import AppError
from app.shared.settings import get_settings

CODE_TTL_SECONDS = 300
MAX_ATTEMPTS = 3
KEY_PREFIX = "scc:otp:"


@dataclass(frozen=True)
class IssuedCode:
    request_id: str
    code: str  # показывать только при DEMO_MODE
    expires_in: int


def _digest(request_id: str, person_inn: str, purpose: str, subject: str, code: str) -> str:
    secret = get_settings().session_secret.encode()
    message = f"{request_id}|{person_inn}|{purpose}|{subject}|{code}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def issue(person_inn: str, purpose: str, subject: str = "") -> IssuedCode:
    request_id = "otp_" + secrets.token_urlsafe(16)
    code = f"{secrets.randbelow(10**6):06d}"
    record = {
        "person_inn": person_inn,
        "purpose": purpose,
        "subject": subject,
        "digest": _digest(request_id, person_inn, purpose, subject, code),
        "attempts": 0,
    }
    try:
        get_redis().set(KEY_PREFIX + request_id, json.dumps(record), ex=CODE_TTL_SECONDS)
    except redis.RedisError as exc:
        raise store_unavailable(exc) from exc
    return IssuedCode(request_id, code, CODE_TTL_SECONDS)


@dataclass(frozen=True)
class VerifiedCode:
    person_inn: str
    purpose: str
    subject: str


def verify(request_id: str, code: str, *, purpose: str) -> VerifiedCode:
    """Проверить код; при успехе он погашается. Ошибки: CODE_EXPIRED, CODE_INVALID, CODE_ATTEMPTS_EXCEEDED."""
    client = get_redis()
    key = KEY_PREFIX + request_id
    try:
        raw = client.get(key)
        if raw is None:
            raise AppError(410, "CODE_EXPIRED", "Код истёк или уже использован")
        record = json.loads(str(raw))
        if record["attempts"] >= MAX_ATTEMPTS:
            raise AppError(429, "CODE_ATTEMPTS_EXCEEDED", "Попытки исчерпаны, запросите новый код")
        expected = record["digest"]
        given = _digest(request_id, record["person_inn"], purpose, record["subject"], code)
        if record["purpose"] != purpose or not hmac.compare_digest(expected, given):
            record["attempts"] += 1
            ttl = client.ttl(key)
            client.set(key, json.dumps(record), ex=max(1, int(ttl)))
            if record["attempts"] >= MAX_ATTEMPTS:
                raise AppError(
                    429, "CODE_ATTEMPTS_EXCEEDED", "Попытки исчерпаны, запросите новый код"
                )
            raise AppError(422, "CODE_INVALID", "Неверный код")
        client.delete(key)
    except redis.RedisError as exc:
        raise store_unavailable(exc) from exc
    return VerifiedCode(record["person_inn"], record["purpose"], record["subject"])
