"""Состав, реквизиты и совпадение участников между системами (10.3)."""

from datetime import date
from decimal import Decimal

from app.roles.scenarios.consistency_common import Context, require


def form_data(c: Context) -> None:
    form = c.identity["form"]
    entity = c.data["registry"]["entity"]
    if form in {"IP", "SELF_EMPLOYED"}:
        require(not c.tax["financials"], "У ИП и самозанятого нет бухотчётности")
        require(
            not c.identity["director"] and not c.identity["founders"],
            "У человека нет директора/учредителей",
        )
        require(not c.identity["kpp"], "У ИП и самозанятого нет КПП")
    if form == "SELF_EMPLOYED":
        require(entity is None, "Самозанятого нет в ЕГРИП")
        require(c.tax["npd"] is not None, "У самозанятого нужен статус НПД")
        require(
            c.tax["taxProfile"] is None and c.tax["sme"] is None, "У самозанятого только статус НПД"
        )
    else:
        require(entity is not None, "Нужна карточка ЕГРЮЛ/ЕГРИП")
        require(c.tax["npd"] is None, "НПД допустим только для формы SELF_EMPLOYED")
        expected = "INDIVIDUAL_ENTREPRENEUR" if form == "IP" else "LEGAL_ENTITY"
        require(entity["type"] == expected, f"Форме {form} соответствует карточка {expected}")


def company_card(c: Context) -> None:
    entity = c.data["registry"]["entity"]
    if entity is None:
        return
    for key in ("inn", "registrationDate"):
        require(
            entity[key] == c.identity[key],
            f"Карточка {key}={entity[key]} не совпадает с identity {c.identity[key]}",
        )
    ogrn = entity.get("ogrn", entity.get("ogrnip"))
    registered = date.fromisoformat(entity["registrationDate"])
    require(ogrn == c.identity["ogrn"], "ОГРН карточки не совпадает с реквизитами компании")
    require(int(ogrn[1:3]) == registered.year % 100, f"Год ОГРН {ogrn} не совпадает с {registered}")
    require(registered <= c.today, f"Дата регистрации {registered} находится в будущем")


def llc_shares(c: Context) -> None:
    entity = c.data["registry"]["entity"]
    if c.identity["form"] == "LLC":
        total = sum((Decimal(str(p["sharePercent"])) for p in entity["founders"]), Decimal(0))
        require(abs(total - 100) <= Decimal("0.000001"), f"Доли ООО: {total}%, требуется 100%")
    elif c.identity["form"] == "JSC":
        require(not entity["founders"], "В карточке АО не должно быть учредителей")


def role_identities(c: Context) -> None:
    registry = c.data["registry"]
    expected = {p["inn"]: p for p in c.identity["persons"]}
    actual = {p["inn"]: p for p in registry["persons"]}
    require(set(actual) == set(expected), "Люди в реестре не совпадают с участниками identity")
    for inn, person in actual.items():
        require(
            all(
                person[key] == expected[inn][key]
                for key in ("lastName", "firstName", "middleName", "birthDate")
            ),
            f"Изменены личность или дата рождения участника {inn}",
        )
    if c.identity["form"] in {"LLC", "JSC"}:
        director = registry["entity"]["director"]
        require(
            director is not None and director["inn"] == c.identity["subjectRefs"]["director"],
            "Директор реестра не совпадает с identity",
        )
        if c.identity["form"] == "LLC":
            refs = {p["inn"] for p in c.identity["founders"]}
            require(
                {p["inn"] for p in registry["entity"]["founders"]} == refs,
                "Учредители реестра не совпадают с identity",
            )


def bki_identity(c: Context) -> None:
    known = {p["inn"]: p for p in c.identity["persons"]}
    seen: set[str] = set()
    for entry in c.data["bki"]:
        inn, body = entry["inn"], entry["body"]
        require(inn not in seen, f"Дублирован субъект БКИ {inn}")
        seen.add(inn)
        subject = body["subject"]
        if inn == c.identity["inn"] and c.identity["form"] in {"LLC", "JSC"}:
            require(
                subject["type"] == "LEGAL_ENTITY" and subject["ogrn"] == c.identity["ogrn"],
                f"Реквизиты организации {inn} в БКИ отличаются от реестра",
            )
        else:
            require(inn in known, f"В БКИ неизвестный участник {inn}")
            require(subject["type"] == "PERSON", f"Участник {inn} в БКИ должен быть человеком")
            require(
                all(
                    subject[key] == known[inn][key]
                    for key in ("lastName", "firstName", "middleName", "birthDate")
                ),
                f"БКИ и реестр описывают разных людей для ИНН {inn}",
            )


def bki_company_age(c: Context) -> None:
    if c.identity["form"] not in {"LLC", "JSC"}:
        return
    for entry in c.data["bki"]:
        if entry["inn"] == c.identity["inn"]:
            for loan in entry["body"]["obligations"]:
                require(
                    loan["openedAt"] >= c.identity["registrationDate"],
                    f"Кредит {loan['uid']} открыт {loan['openedAt']} "
                    f"раньше регистрации {c.identity['registrationDate']}",
                )
