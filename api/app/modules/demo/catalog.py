"""Шпаргалка персон: только разрешённые поля реального сервиса сценариев."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.modules import companies
from app.modules.integrations import scenarios
from app.shared.errors import AppError


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PersonaRequest(Camel):
    product_code: str | None
    amount_rub: str
    term_months: int | None


class Persona(Camel):
    code: str
    title: str
    inn: str | None = None
    company_id: UUID | None = None
    status: str
    technical: bool
    application: PersonaRequest | None = None
    expected_outcome: str | None = None
    expected_final_outcome: str | None = None
    expected_reason_codes: list[str] = Field(default_factory=list)


def _persona(item: dict[str, Any]) -> Persona:
    view = scenarios.get_scenario(item["code"])
    code = view["code"]
    scope = companies.for_scenario(code)
    raw = view.get("application")
    application = None
    if raw:
        application = PersonaRequest(
            product_code=raw.get("productCode"),
            amount_rub=str(raw["amountRub"]),
            term_months=raw.get("termMonths"),
        )
    return Persona(
        code=code,
        title=view["title"],
        inn=view.get("inn"),
        company_id=scope.company_id if scope else None,
        status=view["status"],
        technical=code.startswith("t-"),
        application=application,
        expected_outcome=view.get("expectedOutcome"),
        expected_final_outcome=view.get("expectedFinalOutcome"),
        expected_reason_codes=view.get("expectedReasonCodes") or [],
    )


def list_personas() -> list[Persona]:
    try:
        items = scenarios.list_scenarios()
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(_persona, items))
    except (scenarios.ScenariosUnavailableError, ValueError, KeyError, TypeError) as exc:
        raise AppError(502, "DEMO_SCENARIOS_UNAVAILABLE") from exc
