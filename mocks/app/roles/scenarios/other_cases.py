"""T-125: один источник дел ЕФРСБ и БКИ, с уже созданными личностями T-120."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.common.reldate import add_months
from app.roles.registry.schemas import BankruptcyRecord
from app.roles.scenarios.identity_people import rng_for
from app.roles.scenarios.schemas import ScenarioSpec


def _years_ago(today: date, years: float) -> date:
    value = Decimal(str(years))
    if not value.is_finite() or value < 0:
        raise ValueError("YearsAgo: нужно конечное неотрицательное число")
    months = int((value * 12).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    try:
        return add_months(today, -months)
    except ValueError as exc:
        raise ValueError("YearsAgo: дата дела вне допустимого календаря") from exc


def _subject(identity: dict[str, Any], inn: str) -> dict[str, Any]:
    if len(inn) == 10:
        return {
            "type": "LEGAL_ENTITY",
            "inn": inn,
            "ogrn": identity["ogrn"],
            "name": identity["shortName"],
        }
    person = next((p for p in identity["persons"] if p["inn"] == inn), None)
    if person is None:
        raise ValueError(f"В identity нет человека с ИНН {inn}")
    return {
        "type": "PERSON",
        **{k: person[k] for k in ("inn", "lastName", "firstName", "middleName", "birthDate")},
    }


def add_cases(spec: ScenarioSpec, result: dict[str, Any], code: str, today: date) -> None:
    identity = result["identity"]
    registry = result["registry"]
    subjects = result.setdefault("bki", [])
    by_inn = {entry["inn"]: entry["body"] for entry in subjects}
    if len(by_inn) != len(subjects):
        raise ValueError("В bki[] один субъект указан дважды")
    known_cases = {
        (entry["subjectInn"], entry["caseNumber"]): entry
        for entry in registry.setdefault("bankruptcies", [])
    }
    for index, requested in enumerate(spec.bankruptcies):
        inn = identity["subjectRefs"].get(requested.subject)
        if inn is None:
            raise ValueError(
                f"bankruptcies: неизвестный или отсутствующий субъект {requested.subject}"
            )
        started = _years_ago(today, requested.started_years_ago)
        completed = (
            _years_ago(today, requested.completed_years_ago)
            if requested.completed_years_ago is not None
            else None
        )
        rng = rng_for(code, f"bankruptcy:{inn}:{index}")
        number = f"А00-{rng.randint(10000, 99999)}/{started.year}"
        record = BankruptcyRecord.model_validate(
            {
                "caseNumber": number,
                "subjectType": "LEGAL_ENTITY" if len(inn) == 10 else "PERSON",
                "subjectInn": inn,
                "stage": requested.stage,
                "startedAt": started,
                "completedAt": completed,
            }
        ).model_dump(mode="json", by_alias=True)
        key = (inn, number)
        if key in known_cases and known_cases[key] != record:
            raise ValueError(f"Противоречивое дело {number} у {inn}")
        if key not in known_cases:
            registry["bankruptcies"].append(record)
            known_cases[key] = record
        if inn not in by_inn:
            body = {
                "subject": _subject(identity, inn),
                "obligations": [],
                "inquiries": [],
                "applications": [],
                "bankruptcies": [],
            }
            subjects.append({"inn": inn, "body": body})
            by_inn[inn] = body
        body = by_inn[inn]
        body.setdefault("bankruptcies", [])
        bki_case = {k: record[k] for k in ("caseNumber", "stage", "startedAt", "completedAt")}
        existing = next((x for x in body["bankruptcies"] if x["caseNumber"] == number), None)
        if existing is not None and existing != bki_case:
            raise ValueError(f"Дело {number} в БКИ расходится с ЕФРСБ")
        if existing is None:
            body["bankruptcies"].append(bki_case)
        body["bankruptcies"].sort(key=lambda x: (x["startedAt"], x["caseNumber"]), reverse=True)
    registry["bankruptcies"].sort(key=lambda x: (x["startedAt"], x["caseNumber"]), reverse=True)
    ongoing = [
        x
        for x in registry["bankruptcies"]
        if x["subjectInn"] == identity["inn"] and x["completedAt"] is None
    ]
    if ongoing and registry.get("entity") is not None:
        identity["status"] = "BANKRUPT"
        registry["entity"]["status"] = {
            "code": "BANKRUPT",
            "name": "Банкротство",
            "since": ongoing[0]["startedAt"],
        }
