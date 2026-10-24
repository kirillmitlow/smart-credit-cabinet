"""T-130 / mocks 10.8: reproducible synthetic 1C documents, exact integer kopecks.

No storage, parser, or API calls. Scenario turnover overrides are authoritative where
available; non-customers use the same monthly revenue model as scenario expansion.
"""

from __future__ import annotations

import random
import re
from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from app.common.accounts import (
    OTHER_BANK_BIK,
    SETTLEMENT_IP,
    SETTLEMENT_LEGAL,
    generate_account,
    make_account,
)
from app.common.clock import last_full_month, month_start
from app.common.inn import generate_kpp, inn_is_valid
from app.common.reldate import add_months
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.finance_series import monthly_revenue, rub, vat_rate
from app.roles.scenarios.identity_people import rng_for, unique_inn
from app.roles.scenarios.schemas import FinanceSpec, Strict

BANK = "Синтетический банк (симуляция)"
CONTENT_TYPE = "text/plain; charset=windows-1251"
# Correspondent accounts use 0 + the fifth/sixth BIK digits for the control key.
CORRESPONDENT = make_account(OTHER_BANK_BIK[:6] + "0" + OTHER_BANK_BIK[4:6], "30101", 111)
EXPENSES = (
    "Аренда помещения",
    "Оплата поставщику",
    "Налоги",
    "Страховые взносы",
    "Реклама",
    "Комиссия банка",
)


class BankStatementRequest(Strict):
    inn: str
    months: int = Field(default=12, ge=1, le=24)
    avg_monthly_revenue_rub: int = Field(ge=0)
    holder_name: str | None = Field(default=None, min_length=1, max_length=200)
    okved: str = Field(default="47.19", pattern=r"^[0-9]{2}(?:\.[0-9]{1,2}){0,2}$")
    vat_rate_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    revenue_trend: Literal["GROWTH", "STABLE", "DECLINE"] | None = None
    trend_percent: float | None = Field(default=None, ge=-100, le=1000)
    seasonality: Literal["NONE", "AGRO", "RETAIL_Q4"] | None = None
    net_margin_percent: float | None = Field(default=None, ge=-100, le=100)
    min_monthly_surplus_rub: int | None = None
    seed: int | None = None

    @model_validator(mode="after")
    def valid_text(self) -> Self:
        if self.holder_name is not None:
            _text(self.holder_name)
        return self

    def finance(self) -> FinanceSpec:
        return FinanceSpec.model_validate(
            self.model_dump(exclude={"inn", "months", "holder_name", "okved", "seed"})
        )


