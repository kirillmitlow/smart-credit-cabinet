"""Детерминированные люди и ссылки на одного человека в нескольких ролях."""

from __future__ import annotations

import hashlib
import random
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any

from app.common.inn import generate_inn, inn_is_valid
from app.common.reldate import add_months
from app.roles.scenarios.schemas import Person

_NAMES = (
    "Иванов Алексей Петрович",
    "Петров Сергей Николаевич",
    "Смирнова Анна Сергеевна",
    "Кузнецова Ольга Викторовна",
    "Соколов Дмитрий Андреевич",
    "Волкова Мария Александровна",
    "Орлов Михаил Игоревич",
    "Морозова Елена Павловна",
)


def rng_for(code: str, label: str) -> random.Random:
    return random.Random(  # noqa: S311 — воспроизводимая синтетика, не секреты
        int.from_bytes(hashlib.sha256(f"{code}:{label}".encode()).digest())
    )


def synthetic_inn(value: str, *, individual: bool) -> str:
    if not inn_is_valid(value) or len(value) != (12 if individual else 10):
        raise ValueError("ИНН: неверная длина или контрольная сумма")
    if not value.startswith("00"):
        raise ValueError("В сценариях допустимы только синтетические ИНН региона 00")
    return value


def unique_inn(rng: random.Random, used: set[str], *, individual: bool) -> str:
    for _ in range(10000):
        value = generate_inn(rng, individual=individual)
        if value not in used:
            used.add(value)
            return value
    raise ValueError("Не удалось подобрать свободный синтетический ИНН")


def shares(people: list[Person]) -> list[float]:
    """Заданные доли сохраняются, остаток делится между незаданными, последнему — округление."""
    values = [
        Decimal(str(p.share_percent)) if p.share_percent is not None else None for p in people
    ]
    remaining = Decimal(100) - sum((v for v in values if v is not None), Decimal(0))
    missing = [i for i, v in enumerate(values) if v is None]
    if not people or remaining < 0 or (not missing and remaining != 0):
        raise ValueError("Сумма долей учредителей ООО должна быть 100%")
    if missing:
        part = (remaining / len(missing)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        for i in missing[:-1]:
            values[i] = part
        values[missing[-1]] = remaining - part * (len(missing) - 1)
    if any(v is None or v <= 0 for v in values):
        raise ValueError("Доля каждого учредителя должна быть больше нуля")
    return [float(v) for v in values if v is not None]


def people(
    entries: list[tuple[str, Person]], code: str, today: date, used: set[str]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Сначала объединяем явные поля по ref/ИНН, затем генерируем недостающее.

    Так данные учредителя дополняют директора с тем же ref независимо от порядка полей.
    Разные ref при одном ИНН — допустимые псевдонимы одного человека.
    """
    groups: list[dict[str, Any]] = []
    for slot, person in entries:
        ref = person.ref or slot
        data = person.model_dump(mode="json", by_alias=True, exclude_none=True)
        data = {k: v for k, v in data.items() if k not in ("ref", "sharePercent")}
        matches = [
            g
            for g in groups
            if ref in g["refs"] or (data.get("inn") and data.get("inn") == g["data"].get("inn"))
        ]
        group: dict[str, Any] = {"refs": [ref], "slots": [slot], "data": data}
        for old in matches:
            for key, value in old["data"].items():
                if key in group["data"] and group["data"][key] != value:
                    raise ValueError(f"Противоречивые данные одного человека: {key}")
                group["data"][key] = value
            group["refs"] = list(dict.fromkeys(old["refs"] + group["refs"]))
            group["slots"] = old["slots"] + group["slots"]
            groups.remove(old)
        groups.append(group)

    # Явные ИНН резервируются до генерации, чтобы случайный номер не занял явный.
    for group in groups:
        if value := group["data"].get("inn"):
            synthetic_inn(value, individual=True)
            if value in used:
                raise ValueError("ИНН человека уже занят другим субъектом сценария")
            used.add(value)
    slots: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for group in groups:
        data = group["data"]
        rng = rng_for(code, "person:" + group["refs"][0])
        full_name = " ".join((data.get("fullName") or rng.choice(_NAMES)).split())
        parts = full_name.split(maxsplit=2)
        if len(parts) < 2:
            raise ValueError("ФИО человека должно содержать фамилию и имя")
        birth = (
            date.fromisoformat(data["birthDate"])
            if "birthDate" in data
            else add_months(today, -12 * rng.randint(25, 65))
        )
        if birth > today:
            raise ValueError("Дата рождения не может быть в будущем")
        record = {
            "ref": group["refs"][0],
            "refs": group["refs"],
            "inn": data.get("inn") or unique_inn(rng, used, individual=True),
            "fullName": full_name,
            "lastName": parts[0],
            "firstName": parts[1],
            "middleName": parts[2] if len(parts) == 3 else None,
            "birthDate": birth.isoformat(),
        }
        records.append(record)
        for slot in group["slots"]:
            slots[slot] = record
    return slots, records
