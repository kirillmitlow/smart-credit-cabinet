"""T-131: builtin → четыре настоящих мока; часть входов TS-001 и сброса TS-101."""

import httpx
import pytest

from app.roles.scenarios import apply as transfer
from app.roles.scenarios import service
from app.roles.scenarios.builtin import SOKOLOVA_INN, builtin_scenarios
from app.roles.scenarios.credit_uid import contract_uid
from app.roles.scenarios.gateway import AdminGateway
from app.roles.scenarios.locking import locked_session
from app.roles.scenarios.schemas import ScenarioOrigin
from tests.scenarios_network import Harness
from tests.test_bank_core import disbursement
from tests.test_scenarios_apply import h as h
from tests.test_scenarios_apply import urls as urls

pytestmark = pytest.mark.integration


async def test_builtin_sokolova_is_visible_with_exact_inputs_and_resets(h: Harness) -> None:
    app = h.apps["scenarios"]
    spec = builtin_scenarios(app.state.clock.today(), app.state.settings.bank_bik)[0]
    async with httpx.AsyncClient(transport=h.network) as remote:
        async with locked_session(app.state.database) as session:
            row = await service.create(
                session,
                spec,
                app.state.clock,
                ScenarioOrigin.BUILTIN,
                bank_bik=app.state.settings.bank_bik,
            )
            await transfer.apply(
                session, row, AdminGateway(remote, app.state.settings), app.state.clock
            )
    view = (await h.api.get("/api/v1/scenarios/sokolova")).json()
    assert view["status"] == "APPLIED"
    assert view["origin"] == "BUILTIN"
    assert view["builtinVersion"] == 1
    assert view["application"]["amountRub"] == 500000
    assert view["application"]["productCode"] == "EXPRESS"
    assert view["expectedOutcome"] == "APPROVED"
    assert view["expectedReasonCodes"] == []
    assert len(view["users"]) == 1
    assert view["users"][0]["inn"] == SOKOLOVA_INN
    registry = await h.clients["registry"].get(f"/api/v1/companies/{SOKOLOVA_INN}")
    assert registry.status_code == 200, registry.text
    assert registry.json()["person"]["fullName"] == "Соколова Анна Сергеевна"
    tax = await h.clients["tax"].get(f"/api/v1/tax-profile/{SOKOLOVA_INN}")
    assert tax.status_code == 200
    assert tax.json()["debts"]["taxDebtRub"] == 0
    turnover = await h.clients["bank_core"].get(f"/api/v1/customers/{SOKOLOVA_INN}/turnover")
    assert turnover.status_code == 200
    assert len(turnover.json()["months"]) == 12
    assert {
        (m["incomingNetRub"], m["outgoingRub"], m["counterpartiesIn"])
        for m in turnover.json()["months"]
    } == {(905000, 795000, 2)}
    report = await h.clients["bki"].post(
        "/api/v1/credit-reports",
        json={
            "subject": view["expanded"]["bki"][0]["body"]["subject"],
            "purpose": "LOAN_APPLICATION",
            "consent": {
                "consentId": "sokolova-check",
                "subjectInn": SOKOLOVA_INN,
                "signedAt": "2026-10-21T10:00:00Z",
                "validUntil": "2026-11-21",
                "purpose": "LOAN_APPLICATION",
            },
        },
    )
    assert report.status_code == 200, report.text
    summary = report.json()["summary"]
    assert (summary["activeObligations"], summary["closedObligations"]) == (1, 1)
    assert (summary["totalDebtRub"], summary["monthlyPaymentsRub"]) == (60000, 3000)
    assert summary["historyLengthMonths"] == 30
    assert summary["currentOverdueRub"] == summary["currentOverdueDays"] == 0
    assert summary["inquiries30dExcludingOwn"] == 0
    account = view["expanded"]["bankCore"]["accounts"][0]["number"]
    issued = await h.clients["bank_core"].post(
        "/api/v1/disbursements",
        json=disbursement(
            account,
            contract={
                "number": "DEMO",
                "uid": contract_uid("sokolova", SOKOLOVA_INN, "runtime"),
                "signedAt": "2026-10-21T10:00:00Z",
            },
        ),
        headers={"Idempotency-Key": "sokolova-issue"},
    )
    assert issued.status_code == 201, issued.text
    assert (await h.api.post("/api/v1/scenarios/sokolova/apply")).status_code == 200
    reset = await h.clients["bank_core"].get(f"/api/v1/accounts/{account}")
    assert reset.json()["balanceRub"] == 412300
    assert (await h.clients["bank_core"].get(f"/api/v1/customers/{SOKOLOVA_INN}/loans")).json()[
        "loans"
    ] == []
    assert (
        await h.clients["bki"].get(f"/api/v1/credit-reports/{report.json()['reportId']}")
    ).status_code == 404
    assert (await h.api.delete("/api/v1/scenarios/sokolova")).status_code == 409