def _text(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError("Название должно быть непустой строкой без управляющих символов")
    value.encode("cp1251")  # Reject unsupported names instead of silently corrupting them.
    return value


def valid_inn(inn: str) -> bool:
    return re.fullmatch(r"(?:[0-9]{10}|[0-9]{12})", inn) is not None and inn_is_valid(inn)


def _money(kopecks: int) -> str:
    sign = "-" if kopecks < 0 else ""
    amount = abs(kopecks)
    return f"{sign}{amount // 100}.{amount % 100:02}"


def _split(total: int, count: int, rng: random.Random) -> list[int]:
    if total == 0:
        return []
    count = min(count, total)
    weights = [rng.randint(1, 1000) for _ in range(count)]
    remaining = total - count
    amounts = [1 + remaining * w // sum(weights) for w in weights]
    amounts[-1] += total - sum(amounts)
    return amounts


def _party(inn: str, name: str, used_accounts: set[str], code: str) -> dict[str, str]:
    rng = rng_for(code, f"statement-account:{inn}")
    prefix = SETTLEMENT_IP if len(inn) == 12 else SETTLEMENT_LEGAL
    account = generate_account(rng, OTHER_BANK_BIK, prefix)
    while account in used_accounts:
        account = generate_account(rng, OTHER_BANK_BIK, prefix)
    used_accounts.add(account)
    return {
        "Счет": account,
        "": _text(name),
        "ИНН": inn,
        "КПП": generate_kpp(inn) if len(inn) == 10 else "",
        "РасчСчет": account,
        "Банк1": BANK,
        "БИК": OTHER_BANK_BIK,
        "Корсчет": CORRESPONDENT,
    }


def build_statement(
    *,
    inn: str,
    holder_name: str,
    okved: str,
    finance: FinanceSpec,
    regime: str,
    code: str,
    today: date,
    months: int,
    turnover: list[dict[str, Any]] | None = None,
) -> tuple[bytes, str]:
    """File bytes and ASCII filename. Creation time is fixed to the current month.

    Only document allocation depends on the statement RNG; financial monthly values
    use the original scenario code, so asking for 6 vs 12 months preserves common totals.
    """
    if not valid_inn(inn) or not 1 <= months <= 24:
        raise ValueError("Неверный ИНН или период выписки")
    used_accounts: set[str] = set()
    owner = _party(inn, holder_name, used_accounts, code)
    anchor = last_full_month(today)
    first = add_months(anchor, 1 - months)
    end = date(anchor.year, anchor.month, monthrange(anchor.year, anchor.month)[1])
    rng = rng_for(code, f"statement:{months}:{today:%Y-%m}")
    settings = ScenarioSettings()
    by_month = {row["month"]: row for row in turnover or []}
    totals: list[tuple[date, int, int]] = []
    for index in range(months):
        month = add_months(first, index)
        row = by_month.get(f"{month:%Y-%m}")
        if row is not None:
            incoming, outgoing = row["incomingRub"], row["outgoingRub"]
        else:
            revenue = monthly_revenue(finance, code, month, anchor, settings)
            incoming = rub(
                Decimal(revenue) * (1 + vat_rate(finance, regime, month, settings) / 100)
            )
            margin = finance.net_margin_percent if finance.net_margin_percent is not None else 10
            surplus = rub(Decimal(revenue) * Decimal(str(margin)) / 100)
            if finance.min_monthly_surplus_rub is not None:
                surplus = max(surplus, finance.min_monthly_surplus_rub)
            outgoing = incoming - surplus
        if type(incoming) is not int or type(outgoing) is not int or min(incoming, outgoing) < 0:
            raise ValueError("Маржа/остаток несовместимы с поступлениями месяца")
        totals.append((month, incoming * 100, outgoing * 100))

    balance = lowest = 0
    for _, incoming, outgoing in totals:
        balance += incoming - outgoing
        lowest = min(lowest, balance)
    opening = -lowest
    incoming_total = sum(row[1] for row in totals)
    outgoing_total = sum(row[2] for row in totals)
    fields = {
        "ВерсияФормата": "1.03",
        "Кодировка": "Windows",
        "Отправитель": BANK,
        "Получатель": f"Демо-кабинет (симуляция {rng.getrandbits(128):032x})",
        "ДатаСоздания": month_start(today).strftime("%d.%m.%Y"),
        "ВремяСоздания": "00:00:00",
        "ДатаНачала": first.strftime("%d.%m.%Y"),
        "ДатаКонца": end.strftime("%d.%m.%Y"),
        "РасчСчет": owner["Счет"],
    }
    lines = ["1CClientBankExchange", *(f"{k}={v}" for k, v in fields.items()), "СекцияРасчСчет"]
    controls = {
        "ДатаНачала": fields["ДатаНачала"],
        "ДатаКонца": fields["ДатаКонца"],
        "РасчСчет": owner["Счет"],
        "НачальныйОстаток": _money(opening),
        "ВсегоПоступило": _money(incoming_total),
        "ВсегоСписано": _money(outgoing_total),
        "КонечныйОстаток": _money(opening + incoming_total - outgoing_total),
    }
    lines.extend(f"{k}={v}" for k, v in controls.items())
    lines.append("КонецРасчСчет")
    used = {inn}
    counterparties = []
    for index in range(8):
        other_inn = unique_inn(rng, used, individual=False)
        used.add(other_inn)
        counterparties.append(
            _party(other_inn, f"Демо-контрагент {index + 1} (симуляция)", used_accounts, code)
        )
    retail = int(okved[:2]) in (47, 55, 56, 96)
    number = 0
    for month, incoming, outgoing in totals:
        days = monthrange(month.year, month.month)[1]
        postings: list[tuple[int, bool, int, str]] = []
        for is_incoming, total in ((True, incoming), (False, outgoing)):
            count = days if is_incoming and retail else 8 if is_incoming else len(EXPENSES)
            amounts = _split(total, count, rng)
            for index, amount in enumerate(amounts):
                purpose = (
                    ("Зачисление эквайринга и СБП" if retail else "Оплата товаров по договору")
                    if is_incoming
                    else EXPENSES[index % len(EXPENSES)]
                )
                postings.append((1 + index * days // len(amounts), is_incoming, amount, purpose))
        for day, is_incoming, amount, purpose in sorted(postings, key=lambda x: (x[0], not x[1])):
            number += 1
            at = date(month.year, month.month, day).strftime("%d.%m.%Y")
            other = counterparties[rng.randrange(len(counterparties))]
            payer, recipient = (other, owner) if is_incoming else (owner, other)
            lines.extend(
                (
                    "СекцияДокумент=Платежное поручение",
                    f"Номер={number}",
                    f"Дата={at}",
                    f"Сумма={_money(amount)}",
                )
            )
            for side, party in (("Плательщик", payer), ("Получатель", recipient)):
                lines.extend(f"{side}{k}={v}" for k, v in party.items())
            lines.extend(
                (
                    f"{'ДатаПоступило' if is_incoming else 'ДатаСписано'}={at}",
                    "ВидОплаты=01",
                    "Очередность=5",
                    f"НазначениеПлатежа={purpose} (симуляция)",
                    "КонецДокумента",
                )
            )
    lines.append("КонецФайла")
    return ("\r\n".join(lines) + "\r\n").encode(
        "cp1251"
    ), f"statement_{inn}_{first:%Y-%m}_{end:%Y-%m}.txt"
