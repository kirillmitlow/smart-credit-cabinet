"""T-370: один запрос создаёт сценарий в моках и синхронизирует компанию через владельца."""

from hashlib import sha256
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.modules import audit, companies
from app.modules.demo.catalog import Camel, Persona, project_persona
from app.modules.integrations import scenarios
from app.shared import db, idempotency, operations
from app.shared.errors import AppError


class ScenarioAccount(Camel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    role: Literal["DIRECTOR", "ACCOUNTANT", "GUARANTOR"]
    person_ref: str | None = None
    full_name: str | None = Field(default=None, max_length=200)
    inn: str | None = Field(default=None, pattern=r"^\d{12}$")
    power_of_attorney: bool | None = None


class ScenarioInput(Camel):
    # Остальные разделы ScenarioSpec проверяет его владелец, mock-scenarios; схему не копируем.
    model_config = ConfigDict(extra="allow")
    title: str = Field(min_length=1, max_length=300)
    code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    users: list[ScenarioAccount] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_fit(self) -> Self:
        if self.code and any(len(f"{self.code}:{u.login}") > 100 for u in self.users):
            raise ValueError(
                "Суммарная длина code, разделителя и users.login не должна превышать 100"
            )
        return self


class AppliedSystems(Camel):
    registry: Literal["OK", "SKIPPED"]
    tax: Literal["OK", "SKIPPED"]
    bki: Literal["OK", "SKIPPED"]
    bank_core: Literal["OK", "SKIPPED"]


class CreatedScenario(Camel):
    persona: Persona
    applied: AppliedSystems


def _action(session: Session, spec: dict[str, Any], key: str) -> idempotency.Reply:
    upstream_spec = dict(spec)
    if upstream_spec.get("code") is None:
        # Даже если мок успел сохранить FAILED и не закэшировал 502, повтор не создаст второй код.
        upstream_spec["code"] = "demo-api-" + sha256(key.encode()).hexdigest()[:24]
    try:
        view = scenarios.create_scenario(upstream_spec, idempotency_key=key)
    except scenarios.ScenarioRejectedError as exc:
        headers = {"Retry-After": "1"} if exc.code == "IDEMPOTENCY_IN_PROGRESS" else None
        raise AppError(exc.status, exc.code, headers=headers) from exc
    except scenarios.ScenariosUnavailableError as exc:
        raise AppError(502, "DEMO_SCENARIOS_UNAVAILABLE") from exc
    # Подтверждаем полный результат до любых локальных записей и не раскрываем spec/users.
    try:
        if view["code"] != upstream_spec["code"] or view["status"] != "APPLIED":
            raise ValueError("Сценарий не соответствует запросу")
        applied = AppliedSystems.model_validate(view["applied"])
        project_persona(view, None)
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise AppError(502, "DEMO_SCENARIO_INVALID_RESPONSE") from exc
    with operations.hold(lambda: companies.for_scenario(view["code"])):
        company = companies.apply_scenario(session, view)
        if company is None:
            raise AppError(502, "DEMO_SCENARIO_INVALID_RESPONSE")
        result = CreatedScenario(persona=project_persona(view, company.id), applied=applied)
        audit.record(
            session,
            "DEMO_SCENARIO_CREATED",
            company_id=company.id,
            object_type="SCENARIO",
            object_id=view["code"],
        )
    return idempotency.Reply(201, result.model_dump(mode="json", by_alias=True))


def create(spec: dict[str, Any], key: str) -> idempotency.Reply:
    """Сбой после внешнего commit повторяется с тем же ключом, а не создаёт компанию второй раз."""
    with operations.hold(lambda: None), db.transaction() as session:
        return idempotency.run_once(
            session,
            scope="demo:scenarios:create",
            key=key,
            request=spec,
            action=lambda: _action(session, spec, key),
        )
