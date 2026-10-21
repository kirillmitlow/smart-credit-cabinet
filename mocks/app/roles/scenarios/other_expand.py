"""T-125: полный независимый снимок прочих систем без изменения исходного expanded."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from app.roles.bank_core.schemas import BankCoreBody
from app.roles.bki.schemas import BkiSubjectBody
from app.roles.registry.schemas import RegistryBody
from app.roles.scenarios.other_cases import add_cases
from app.roles.scenarios.other_tax import add_contracts, add_tax
from app.roles.scenarios.schemas import ScenarioSpec
from app.roles.tax.schemas import TaxBody


def _compliance(spec: ScenarioSpec, result: dict[str, Any], today: date) -> None:
    identity = result["identity"]
    requested = spec.compliance
    aml_target = None
    if requested and requested.aml_listed:
        role = "company" if requested.aml_listed == "COMPANY" else "director"
        aml_target = identity["subjectRefs"].get(role)
        if aml_target is None:
            raise ValueError(f"compliance.amlListed: у этой формы нет субъекта {role}")
    level = requested.zsk if requested and requested.zsk is not None else "GREEN"
    if level not in ("GREEN", "YELLOW", "RED"):
        raise ValueError("compliance.zsk: ожидается GREEN, YELLOW или RED")
    people = {p["inn"] for p in identity["persons"]}
    existing = result.setdefault("bankSubjects", [])
    by_inn = {entry["inn"]: entry["body"] for entry in existing}
    if len(by_inn) != len(existing):
        raise ValueError("В bankSubjects один человек указан дважды")
    for inn in [identity["inn"], *sorted(people - {identity["inn"]})]:
        is_company = inn == identity["inn"]
        body = result.setdefault("bankCore", {}) if is_company else by_inn.get(inn)
        if body is None:
            body = {}
            existing.append({"inn": inn, "body": body})
        body["compliance"] = {
            "aml": {
                "listName": "ROSFINMONITORING_TERRORISM_EXTREMISM",
                "reason": "Демо: перечень Росфинмониторинга",
            }
            if inn == aml_target
            else None,
            "zsk": {"riskLevel": level, "assessedAt": today.replace(day=1).isoformat()}
            if is_company and identity["form"] != "SELF_EMPLOYED"
            else None,
            "internalStopList": {"reason": "Демо: внутренний стоп-лист"}
            if is_company and requested and requested.internal_stop_list
            else None,
        }
        if is_company:
            for source in result.get("bankLoans", []):
                if source["inn"] != inn:
                    raise ValueError("Кредиты нашего банка допустимы только у компании или ИП")
                if body.get("customer") is None:
                    raise ValueError("Для кредитов нашего банка нужен клиент bankCore")
                loans = body.setdefault("loans", [])
                for loan in source["body"]["loans"]:
                    found = next(
                        (x for x in loans if x["contractUid"] == loan["contractUid"]), None
                    )
                    if found is not None and found != loan:
                        raise ValueError("Противоречивые кредиты с одним contractUid")
                    if found is None:
                        loans.append(deepcopy(loan))


def expand_other(
    spec: ScenarioSpec,
    expanded: dict[str, Any],
    code: str,
    today: date,
    bank_bik: str = "040000999",
) -> dict[str, Any]:
    """Вход spec уже объединён с пресетом; выход пригоден для следующих стадий T-126/T-127."""
    result = deepcopy(expanded)
    add_cases(spec, result, code, today)
    add_contracts(spec, result, code, today)
    add_tax(spec, result, code, today, bank_bik)
    _compliance(spec, result, today)
    result["registry"] = RegistryBody.model_validate(result["registry"]).model_dump(
        mode="json", by_alias=True
    )
    result["tax"] = TaxBody.model_validate(result.get("tax", {})).model_dump(
        mode="json", by_alias=True
    )
    result["bankCore"] = BankCoreBody.model_validate(result.get("bankCore", {})).model_dump(
        mode="json", by_alias=True
    )
    for entry in result["bki"]:
        entry["body"] = BkiSubjectBody.model_validate(entry["body"]).model_dump(
            mode="json", by_alias=True
        )
    for entry in result["bankSubjects"]:
        entry["body"] = BankCoreBody.model_validate(entry["body"]).model_dump(
            mode="json", by_alias=True
        )
    # Чистый человек не имеет строки в справочниках АБС: screening вернёт CLEAR без PUT.
    # PUT пустого тела не создаёт ресурса, поэтому общий admin ответил бы 404 после записи.
    result["bankSubjects"] = [
        entry
        for entry in result["bankSubjects"]
        if any(entry["body"].get(key) for key in ("customer", "accounts", "turnover", "loans"))
        or any((entry["body"].get("compliance") or {}).values())
    ]
    return result
