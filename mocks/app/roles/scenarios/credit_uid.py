"""Детерминированный сценарный UUID v1 + контрольный символ УИд.

Контроль: приложение 2, п.5 Положения ЦБ 758-П (веса 1…10 циклически,
сумма по модулю 16). UUID синтетический: не содержит времени/узла машины.
Источник: https://www.cbr.ru/queries/xsltblock/file/117713/0/2286-2287 (стр.48).
"""

import hashlib
from uuid import UUID


def contract_uid(code: str, inn: str, label: str) -> str:
    digest = hashlib.sha256(f"{code}:bki:{inn}:{label}".encode()).digest()[:16]
    uid = UUID(bytes=digest, version=1)
    check = sum(int(char, 16) * (index % 10 + 1) for index, char in enumerate(uid.hex)) % 16
    return f"{uid}-{check:x}"
