"""ИНН, ОГРН, ОГРНИП и КПП: проверка контрольных сумм, генерация синтетических (регион 00), маска.

Регион «00» не выдаётся реальным налогоплательщикам: синтетика не совпадёт с живыми
данными (RQ-52).
Генерация детерминирована: всё случайное берётся из переданного random.Random.
"""

from __future__ import annotations

import random
import re

SYNTHETIC_REGION = "00"

_INN10_W = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_W1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_W2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_KPP = re.compile(r"^\d{4}[\dA-Z]{2}\d{3}$")
_INN_IN_TEXT = re.compile(r"(?<!\d)(\d{12}|\d{10})(?!\d)")


class IdentifierError(ValueError):
    """Неверный идентификатор; роль превращает его в 400 INN_INVALID или 422."""


def _check_digit(digits: str, weights: tuple[int, ...]) -> str:
    return str(sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11 % 10)


def inn_is_valid(inn: str) -> bool:
    if not inn.isdigit():
        return False
    if len(inn) == 10:
        return inn[9] == _check_digit(inn[:9], _INN10_W)
    if len(inn) == 12:
        return inn[10] == _check_digit(inn[:10], _INN12_W1) and inn[11] == _check_digit(
            inn[:11], _INN12_W2
        )
    return False


def validate_inn(inn: str) -> str:
    if not inn_is_valid(inn):
        raise IdentifierError("ИНН должен состоять из 10 или 12 цифр с верной контрольной суммой")
    return inn


def generate_inn(rng: random.Random, *, individual: bool = False) -> str:
    """ИНН организации (10 цифр) или физлица/ИП (12 цифр) с регионом 00."""
    inspection = f"{rng.randint(1, 99):02d}"
    if individual:
        body = SYNTHETIC_REGION + inspection + f"{rng.randint(0, 999_999):06d}"
        body += _check_digit(body, _INN12_W1)
        return body + _check_digit(body, _INN12_W2)
    body = SYNTHETIC_REGION + inspection + f"{rng.randint(0, 99_999):05d}"
    return body + _check_digit(body, _INN10_W)


def ogrn_is_valid(ogrn: str) -> bool:
    """ОГРН (13 цифр) или ОГРНИП (15 цифр)."""
    if not ogrn.isdigit():
        return False
    if len(ogrn) == 13:
        return ogrn[0] in "15" and ogrn[12] == str(int(ogrn[:12]) % 11 % 10)
    if len(ogrn) == 15:
        return ogrn[0] == "3" and ogrn[14] == str(int(ogrn[:14]) % 13 % 10)
    return False


def ogrn_year(ogrn: str) -> int:
    """Год присвоения номера по цифрам 2–3 (для синтетики — век 2000-х)."""
    return 2000 + int(ogrn[1:3])


def generate_ogrn(rng: random.Random, registration_year: int, *, individual: bool = False) -> str:
    year = f"{registration_year % 100:02d}"
    inspection = f"{rng.randint(1, 99):02d}"
    if individual:
        body = "3" + year + SYNTHETIC_REGION + inspection + f"{rng.randint(0, 9_999_999):07d}"
        return body + str(int(body) % 13 % 10)
    body = "1" + year + SYNTHETIC_REGION + inspection + f"{rng.randint(0, 99_999):05d}"
    return body + str(int(body) % 11 % 10)


def kpp_is_valid(kpp: str, inn: str | None = None) -> bool:
    if not _KPP.match(kpp):
        return False
    return inn is None or kpp[:4] == inn[:4]


def generate_kpp(inn: str) -> str:
    """КПП по месту регистрации: код инспекции из ИНН + причина 01 + номер 001."""
    return inn[:4] + "01001"


def mask_inn(inn: str) -> str:
    """0017654322 → 0017****22: середина скрыта, длина сохраняется."""
    if len(inn) < 7:
        return "*" * len(inn)
    return inn[:4] + "*" * (len(inn) - 6) + inn[-2:]


def mask_inns_in_text(text: str) -> str:
    """Маскировать все ИНН-подобные числа в строке (путь запроса, сообщение)."""
    return _INN_IN_TEXT.sub(lambda m: mask_inn(m.group(1)), text)
