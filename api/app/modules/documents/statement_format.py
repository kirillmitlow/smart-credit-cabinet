"""Bounded 1C 1.03 syntax, dates and exact kopecks; no I/O or revenue assumptions.

Source: official 1C exchange format linked in 40-03. This layer preserves posted dates,
account ownership evidence and original fields for the subsequent reconciliation stage.
It deliberately does not turn receipt totals into confirmed business revenue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

from app.modules.documents.validation import STATEMENT_LIMIT, decode_statement
from app.shared.errors import AppError

_MONEY = re.compile(r"[0-9]{1,17}(?:[.,][0-9]{1,2})?\Z")
_DATE = re.compile(r"([0-9]{2})\.([0-9]{2})\.([0-9]{4})\Z")
_ACCOUNT = re.compile(r"[0-9]{20}\Z")
_MAX_MONEY = Decimal("92233720368547758.07")


def _invalid(code: str = "MALFORMED_STATEMENT") -> AppError:
    # Never include source lines, account numbers or payment purposes in error messages.
    return AppError(422, code, "Выписка не прошла проверку формата")


def money(value: str, *, allow_negative: bool = False) -> Decimal:
    """Exact kopecks. Payments are nonnegative; overdraft account balances may be negative."""
    unsigned = value.removeprefix("-") if allow_negative else value
    if not _MONEY.fullmatch(unsigned):
        raise _invalid("INVALID_AMOUNT")
    amount = Decimal(value.replace(",", "."))
    if abs(amount) > _MAX_MONEY:
        raise _invalid("INVALID_AMOUNT")
    return amount


def calendar_date(value: str) -> date:
    match = _DATE.fullmatch(value)
    if match is None:
        raise _invalid("INVALID_DATE")
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise _invalid("INVALID_DATE") from exc


def account_number(value: str) -> str:
    if not _ACCOUNT.fullmatch(value):
        raise _invalid("INVALID_ACCOUNT")
    return value


def _required(fields: Mapping[str, str], key: str) -> str:
    value = fields.get(key, "")
    if not value:
        raise _invalid()
    return value


def _period(fields: Mapping[str, str]) -> tuple[date, date]:
    start = calendar_date(_required(fields, "ДатаНачала"))
    end = calendar_date(_required(fields, "ДатаКонца"))
    if start > end:
        raise _invalid("INVALID_PERIOD")
    return start, end


@dataclass(frozen=True, slots=True)
class AccountSection:
    number: str
    start: date
    end: date
    opening: Decimal
    received: Decimal | None
    spent: Decimal | None
    closing: Decimal | None


@dataclass(frozen=True, slots=True)
class PaymentSection:
    kind: str
    number: str
    created: date
    amount: Decimal
    payer_account: str
    recipient_account: str
    debited: date | None
    credited: date | None
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class StatementFile:
    sha256: str
    encoding: str
    start: date
    end: date
    declared_accounts: tuple[str, ...]
    accounts: tuple[AccountSection, ...]
    payments: tuple[PaymentSection, ...]


def _account(fields: Mapping[str, str]) -> AccountSection:
    start, end = _period(fields)
    return AccountSection(
        account_number(_required(fields, "РасчСчет")),
        start,
        end,
        money(_required(fields, "НачальныйОстаток"), allow_negative=True),
        money(fields["ВсегоПоступило"]) if fields.get("ВсегоПоступило") else None,
        money(fields["ВсегоСписано"]) if fields.get("ВсегоСписано") else None,
        money(fields["КонечныйОстаток"], allow_negative=True)
        if fields.get("КонечныйОстаток")
        else None,
    )


def _payment(kind: str, fields: Mapping[str, str]) -> PaymentSection:
    return PaymentSection(
        kind,
        _required(fields, "Номер"),
        calendar_date(_required(fields, "Дата")),
        money(_required(fields, "Сумма")),
        account_number(_required(fields, "ПлательщикСчет")),
        account_number(_required(fields, "ПолучательСчет")),
        calendar_date(fields["ДатаСписано"]) if fields.get("ДатаСписано") else None,
        calendar_date(fields["ДатаПоступило"]) if fields.get("ДатаПоступило") else None,
        MappingProxyType(dict(fields)),
    )


def read_statement(content: bytes) -> StatementFile:
    """Read the document envelope without trusting its ownership or economic meaning.

    Repeated header РасчСчет/Документ are lists in the official format. All other duplicate
    keys are rejected, including identical values: no hidden 'last value wins' semantics.
    Account sections precede payment sections; no trailing records after КонецФайла.
    """
    if len(content) > STATEMENT_LIMIT:
        raise AppError(413, "FILE_TOO_LARGE", "Выписка должна быть не больше 5 МБ")
    text = decode_statement(content)
    lines = text.splitlines()
    if not lines or lines[0] != "1CClientBankExchange":
        raise _invalid("UNSUPPORTED_FORMAT")
    header: dict[str, str] = {}
    declared: list[str] = []
    account_sections: list[AccountSection] = []
    payments: list[PaymentSection] = []
    section: str | None = None
    kind = ""
    fields: dict[str, str] = {}
    body_started = False
    ended = False
    for raw in lines[1:]:
        line = raw.strip()
        if not line:
            continue
        if ended:
            raise _invalid()
        if line == "КонецФайла":
            if section is not None:
                raise _invalid()
            ended = True
            continue
        if line == "СекцияРасчСчет" or line.startswith("СекцияДокумент="):
            if section is not None or (line == "СекцияРасчСчет" and payments):
                raise _invalid()
            body_started = True
            section = "account" if line == "СекцияРасчСчет" else "payment"
            kind = line.partition("=")[2]
            if section == "payment" and not kind:
                raise _invalid()
            fields = {}
            continue
        if line in {"КонецРасчСчет", "КонецДокумента"}:
            expected = "account" if line == "КонецРасчСчет" else "payment"
            if section != expected:
                raise _invalid()
            if section == "account":
                account_sections.append(_account(fields))
            else:
                payments.append(_payment(kind, fields))
            section = None
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or (section is None and body_started):
            raise _invalid()
        if section is None and key in {"РасчСчет", "Документ"}:
            if key == "РасчСчет":
                declared.append(account_number(value))
            continue
        target = header if section is None else fields
        if key in target:
            raise _invalid("DUPLICATE_FIELD")
        target[key] = value
    if not ended or section is not None or not account_sections or not declared:
        raise _invalid()
    if header.get("ВерсияФормата") != "1.03":
        raise _invalid("UNSUPPORTED_VERSION")
    if header.get("Кодировка") not in {"Windows", "UTF-8"}:
        raise _invalid("BAD_ENCODING")
    try:
        content.decode("utf-8-sig", errors="strict")
        encoding = "utf-8"
    except UnicodeError:
        encoding = "windows-1251"
    if header["Кодировка"] == "UTF-8" and encoding != "utf-8":
        raise _invalid("BAD_ENCODING")
    start, end = _period(header)
    if any(
        item.number not in declared or item.start < start or item.end > end
        for item in account_sections
    ):
        raise _invalid("INVALID_PERIOD")
    return StatementFile(
        sha256(content).hexdigest(),
        encoding,
        start,
        end,
        tuple(dict.fromkeys(declared)),
        tuple(account_sections),
        tuple(payments),
    )
