"""T-132, T-134: builtin → четыре настоящих мока → ответы содержат числа оракула 30-17."""

from typing import Any

import httpx
import pytest

from app.roles.scenarios import apply as transfer
from app.roles.scenarios import service
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.builtin_simple import (
    GARIPOV_INN,
    LEBEDEV_INN,
    MOROZOV_INN,
    ORLOV_INN,
    QUICK_START_INN,
    ROMASHKA_INN,
    SOKOLOV_INN,
    VEKTOR_INN,
)
from app.roles.scenarios.gateway import AdminGateway
from app.roles.scenarios.locking import locked_session
from app.roles.scenarios.schemas import ScenarioOrigin
from tests.scenarios_network import Harness
from tests.test_scenarios_apply import h as h
from tests.test_scenarios_apply import urls as urls

pytestmark = pytest.mark.integration


async def install(h: Harness) -> dict[str, dict[str, Any]]:
    """Все встроенные сценарии, как их создаёт стенд; результат — представления по коду."""
    app = h.apps["scenarios"]
    async with httpx.AsyncClient(transport=h.network) as remote:
        async with locked_session(app.state.database) as session:
            for spec in builtin_scenarios(app.state.clock.today(), app.state.settings.bank_bik):
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
    views = {}
    for item in (await h.api.get("/api/v1/scenarios")).json():
        views[item["code"]] = (await h.api.get(f"/api/v1/scenarios/{item['code']}")).json()
    return views


