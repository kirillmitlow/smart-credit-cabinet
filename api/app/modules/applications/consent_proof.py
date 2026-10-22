"""Доказательство простой подписи (T-261, 20-04, 50-09): HMAC на серверном секрете.

Шестизначный код перебирается за секунды, если в базе лежит его обычный хеш. Поэтому в базу идёт
`HMAC(секрет, код | хеш текста | ИНН подписанта | идентификатор попытки | ИНН субъекта | вид)`:
без секрета код из доказательства не восстановить, а секрет не хранится ни в базе, ни в логах.
Субъект и вид добавлены к четырём полям из 50-09, чтобы два согласия одной подписи (компания и
директор у одного человека) не получали одинаковое доказательство. Доказательство каждого
согласия считается отдельно, порядок согласий в пакете на него не влияет.
"""

from __future__ import annotations

import hashlib
import hmac

from app.shared.settings import get_settings

SIGN_METHOD = "SIMPLE_ESIGN"
SIGN_PURPOSE = "SIGN_CONSENT"
_KEY_LABEL = b"scc:simple-esign-proof:v1"


def _key(secret: str) -> bytes:
    """Отдельный ключ подписи из серверного секрета: утечка кода сессии не раскрывает ключ."""
    return hmac.new(secret.encode(), _KEY_LABEL, hashlib.sha256).digest()


def compute_proof(
    secret: str,
    *,
    code: str,
    text_hash: str,
    signer_inn: str,
    attempt_id: str,
    subject_inn: str,
    kind: str,
) -> str:
    message = "|".join((code, text_hash, signer_inn, attempt_id, subject_inn, kind)).encode()
    return hmac.new(_key(secret), message, hashlib.sha256).hexdigest()


def proof_for(
    *,
    code: str,
    text_hash: str,
    signer_inn: str,
    attempt_id: str,
    subject_inn: str,
    kind: str,
) -> str:
    return compute_proof(
        get_settings().session_secret,
        code=code,
        text_hash=text_hash,
        signer_inn=signer_inn,
        attempt_id=attempt_id,
        subject_inn=subject_inn,
        kind=kind,
    )
