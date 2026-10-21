"""T-124: арифметика Ромашки, просрочки и результат настоящего API БКИ."""

from asyncio import to_thread
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.common.clock import Clock
from app.main import create_app
from app.roles.bki import calc
from app.roles.bki.admin import BkiAdminHandler
from app.roles.bki.schemas import BkiSubjectBody
from app.roles.scenarios.bki_expand import expand_bki
from app.roles.scenarios.identity import expand_identity
from app.roles.scenarios.schemas import ScenarioSpec
from tests.conftest import ADMIN_KEY, database_url, make_settings

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 6, 12, 5, tzinfo=UTC)


def generate(block: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    spec = ScenarioSpec.model_validate(
        {
            "title": "Ромашка",
            "company": {"form": "LLC", "ageMonths": 120},
            "bki": {"company": block},
            **kwargs,
        }
    )
    identity = expand_identity(spec, "advanced", TODAY, set())["identity"]
    result = expand_bki(spec, identity, "advanced", TODAY)
    item = result["bki"][0]
    BkiAdminHandler().check(item["inn"], BkiSubjectBody.model_validate(item["body"]))
    return item


def facts(body: dict[str, Any]) -> list[calc.ObligationFacts]:
    return [
        calc.ObligationFacts(
            o["kind"],
            o["role"],
            o["status"],
            date.fromisoformat(o["openedAt"]),
            date.fromisoformat(o["closedAt"]) if o["closedAt"] else None,
            o["balanceRub"],
            o["monthlyPaymentRub"],
            o["overdueRub"],
            [
                calc.Period(
                    date.fromisoformat(p["since"]),
                    date.fromisoformat(p["until"]) if p["until"] else None,
                )
                for p in o["overduePeriods"]
            ],
        )
        for o in body["obligations"]
    ]


def romashka() -> dict[str, Any]:
    return {
        "historyYears": 7,
        "currentOverdueDays": 94,
        "inquiries30d": 6,
        "rejectedApplications90d": 2,
        "activeLoans": [
            {
                "kind": "LOAN",
                "amountRub": 3000000,
                "termMonths": 36,
                "ratePercent": 21,
                "openedAt": "2024-02-18",
            },
            {
                "kind": "LOAN",
                "amountRub": 4000000,
                "termMonths": 24,
                "ratePercent": 21,
                "openedAt": "2025-03-05",
                "secured": True,
            },
        ],
        "closedLoans": [
            {
                "kind": "LOAN",
                "amountRub": 100000,
                "openedAt": "2019-10-20",
                "closedAt": "2020-10-20",
            },
            {
                "kind": "LOAN",
                "amountRub": 200000,
                "openedAt": "2021-10-20",
                "closedAt": "2022-10-20",
            },
            {
                "kind": "LOAN",
                "amountRub": 300000,
                "openedAt": "2023-10-20",
                "closedAt": "2024-10-20",
            },
        ],
    }


def test_romashka_arithmetic_and_history_match_spec() -> None:
    body = generate(romashka())["body"]
    first, second = body["obligations"][:2]
    assert first["overduePeriods"] == [{"since": "2026-07-18", "until": None}]
    assert first["monthlyPaymentRub"] == 113000
    assert first["balanceRub"] == 837000
    assert first["overdueRub"] == 452000
    assert second["monthlyPaymentRub"] == 205500
    assert second["balanceRub"] == 976000
    history = calc.payment_history(date(2024, 2, 18), None, [calc.Period(date(2026, 7, 18))], TODAY)
    assert history[-4:] == [
        ("2026-07", "D1_29"),
        ("2026-08", "D30_59"),
        ("2026-09", "D60_89"),
        ("2026-10", "D90_119"),
    ]
    summary = calc.summarize(
        facts(body),
        [calc.InquiryFacts(date.fromisoformat(i["date"]), i["isOwn"]) for i in body["inquiries"]],
        [
            calc.ApplicationFacts(
                date.fromisoformat(a["date"]),
                date.fromisoformat(a["decisionDate"]),
                a["decision"],
                a["isOwn"],
            )
            for a in body["applications"]
        ],
        TODAY,
        5,
    )
    assert summary.total_debt_rub == 1813000
    assert summary.monthly_payments_rub == 318500
    assert summary.closed_obligations == 3
    assert summary.history_length_months == 84
    assert summary.current_overdue_days == 94
    assert summary.max_overdue_days_24m == 94
    assert summary.inquiries_30d_excluding_own == 6
    assert summary.rejected_applications_90d_excluding_own == 2


@pytest.mark.parametrize(("days", "bucket"), [(45, "D30_59"), (95, "D90_119")])
def test_overdue_buckets_and_clock_advance(days: int, bucket: str) -> None:
    body = generate(
        {"currentOverdueDays": days, "activeLoans": [{"kind": "LOAN", "amountRub": 1000000}]}
    )["body"]
    fact = facts(body)[0]
    assert calc.payment_history(fact.opened_at, None, fact.periods, TODAY)[-1][1] == bucket
    assert calc.overdue_days_at(fact.periods, TODAY + timedelta(days=7)) == days + 7
    assert (
        body["obligations"][0]["overduePeriods"][0]["since"]
        == (TODAY - timedelta(days=days)).isoformat()
    )


def test_explicit_overdue_amount_overrides_schedule() -> None:
    body = generate(
        {
            "currentOverdueDays": 45,
            "currentOverdueRub": 12345,
            "activeLoans": [{"kind": "LOAN", "amountRub": 1000000}],
        }
    )["body"]
    assert body["obligations"][0]["overdueRub"] == 12345


def test_unpaid_on_due_date_does_not_reduce_balance() -> None:
    body = generate(
        {
            "currentOverdueDays": 30,
            "activeLoans": [
                {
                    "kind": "LOAN",
                    "amountRub": 240000,
                    "termMonths": 24,
                    "ratePercent": 0,
                    "openedAt": "2025-10-20",
                }
            ],
        }
    )["body"]
    # 20 сентября — в периоде неоплаты; оплачены лишь 10 платежей до 20 августа.
    assert body["obligations"][0]["balanceRub"] == 140000
    assert body["obligations"][0]["overdueRub"] == 20000


def test_past_overdue_does_not_create_current_debt() -> None:
    body = generate({"historyYears": 3, "pastMaxOverdueDays": 61})["body"]
    summary = calc.summarize(facts(body), [], [], TODAY, 5)
    assert summary.max_overdue_days_24m == 61
    assert summary.current_overdue_days == 0
    assert summary.current_overdue_rub == 0
    assert all(p["until"] is not None for o in body["obligations"] for p in o["overduePeriods"])


def test_restructuring_count_and_collectors_do_not_overwrite_each_other() -> None:
    body = generate({"restructurings24m": 3, "soldToCollectors": True})["body"]
    summary = calc.summarize(facts(body), [], [], TODAY, 5)
    assert summary.restructurings_24m == 3
    assert sum(o["status"] == "SOLD_TO_COLLECTORS" for o in body["obligations"]) == 1


@pytest.mark.parametrize(
    ("block", "message"),
    [
        (
            {"currentOverdueDays": 1000, "activeLoans": [{"kind": "LOAN", "amountRub": 100000}]},
            "раньше открытия",
        ),
        ({"currentOverdueDays": 45}, "activeLoans"),
        ({"currentOverdueRub": 123}, "currentOverdueDays"),
        ({"pastMaxOverdueDays": 800}, "24 месяца"),
        ({"historyYears": 0, "inquiries30d": 1}, "historyYears"),
    ],
)
def test_contradictions_are_rejected(block: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        generate(block)


@pytest.mark.integration
async def test_generated_romashka_through_real_bki(postgres_url: str) -> None:
    url = await to_thread(database_url, postgres_url, "mock_bki_scenarios_advanced")
    app = create_app(make_settings(mock_role="bki", mock_api_keys="api:bki-test", database_url=url))
    await app.state.database.migrate()
    app.state.clock = Clock(TODAY, real_now=lambda: NOW)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    item = generate(romashka())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
            assert (
                await client.post("/admin/wipe", headers={"X-Admin-Key": ADMIN_KEY})
            ).status_code == 204
            response = await client.put(
                f"/admin/subjects/{item['inn']}",
                headers={"X-Admin-Key": ADMIN_KEY, "X-Scenario-Code": "romashka-generated"},
                json=item["body"],
            )
            assert response.status_code in (200, 201), response.text
            request = {
                "subject": item["body"]["subject"],
                "purpose": "LOAN_APPLICATION",
                "consent": {
                    "consentId": "generated-consent",
                    "subjectInn": item["inn"],
                    "signedAt": NOW.isoformat(),
                    "validUntil": "2027-04-20",
                    "purpose": "LOAN_APPLICATION",
                },
            }
            response = await client.post(
                "/api/v1/credit-reports", headers={"X-Api-Key": "bki-test"}, json=request
            )
            assert response.status_code == 200, response.text
            report = response.json()
            summary = report["summary"]
            assert summary["activeObligations"] == 2
            assert summary["closedObligations"] == 3
            assert summary["totalDebtRub"] == 1813000
            assert summary["monthlyPaymentsRub"] == 318500
            assert summary["currentOverdueRub"] == 452000
            assert summary["currentOverdueDays"] == 94
            assert summary["inquiries30d"] == 7
            assert summary["inquiries30dExcludingOwn"] == 6
            assert summary["rejectedApplications90dExcludingOwn"] == 2
            app.state.clock = Clock(
                TODAY + timedelta(days=1), real_now=lambda: NOW + timedelta(days=1)
            )
            later = await client.post(
                "/api/v1/credit-reports", headers={"X-Api-Key": "bki-test"}, json=request
            )
            assert later.status_code == 200, later.text
            assert later.json()["summary"]["currentOverdueDays"] == 95
            saved = await client.get(
                f"/api/v1/credit-reports/{report['reportId']}", headers={"X-Api-Key": "bki-test"}
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["summary"]["currentOverdueDays"] == 94
    finally:
        await app.state.database.dispose()


def test_current_and_past_overdue_periods_do_not_overlap() -> None:
    body = generate(
        {
            "currentOverdueDays": 45,
            "pastMaxOverdueDays": 30,
            "activeLoans": [{"kind": "LOAN", "amountRub": 1000000}],
        }
    )["body"]
    periods = body["obligations"][0]["overduePeriods"]
    assert len(periods) == 2
    assert periods[0]["until"] < periods[1]["since"]
    summary = calc.summarize(facts(body), [], [], TODAY, 5)
    assert summary.current_overdue_days == 45
    assert summary.max_overdue_days_24m == 45


def test_problem_debtor_preset_is_supported() -> None:
    from app.roles.scenarios.expand import resolved_spec

    spec = resolved_spec(ScenarioSpec(title="Должник", preset="PROBLEM_DEBTOR"))
    identity = expand_identity(spec, "debtor", TODAY, set())["identity"]
    output = expand_bki(spec, identity, "debtor", TODAY)
    company = next(item["body"] for item in output["bki"] if item["inn"] == identity["inn"])
    summary = calc.summarize(facts(company), [], [], TODAY, 5)
    assert summary.current_overdue_days == 94
    assert summary.current_overdue_rub > 0


def test_own_bank_unpaid_instalments_keep_exact_ruble_balance() -> None:
    body = generate(
        {
            "currentOverdueDays": 30,
            "activeLoans": [
                {
                    "kind": "LOAN",
                    "amountRub": 500000,
                    "termMonths": 12,
                    "ratePercent": 24,
                    "openedAt": "2026-04-20",
                    "ourBank": True,
                },
            ],
        },
        bank={"isCustomer": True},
    )["body"]
    # Сентябрьский платёж перенесён с воскресенья на 21-е и не оплачен.
    assert body["obligations"][0]["balanceRub"] == 346346
    assert body["obligations"][0]["monthlyPaymentRub"] == 47280
    assert body["obligations"][0]["overdueRub"] == 94560