async def credit_report(h: Harness, subject: dict[str, Any]) -> dict[str, Any]:
    inn = subject["inn"]
    response = await h.clients["bki"].post(
        "/api/v1/credit-reports",
        json={
            "subject": subject,
            "purpose": "LOAN_APPLICATION",
            "consent": {
                "consentId": f"personas-{inn}",
                "subjectInn": inn,
                "signedAt": "2026-10-21T10:00:00Z",
                "validUntil": "2027-04-21",
                "purpose": "LOAN_APPLICATION",
            },
        },
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def subject_of(view: dict[str, Any], inn: str) -> dict[str, Any]:
    entry = next(e for e in view["expanded"]["bki"] if e["inn"] == inn)
    subject: dict[str, Any] = entry["body"]["subject"]
    return subject


async def test_all_five_personas_apply_and_are_listed_with_expected_outcomes(h: Harness) -> None:
    views = await install(h)
    assert sorted(views) == [
        "garipov",
        "orlov",
        "quick-start",
        "romashka",
        "snabkontrakt",
        "sokolova",
        "stankoprom",
        "vektor",
        "zarya",
    ]
    assert {c: v["status"] for c, v in views.items()} == dict.fromkeys(views, "APPLIED")
    assert all(v["origin"] == "BUILTIN" and v["builtinVersion"] == 1 for v in views.values())
    listing = {i["code"]: i for i in (await h.api.get("/api/v1/scenarios")).json()}
    assert {c: i["expectedOutcome"] for c, i in listing.items()} == {
        "snabkontrakt": "COUNTER_OFFER",
        "stankoprom": "MANUAL_REVIEW",
        "zarya": "MANUAL_REVIEW",
        "sokolova": "APPROVED",
        "vektor": "REJECTED",
        "orlov": "NOT_ELIGIBLE",
        "romashka": "REJECTED",
        "garipov": "NEEDS_INFO",
        "quick-start": "COUNTER_OFFER",
    }
    assert views["romashka"]["expectedReasonCodes"] == ["TAX_ARREARS_HIGH", "CURRENT_OVERDUE_90"]
    assert views["orlov"]["expectedReasonCodes"] == ["SELF_EMPLOYED"]
    assert views["garipov"]["expectedFinalOutcome"] == "APPROVED"
    assert views["quick-start"]["application"]["guarantor"] is None
    assert views["orlov"]["users"] == []
    assert [u["login"] for u in views["vektor"]["users"]] == ["lebedev"]
    assert [u["login"] for u in views["romashka"]["users"]] == ["morozov"]
    assert [u["login"] for u in views["quick-start"]["users"]] == ["sokolov"]
    assert views["quick-start"]["users"][0]["personRef"] == "owner"


async def test_applied_summary_matches_card_for_each_persona(h: Harness) -> None:
    views = await install(h)
    # в реестре самозанятый записан как человек (роли), но карточки ЕГРИП у него нет
    assert views["orlov"]["applied"] == {
        "registry": "OK",
        "tax": "OK",
        "bki": "SKIPPED",
        "bankCore": "SKIPPED",
    }
    for code in ("vektor", "romashka", "garipov"):
        assert views[code]["applied"] == {
            "registry": "OK",
            "tax": "OK",
            "bki": "OK",
            "bankCore": "OK",
        }, code
    # не клиент, но данные комплаенса есть → bankCore записан (Q-145/D-107), клиентом не стал
    for code in ("vektor", "romashka", "garipov"):
        customer = await h.clients["bank_core"].get(f"/api/v1/customers/{views[code]['inn']}")
        assert customer.status_code == 404, code
    assert views["quick-start"]["applied"]["bankCore"] == "OK"


async def test_vektor_registry_says_liquidating_and_tax_is_clean(h: Harness) -> None:
    await install(h)
    card = (await h.clients["registry"].get(f"/api/v1/companies/{VEKTOR_INN}")).json()
    assert card["status"]["code"] == "LIQUIDATING"
    assert card["address"]["unreliable"] is not None
    assert card["director"]["inn"] == LEBEDEV_INN
    tax = (await h.clients["tax"].get(f"/api/v1/tax-profile/{VEKTOR_INN}")).json()
    assert tax["taxRegimes"][0]["code"] == "USN_INCOME"
    assert tax["debts"]["taxDebtRub"] == 0
    assert (await h.clients["tax"].get(f"/api/v1/financials/{VEKTOR_INN}")).status_code == 404
    report = await credit_report(
        h,
        {
            "type": "LEGAL_ENTITY",
            "inn": VEKTOR_INN,
            "ogrn": card["ogrn"],
            "name": card["shortName"],
        },
    )
    summary = report["summary"]
    assert (summary["activeObligations"], summary["closedObligations"]) == (0, 1)
    assert summary["historyLengthMonths"] == 40
    assert summary["currentOverdueRub"] == summary["maxOverdueDays24m"] == 0
    assert (
        summary["inquiries30dExcludingOwn"],
        summary["rejectedApplications90dExcludingOwn"],
    ) == (
        0,
        0,
    )


async def test_orlov_is_missing_in_registry_but_npd_payer(h: Harness) -> None:
    await install(h)
    registry = await h.clients["registry"].get(f"/api/v1/companies/{ORLOV_INN}")
    assert registry.status_code == 404
    npd = await h.clients["tax"].post(
        "/api/v1/self-employed/status", json={"inn": ORLOV_INN, "requestDate": "2026-10-21"}
    )
    assert npd.status_code == 200
    assert npd.json()["status"] is True
    assert (await h.clients["tax"].get(f"/api/v1/tax-profile/{ORLOV_INN}")).status_code == 404
    assert (await h.clients["bank_core"].get(f"/api/v1/customers/{ORLOV_INN}")).status_code == 404
    report = await credit_report(
        h,
        {
            "type": "PERSON",
            "inn": ORLOV_INN,
            "lastName": "Орлов",
            "firstName": "Михаил",
            "birthDate": "1990-01-01",
        },
    )
    assert report["matchStatus"] == "NOT_FOUND"
    assert report["hasHistory"] is False


async def test_romashka_bki_report_matches_example_6_1(h: Harness) -> None:
    views = await install(h)
    report = await credit_report(h, subject_of(views["romashka"], ROMASHKA_INN))
    summary = report["summary"]
    assert (summary["activeObligations"], summary["closedObligations"]) == (2, 3)
    assert (summary["totalDebtRub"], summary["monthlyPaymentsRub"]) == (1813000, 318500)
    assert (summary["currentOverdueRub"], summary["currentOverdueDays"]) == (452000, 94)
    assert summary["maxOverdueDays24m"] == 94
    assert summary["restructurings24m"] == 0
    assert summary["inquiries30dExcludingOwn"] == 6
    assert summary["rejectedApplications90dExcludingOwn"] == 2
    assert summary["historyLengthMonths"] == 84
    first = next(o for o in report["obligations"] if o["overdueRub"] == 452000)
    assert (first["amountRub"], first["balanceRub"], first["monthlyPaymentRub"]) == (
        3000000,
        837000,
        113000,
    )
    assert first["overdueDays"] == 94
    # корзины: июль D1_29, август D30_59, сентябрь D60_89, октябрь D90_119
    tail = {p["month"]: p["status"] for p in first["paymentHistory"][-4:]}
    assert tail == {
        "2026-07": "D1_29",
        "2026-08": "D30_59",
        "2026-09": "D60_89",
        "2026-10": "D90_119",
    }
    second = next(o for o in report["obligations"] if o["balanceRub"] == 976000)
    assert (second["amountRub"], second["monthlyPaymentRub"], second["secured"]) == (
        4000000,
        205500,
        True,
    )
    director = await credit_report(h, subject_of(views["romashka"], MOROZOV_INN))
    assert director["summary"]["totalDebtRub"] == 0
    assert director["summary"]["currentOverdueDays"] == 0


async def test_romashka_tax_debt_is_over_ten_percent_and_statements_match_bki(h: Harness) -> None:
    await install(h)
    tax = (await h.clients["tax"].get(f"/api/v1/tax-profile/{ROMASHKA_INN}")).json()
    assert tax["debts"]["taxDebtRub"] == 1150000
    assert tax["debts"]["penaltiesRub"] == 42000
    statements = (await h.clients["tax"].get(f"/api/v1/financials/{ROMASHKA_INN}")).json()
    assert statements["year"] == 2025
    assert statements["formType"] == "SIMPLIFIED"
    lines = {code: pair["current"] for code, pair in statements["lines"].items()}
    assert (lines["2110"], lines["2330"], lines["1400"]) == (95000000, 600000, 500000)
    monthly = lines["2110"] / 12
    assert tax["debts"]["taxDebtRub"] / monthly > 0.10
    assert round(tax["debts"]["taxDebtRub"] / monthly * 100, 2) == 14.53
    sme = (await h.clients["tax"].get(f"/api/v1/sme-status/{ROMASHKA_INN}")).json()
    assert sme["category"] == "SMALL"
    assert (
        await h.clients["bank_core"].get(f"/api/v1/customers/{ROMASHKA_INN}")
    ).status_code == 404


async def test_garipov_has_no_statements_no_turnover_and_one_closed_loan(h: Harness) -> None:
    views = await install(h)
    statements = await h.clients["tax"].get(f"/api/v1/financials/{GARIPOV_INN}")
    assert statements.status_code == 404
    assert statements.json()["code"] == "STATEMENTS_NOT_FOUND"
    tax = (await h.clients["tax"].get(f"/api/v1/tax-profile/{GARIPOV_INN}")).json()
    assert tax["taxRegimes"][0]["code"] == "PSN"
    assert tax["incomeExpenses"] is None
    assert (await h.clients["bank_core"].get(f"/api/v1/customers/{GARIPOV_INN}")).status_code == 404
    turnover = await h.clients["bank_core"].get(f"/api/v1/customers/{GARIPOV_INN}/turnover")
    assert turnover.status_code == 404
    report = await credit_report(h, subject_of(views["garipov"], GARIPOV_INN))
    summary = report["summary"]
    assert (summary["activeObligations"], summary["closedObligations"]) == (0, 1)
    assert summary["historyLengthMonths"] == 48
    assert summary["totalDebtRub"] == summary["currentOverdueRub"] == 0


async def test_quick_start_company_has_no_bki_but_owner_is_clean(h: Harness) -> None:
    views = await install(h)
    company = await credit_report(
        h,
        {
            "type": "LEGAL_ENTITY",
            "inn": QUICK_START_INN,
            "ogrn": views["quick-start"]["ogrn"],
            "name": views["quick-start"]["shortName"],
        },
    )
    assert company["matchStatus"] == "NOT_FOUND"
    assert company["hasHistory"] is False
    owner = await credit_report(h, subject_of(views["quick-start"], SOKOLOV_INN))
    assert owner["matchStatus"] == "MATCHED"
    summary = owner["summary"]
    assert (summary["activeObligations"], summary["closedObligations"]) == (1, 1)
    assert summary["totalDebtRub"] == summary["currentOverdueDays"] == 0
    assert summary["historyLengthMonths"] == 60
    assert views["quick-start"]["director"]["inn"] == SOKOLOV_INN


async def test_quick_start_is_a_three_month_customer_with_flat_turnover(h: Harness) -> None:
    views = await install(h)
    customer = (await h.clients["bank_core"].get(f"/api/v1/customers/{QUICK_START_INN}")).json()
    assert customer["customerSince"] == "2026-07-21"
    turnover = (
        await h.clients["bank_core"].get(f"/api/v1/customers/{QUICK_START_INN}/turnover")
    ).json()
    months = turnover["months"]
    assert [m["month"] for m in months] == ["2026-07", "2026-08", "2026-09"]
    assert {(m["incomingNetRub"], m["outgoingRub"], m["counterpartiesIn"]) for m in months} == {
        (700000, 595000, 10)
    }
    account = views["quick-start"]["expanded"]["bankCore"]["accounts"][0]["number"]
    balance = await h.clients["bank_core"].get(f"/api/v1/accounts/{account}")
    assert balance.json()["balanceRub"] == 300000
    sme = (await h.clients["tax"].get(f"/api/v1/sme-status/{QUICK_START_INN}")).json()
    assert sme["category"] == "MICRO"
    assert sme["isNewlyCreated"] is True


async def test_reapply_returns_every_persona_to_its_initial_state(h: Harness) -> None:
    views = await install(h)
    for code in ("vektor", "orlov", "romashka", "garipov", "quick-start"):
        first = views[code]["expanded"]
        response = await h.api.post(f"/api/v1/scenarios/{code}/apply")
        assert response.status_code == 200, (code, response.text)
        assert response.json()["expanded"] == first, code
    assert (await h.api.delete("/api/v1/scenarios/romashka")).status_code == 409
