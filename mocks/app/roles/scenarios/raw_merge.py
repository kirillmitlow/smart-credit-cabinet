"""T-126: raw перекрывает тела моков; отчётный год и список кредитов неделимы."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from app.common.admin import merge_patch
from app.roles.scenarios.bki_expand import subject_body
from app.roles.tax.schemas import FinancialRecord


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"RAW_SHAPE: {path} должен быть объектом")
    return value


def _financials(original: list[dict[str, Any]], replacements: Any) -> list[dict[str, Any]]:
    if not isinstance(replacements, list):
        raise ValueError("RAW_FINANCIAL_YEAR: raw.tax.financials должен быть списком годов")
    by_year = {record["year"]: record for record in original}
    seen: set[int] = set()
    for value in replacements:
        record = deepcopy(_object(value, "raw.tax.financials[]"))
        year = record.get("year")
        if not isinstance(year, int) or isinstance(year, bool) or not 1990 <= year < 9999:
            raise ValueError("RAW_FINANCIAL_YEAR: нужен год от 1990 до 9998")
        if year in seen:
            raise ValueError(f"RAW_FINANCIAL_YEAR: год {year} указан дважды")
        seen.add(year)
        # В примерах ScenarioSpec дата сдачи не задана; десять строк не наследуются.
        record.setdefault("submittedAt", date(year + 1, 3, 28).isoformat())
        try:
            parsed = FinancialRecord.model_validate(record)
        except ValueError as exc:
            raise ValueError(
                f"RAW_FINANCIAL_YEAR: год {year}, нужны полные согласованные строки: {exc}"
            ) from exc
        by_year[year] = parsed.model_dump(mode="json", by_alias=True)
    return [by_year[year] for year in sorted(by_year)]


def merge_raw(expanded: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(expanded)
    if not raw:
        return result
    allowed = {"registry", "tax", "bki", "bankCore", "bankSubjects"}
    if unknown := set(raw) - allowed:
        raise ValueError(f"RAW_SHAPE: неизвестные разделы raw: {', '.join(sorted(unknown))}")
    for key in ("registry", "bankCore"):
        if key in raw:
            result[key] = merge_patch(result[key], _object(raw[key], f"raw.{key}"))
    if "bankSubjects" in raw:
        if not isinstance(raw["bankSubjects"], list):
            raise ValueError("RAW_SHAPE: raw.bankSubjects должен быть списком субъектов")
        result["bankSubjects"] = deepcopy(raw["bankSubjects"])
    if "tax" in raw:
        patch = deepcopy(_object(raw["tax"], "raw.tax"))
        if "financials" in patch:
            result["tax"]["financials"] = _financials(
                result["tax"]["financials"], patch.pop("financials")
            )
        result["tax"] = merge_patch(result["tax"], patch)
    if "bki" in raw:
        patches = _object(raw["bki"], "raw.bki")
        by_inn = {entry["inn"]: entry for entry in result["bki"]}
        seen_patches: dict[str, dict[str, Any]] = {}
        for ref, value in patches.items():
            inn = result["identity"]["subjectRefs"].get(ref)
            if inn is None:
                raise ValueError(f"RAW_BKI_SUBJECT: отсутствует субъект {ref}")
            patch = _object(value, f"raw.bki.{ref}")
            # У директора-владельца или ИП нельзя тихо выбрать последний из двух блоков.
            previous = seen_patches.get(inn, {})
            for field in previous.keys() & patch.keys():
                if previous[field] != patch[field]:
                    raise ValueError(f"RAW_BKI_SUBJECT: противоречивый {field} одного ИНН {inn}")
            seen_patches[inn] = {**previous, **patch}
            if inn not in by_inn:
                entry = {"inn": inn, "body": {"subject": subject_body(result["identity"], inn)}}
                result["bki"].append(entry)
                by_inn[inn] = entry
            by_inn[inn]["body"] = merge_patch(by_inn[inn]["body"], patch)
    return result
