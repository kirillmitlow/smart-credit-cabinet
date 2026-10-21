"""T-126: каждое нарушение из реестра доходит до HTTP 422."""

from copy import deepcopy
from typing import Any

import httpx
import pytest

from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.expand import expand
from app.roles.scenarios.validators import RULES
from tests.test_scenarios_consistency import MUTATIONS, TODAY, scenario
from tests.test_scenarios_preview import client, scenarios_url  # noqa: F401 — pytest fixtures

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("rule_code", [r.code for r in RULES])
async def test_rule_violation_is_a_problem_response(
    client: httpx.AsyncClient,  # noqa: F811 — импортированная pytest fixture
    rule_code: str,
) -> None:
    spec = scenario().model_copy(update={"code": f"http-{rule_code.lower().replace('_', '-')}"})
    data = expand(spec, TODAY, settings=ScenarioSettings(bank_bik="040000111"))
    body = spec.model_dump(mode="json", by_alias=True, exclude_unset=True)
    changed = deepcopy(data)
    raw: dict[str, Any] = {}
    if rule_code in MUTATIONS:
        path, value = MUTATIONS[rule_code]
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = deepcopy(value)
        root = path[0]
        if root == "identity":
            body["company"]["form"] = "IP"
        elif root == "bki":
            raw["bki"] = {"company": changed["bki"][0]["body"]}
        else:
            raw[str(root)] = changed[root]
        if rule_code == "BANKRUPTCY_MATCH":
            raw["registry"]["bankruptcies"][0].update(
                subjectInn=data["identity"]["inn"], subjectType="LEGAL_ENTITY"
            )
        elif rule_code == "BANKRUPTCY_DATES":
            case = raw["registry"]["bankruptcies"][0]
            case.update(
                subjectInn=data["identity"]["inn"], subjectType="LEGAL_ENTITY", stage="OBSERVATION"
            )
            raw["bki"] = {
                "company": {
                    "bankruptcies": [
                        {k: case[k] for k in ("caseNumber", "stage", "startedAt", "completedAt")}
                    ]
                }
            }
        elif rule_code == "OUR_BANK_UID":
            body["bki"]["company"]["activeLoans"][0]["ourBank"] = True
            raw = {"bankCore": {"loans": []}}
    elif rule_code == "TURNOVER_REVENUE":
        for row in changed["bankCore"]["turnover"]:
            row["incomingRub"] *= 2
            row["incomingNetRub"] *= 2
        raw["bankCore"] = changed["bankCore"]
    elif rule_code == "NON_CUSTOMER_DATA":
        body["bank"] = {"isCustomer": False}
        raw["bankCore"] = changed["bankCore"]
    elif rule_code == "REGIME_LIMITS":
        raw["tax"] = {
            "taxProfile": {
                "taxRegimes": [{"year": 2025, "code": "AUSN"}],
                "avgHeadcount": {"year": 2025, "value": 6},
            }
        }
    elif rule_code == "STATEMENT_DEBT":
        record = changed["tax"]["financials"][-1]
        lines = record["lines"]
        delta = 3000001 - lines["1400"]
        lines["1400"] += delta
        lines["1200"] += delta
        lines["1600"] += delta
        raw["tax"] = {"financials": [record]}
    elif rule_code == "LOAN_LOCATION":
        body["activeLoans"] = [{"kind": "LOAN", "amountRub": 1000000}]
    response = await client.post("/api/v1/scenarios/preview", json={**body, "raw": raw})
    assert response.status_code == 422, (rule_code, response.text)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert len(response.json()["detail"]) > 20
