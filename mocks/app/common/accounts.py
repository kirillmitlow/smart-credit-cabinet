"""Номера банковских счетов (20 цифр) с контрольным ключом по правилам Банка России.

Ключ — девятая цифра: считается по трём последним цифрам БИК и номеру счёта с весами 7-1-3.
"""

from __future__ import annotations

import random
import re

OUR_BANK_BIK = "040000999"
# Синтетический «другой банк» для выписки 1С (раздел 10.8)
OTHER_BANK_BIK = "040000111"

# Балансовые счета второго порядка, которые встречаются в сценариях
SETTLEMENT_LEGAL = "40702"  # расчётный счёт организации
SETTLEMENT_IP = "40802"  # расчётный счёт ИП
LOAN_LEGAL = "45206"  # ссудный счёт организации
LOAN_IP = "45406"  # ссудный счёт ИП

RUB = "810"
_WEIGHTS = ((7, 1, 3) * 8)[:23]  # 23 позиции: 3 цифры БИК + 20 цифр счёта
_ACCOUNT = re.compile(r"^\d{20}$")
_BIK = re.compile(r"^\d{9}$")
KEY_INDEX = 8


class AccountError(ValueError):
    pass


def _weighted_sum(bik: str, account: str) -> int:
    digits = bik[-3:] + account
    return sum(int(d) * w % 10 for d, w in zip(digits, _WEIGHTS, strict=True))


def control_key(bik: str, account: str) -> str:
    """Ключ для счёта; цифра на месте ключа игнорируется."""
    if not _BIK.match(bik) or not _ACCOUNT.match(account):
        raise AccountError("Ожидается БИК из 9 цифр и счёт из 20 цифр")
    zeroed = account[:KEY_INDEX] + "0" + account[KEY_INDEX + 1 :]
    return str(_weighted_sum(bik, zeroed) % 10 * 3 % 10)


def account_is_valid(bik: str, account: str) -> bool:
    if not _BIK.match(bik) or not _ACCOUNT.match(account):
        return False
    return _weighted_sum(bik, account) % 10 == 0


def make_account(bik: str, balance_account: str, serial: int, *, branch: str = "0000") -> str:
    """Счёт вида ААААА 810 К ФФФФ NNNNNNN с правильным ключом."""
    if not re.fullmatch(r"\d{5}", balance_account) or not re.fullmatch(r"\d{4}", branch):
        raise AccountError("Балансовый счёт — 5 цифр, подразделение — 4 цифры")
    if not 0 <= serial <= 9_999_999:
        raise AccountError("Порядковый номер счёта — от 0 до 9 999 999")
    draft = f"{balance_account}{RUB}0{branch}{serial:07d}"
    return draft[:KEY_INDEX] + control_key(bik, draft) + draft[KEY_INDEX + 1 :]


def generate_account(rng: random.Random, bik: str, balance_account: str) -> str:
    return make_account(bik, balance_account, rng.randint(1, 9_999_999))


def mask_account(account: str) -> str:
    return "*" * 16 + account[-4:] if len(account) == 20 else "*" * len(account)
