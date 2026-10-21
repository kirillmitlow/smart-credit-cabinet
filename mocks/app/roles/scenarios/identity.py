"""Identity сценария: согласованные реквизиты и готовое тело registry (10.3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.common.inn import generate_kpp, generate_ogrn, kpp_is_valid, ogrn_is_valid
from app.common.reldate import add_months
from app.roles.scenarios.identity_people import people, rng_for, shares, synthetic_inn, unique_inn
from app.roles.scenarios.schemas import Person, ScenarioSpec

_FORMS = {
    "LLC": ("ООО", "12300", "Общество с ограниченной ответственностью"),
    "JSC": ("АО", "12267", "Непубличное акционерное общество"),
}
_STATUS_NAMES = {
    "ACTIVE": "Действующее",
    "LIQUIDATING": "В процессе ликвидации",
    "LIQUIDATED": "Ликвидировано",
    "BANKRUPT": "Банкротство",
    "REORGANIZING": "Реорганизация",
    "CEASED": "Деятельность прекращена",
}
_COMPANY_NAMES = ("Вектор", "Маяк", "Горизонт", "Спектр", "Исток", "Прогресс")


def _record_grn(code: str, label: str, year: int) -> str:
    # ГРН последующей записи начинается с 2, ОГРН первичной регистрации — с 1.
    body = f"2{year % 100:02d}00{rng_for(code, label).randint(0, 9_999_999):07d}"
    return body + str(int(body) % 11 % 10)


def expand_identity(
    spec: ScenarioSpec, code: str, today: date, reserved: set[str]
) -> dict[str, Any]:
    company = spec.company
    if company is None or company.form is None:
        raise ValueError("Укажите company.form или preset явно")
    form = company.form
    legal = form in _FORMS
    if not legal and (company.unreliable_address or company.pending_exclusion):
        raise ValueError("Отметки адреса и исключения из ЕГРЮЛ доступны только организациям")
    used = set(reserved)
    rng = rng_for(code, "company")
    if company.inn is not None:
        inn = synthetic_inn(company.inn, individual=not legal)
        if inn in used:
            raise ValueError("ИНН компании уже занят другим сценарием")
        used.add(inn)
    else:
        inn = unique_inn(rng, used, individual=not legal)
    registered = company.registration_date or add_months(
        today, -(company.age_months if company.age_months is not None else 36)
    )
    if registered > today:
        raise ValueError("Дата регистрации не может быть в будущем")
    ogrn: str | None = None
    if form != "SELF_EMPLOYED":
        if company.ogrn is not None:
            ogrn = company.ogrn
            if company.registration_date is None:
                raise ValueError("При заданном ogrn нужна абсолютная registrationDate")
            if not ogrn_is_valid(ogrn) or len(ogrn) != (13 if legal else 15) or ogrn[3:5] != "00":
                raise ValueError(
                    "ОГРН: нужны верная контрольная сумма, длина и синтетический регион 00"
                )
            if int(ogrn[1:3]) != registered.year % 100:
                raise ValueError("Год ОГРН должен совпадать с годом registrationDate")
        else:
            ogrn = generate_ogrn(rng_for(code, "ogrn"), registered.year, individual=not legal)
    elif company.ogrn is not None:
        raise ValueError("У самозанятого нет ОГРН")
    kpp = (company.kpp or generate_kpp(inn)) if legal else None
    if kpp is not None and not kpp_is_valid(kpp, inn):
        raise ValueError("КПП должен начинаться с первых четырёх цифр ИНН")

    director_spec = spec.people.director if spec.people and spec.people.director else Person()
    if legal:
        director_spec = director_spec.model_copy(update={"ref": director_spec.ref or "director"})
        founder_specs = spec.people.founders if spec.people else None
        if form == "LLC" and founder_specs is None:
            founder_specs = [director_spec]
        founder_specs = founder_specs or []
        entries = [("director", director_spec)] + [
            (f"founder-{i + 1}", p) for i, p in enumerate(founder_specs)
        ]
        slots, persons = people(entries, code, today, used)
        director = slots["director"]
        portions = shares(founder_specs) if form == "LLC" else []
        founders = [
            {**slots[f"founder-{i + 1}"], "sharePercent": portion}
            for i, portion in enumerate(portions)
        ]
        if len({p["inn"] for p in founders}) != len(founders):
            raise ValueError("Один учредитель указан дважды")
        owner = max(founders, key=lambda p: p["sharePercent"]) if founders else None
        business_name = company.name or rng.choice(_COMPANY_NAMES)
        short_name = f"{_FORMS[form][0]} «{business_name}»"
    else:
        # ИНН ИП/самозанятого принадлежит самому человеку; директора у них нет.
        used.remove(inn)
        name = company.name
        if name and name.startswith("ИП "):
            name = name[3:]
        slots, persons = people(
            [("self", Person(ref="self", inn=inn, full_name=name))], code, today, used
        )
        director, founders = None, []
        owner = slots["self"] if form == "IP" else None
        short_name = ("ИП " if form == "IP" else "Самозанятый ") + slots["self"]["fullName"]

    region = company.region_code or "00"
    status = company.status or "ACTIVE"
    allowed = set(_STATUS_NAMES) - (
        {"CEASED"} if legal else {"LIQUIDATING", "LIQUIDATED", "REORGANIZING"}
    )
    if status not in allowed:
        raise ValueError(f"Недопустимый status для формы {form}")
    okved = {"code": company.okved or "47.19", "name": "Демонстрационный вид деятельности"}
    identity = {
        "form": form,
        "inn": inn,
        "ogrn": ogrn,
        "kpp": kpp,
        "shortName": short_name,
        "registrationDate": registered.isoformat(),
        "status": status,
        "okved": okved["code"],
        "regionCode": region,
        "director": director,
        "founders": founders,
        "owner": owner,
        "persons": persons,
        "subjectRefs": {
            "company": inn,
            "director": director["inn"] if director else None,
            "owner": owner["inn"] if owner else None,
            **{f"founder:{ref}": p["inn"] for p in founders for ref in p["refs"]},
        },
    }
    registry_people = [
        {k: p[k] for k in ("inn", "lastName", "firstName", "middleName", "birthDate")}
        for p in persons
    ]
    common = {
        "inn": inn,
        "registrationDate": registered.isoformat(),
        "status": {"code": status, "name": _STATUS_NAMES[status], "since": registered.isoformat()},
        "okvedMain": okved,
        "okvedAdditional": [],
        "taxAuthority": {"code": inn[:4], "name": f"Демонстрационная инспекция {inn[:4]}"},
        "lastRecord": {"grn": ogrn, "date": registered.isoformat()},
    }
    entity: dict[str, Any] | None
    if legal:
        nominals = [int(Decimal(str(p["sharePercent"])) * 100) for p in founders]
        if nominals:
            nominals[-1] = 10000 - sum(nominals[:-1])
        entity = {
            **common,
            "type": "LEGAL_ENTITY",
            "ogrn": ogrn,
            "kpp": kpp,
            "fullName": f"{_FORMS[form][2]} «{business_name}»",
            "shortName": short_name,
            "legalForm": {"okopf": _FORMS[form][1], "name": _FORMS[form][2]},
            "address": {
                "regionCode": region,
                "regionName": f"Демонстрационный регион {region}",
                "full": "Демонстрационный адрес, ул. Тестовая, д. 1",
                "unreliable": None,
            },
            "pendingExclusion": None,
            "authorizedCapitalRub": 10000,
            "director": {
                "fullName": director["fullName"],
                "inn": director["inn"],
                "position": "Генеральный директор",
                "since": registered.isoformat(),
                "unreliable": None,
            }
            if director
            else None,
            "founders": [
                {
                    "type": "PERSON",
                    "fullName": p["fullName"],
                    "inn": p["inn"],
                    "sharePercent": p["sharePercent"],
                    "shareNominalRub": nominal,
                    "unreliable": None,
                }
                for p, nominal in zip(founders, nominals, strict=True)
            ],
        }
        if company.unreliable_address:
            entity["address"]["unreliable"] = {
                "since": today.isoformat(),
                "grn": _record_grn(code, "unreliable", today.year),
                "reason": "Демонстрационная отметка недостоверности адреса",
            }
            entity["lastRecord"] = {
                "grn": entity["address"]["unreliable"]["grn"],
                "date": today.isoformat(),
            }
        if company.pending_exclusion:
            entity["pendingExclusion"] = {
                "decisionDate": today.isoformat(),
                "grn": _record_grn(code, "exclusion", today.year),
                "objectionsDeadline": add_months(today, 3).isoformat(),
            }
            entity["lastRecord"] = {
                "grn": entity["pendingExclusion"]["grn"],
                "date": today.isoformat(),
            }
    elif form == "IP":
        person = slots["self"]
        entity = {
            **common,
            "type": "INDIVIDUAL_ENTREPRENEUR",
            "ogrnip": ogrn,
            "person": {k: person[k] for k in ("lastName", "firstName", "middleName", "fullName")},
            "region": {"code": region, "name": f"Демонстрационный регион {region}"},
        }
    else:
        entity = None
    return {
        "identity": identity,
        "registry": {"entity": entity, "persons": registry_people, "bankruptcies": []},
    }
