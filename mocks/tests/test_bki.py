"""T-112..T-114 (интеграция): mock-credit-bureau на живом Postgres (раздел 6 спецификации)."""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.common.clock import Clock
from app.main import create_app
from tests.conftest import ADMIN_KEY, database_url, make_settings

pytestmark = pytest.mark.integration

BKI_KEY = "dev-bki-key"
TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 6, 12, 5, tzinfo=UTC)  # 09:12 МСК

ROMASHKA = "0015557771"
SNAB = "0012345673"
OWNER = "001234567887"  # человек
DIRECTOR = "001310000436"  # человек
NO_HISTORY = "0017654322"


def clock_at(day: date, moment: datetime = NOW) -> Clock:
    return Clock(day, real_now=lambda: moment)


@pytest.fixture(scope="module")
def bki_url(postgres_url: str) -> str:
    return database_url(postgres_url, "mock_bki_test")


@pytest.fixture
async def app(bki_url: str) -> AsyncIterator[FastAPI]:
    app = create_app(
        make_settings(mock_role="bki", mock_api_keys=f"api:{BKI_KEY}", database_url=bki_url)
    )
    await app.state.database.migrate()
    app.state.clock = clock_at(TODAY)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Admin-Key": ADMIN_KEY}
    ) as c:
        assert (await c.post("/admin/wipe")).status_code == 204
    yield app
    await app.state.database.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Api-Key": BKI_KEY}
    ) as c:
        yield c


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Admin-Key": ADMIN_KEY}
    ) as c:
        yield c


# ---------- данные ----------


def spec_romashka_body() -> dict[str, Any]:
    """Пример тела PUT из 8.3 (mock-credit-bureau) без изменений."""
    return {
        "subject": {
            "type": "LEGAL_ENTITY",
            "inn": ROMASHKA,
            "ogrn": "1190000007890",
            "name": "ООО «Ромашка»",
        },
        "obligations": [
            {
                "uid": "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4",
                "kind": "LOAN",
                "role": "BORROWER",
                "openedAt": "2024-02-18",
                "plannedCloseAt": "2027-02-18",
                "closedAt": None,
                "amountRub": 3000000,
                "limitRub": None,
                "balanceRub": 837000,
                "monthlyPaymentRub": 113000,
                "overdueRub": 452000,
                "overduePeriods": [{"since": "2026-07-18", "until": None}],
                "status": "ACTIVE",
                "secured": False,
            }
        ],
        "inquiries": [
            {
                "date": "2026-10-14",
                "userType": "BANK",
                "purpose": "LOAN_APPLICATION",
                "isOwn": False,
            }
        ],
        "applications": [
            {
                "date": "2026-10-14",
                "kind": "LOAN",
                "amountRub": 2000000,
                "decision": "REJECTED",
                "decisionDate": "2026-10-15",
                "isOwn": False,
            }
        ],
        "bankruptcies": [],
    }


def closed_loan(uid: str, opened: str, closed: str) -> dict[str, Any]:
    return {
        "uid": uid,
        "kind": "LOAN",
        "openedAt": opened,
        "plannedCloseAt": closed,
        "closedAt": closed,
        "amountRub": 1_000_000,
        "balanceRub": 0,
        "monthlyPaymentRub": 0,
        "status": "CLOSED",
    }


def full_romashka_body() -> dict[str, Any]:
    """Ромашка из примера 6.1: итоги summary совпадают с примером при APP_TODAY=2026-10-20."""
    body = spec_romashka_body()
    body["obligations"].append(
        {
            "uid": "2c7e5d90-81a3-4c1b-b4f2-7a9d3e6c0b15-1",
            "kind": "LOAN",
            "role": "BORROWER",
            "openedAt": "2025-03-05",
            "plannedCloseAt": "2027-03-05",
            "amountRub": 4000000,
            "balanceRub": 976000,
            "monthlyPaymentRub": 205500,
            "secured": True,
        }
    )
    body["obligations"] += [
        closed_loan("c1-0001", "2019-10-15", "2021-10-15"),  # самое раннее: 84 месяца истории
        closed_loan("c2-0002", "2021-01-10", "2022-01-10"),
        closed_loan("c3-0003", "2022-05-01", "2023-05-01"),
    ]
    # 6 чужих запросов за 30 дней (в окно) и один старый
    body["inquiries"] = [
        {"date": d, "userType": "BANK", "purpose": "LOAN_APPLICATION"}
        for d in (
            "2026-10-14",
            "2026-10-10",
            "2026-10-05",
            "2026-10-01",
            "2026-09-28",
            "2026-09-22",
        )
    ] + [{"date": "2026-08-01", "userType": "MFO", "purpose": "LOAN_APPLICATION"}]
    body["applications"].append(
        {
            "date": "2026-09-02",
            "kind": "LOAN",
            "amountRub": 1500000,
            "decision": "REJECTED",
            "decisionDate": "2026-09-04",
        }
    )
    body["applications"].append(  # старше 90 дней — в сводку не входит
        {
            "date": "2026-05-01",
            "kind": "LOAN",
            "amountRub": 500000,
            "decision": "REJECTED",
            "decisionDate": "2026-05-03",
        }
    )
    return body


async def put_subject(
    admin: httpx.AsyncClient, inn: str, body: dict[str, Any], scenario: str | None = "test"
) -> httpx.Response:
    headers = {"X-Scenario-Code": scenario} if scenario else {}
    response = await admin.put(f"/admin/subjects/{inn}", json=body, headers=headers)
    assert response.status_code in (200, 201), response.text
    return response


def consent(inn: str, clock: Clock | None = None, **over: Any) -> dict[str, Any]:
    now = (clock or clock_at(TODAY)).now()
    value: dict[str, Any] = {
        "consentId": "cns_01JAK8M2W7",
        "subjectInn": inn,
        "signedAt": (now - timedelta(minutes=7)).isoformat().replace("+00:00", "Z"),
        "validUntil": "2027-04-20",
        "purpose": "LOAN_APPLICATION",
        "signMethod": "SIMPLE_ESIGN",
        "signerInn": DIRECTOR,
        "textVersion": "bki-consent-v1",
    }
    value.update(over)
    return value


def subject_of(inn: str) -> dict[str, Any]:
    if len(inn) == 10:
        return {"type": "LEGAL_ENTITY", "inn": inn, "name": "ООО «Тест»"}
    return {"type": "PERSON", "inn": inn, "lastName": "Морозов", "firstName": "Олег"}


def report_request(inn: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "subject": subject_of(inn),
        "consent": consent(inn),
        "purpose": "LOAN_APPLICATION",
        "applicationRef": "APP-2026-000123",
    }
    body.update(over)
    return body


REPORTS = "/api/v1/credit-reports"
SUBMISSIONS = "/api/v1/submissions"


async def snapshot_runtime(admin: httpx.AsyncClient, inn: str) -> dict[str, Any]:
    response = await admin.get(f"/admin/subjects/{inn}")
    assert response.status_code == 200
    runtime: dict[str, Any] = response.json()["runtime"]
    return runtime


# ---------- T-112: согласие и запрос отчёта ----------


async def test_consent_reasons_each_have_own_code(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    cases = [
        ({"consent": None}, "CONSENT_MISSING"),
        ({"consent": consent(DIRECTOR)}, "CONSENT_SUBJECT_MISMATCH"),
        (
            {"consent": consent(ROMASHKA, signedAt="2026-10-20T09:30:00Z")},
            "CONSENT_NOT_YET_VALID",  # «сейчас» 09:12 МСК = 06:12 UTC
        ),
        ({"consent": consent(ROMASHKA, validUntil="2026-10-19")}, "CONSENT_EXPIRED"),
        ({"consent": consent(ROMASHKA, purpose="MONITORING")}, "CONSENT_PURPOSE_MISMATCH"),
    ]
    for override, code in cases:
        response = await client.post(REPORTS, json=report_request(ROMASHKA, **override))
        assert response.status_code == 403, code
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == code
    # Первая неудача в порядке проверок: нет согласия важнее прочего
    both = report_request(ROMASHKA, consent=consent(DIRECTOR, validUntil="2020-01-01"))
    assert (await client.post(REPORTS, json=both)).json()["code"] == "CONSENT_SUBJECT_MISMATCH"
    # Отказ по согласию следа в истории не оставляет
    assert (await snapshot_runtime(admin, ROMASHKA))["inquiries"] == []


async def test_consent_not_yet_valid_tolerates_five_minutes(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    now = app.state.clock.now()

    def at(delta: timedelta) -> dict[str, Any]:
        stamp = (now + delta).isoformat().replace("+00:00", "Z")
        return report_request(ROMASHKA, consent=consent(ROMASHKA, signedAt=stamp))

    assert (
        await client.post(REPORTS, json=at(timedelta(minutes=4, seconds=59)))
    ).status_code == 200
    late = await client.post(REPORTS, json=at(timedelta(minutes=5, seconds=1)))
    assert late.status_code == 403
    assert late.json()["code"] == "CONSENT_NOT_YET_VALID"
    # Подпись из прошлого и срок «до сегодня» включительно годятся
    ok = report_request(ROMASHKA, consent=consent(ROMASHKA, validUntil="2026-10-20"))
    assert (await client.post(REPORTS, json=ok)).status_code == 200


async def test_expiry_follows_app_today(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    app.state.clock = clock_at(date(2027, 4, 21))
    request = report_request(
        ROMASHKA,
        consent=consent(ROMASHKA, clock_at(date(2027, 4, 21)), validUntil="2027-04-20"),
    )
    assert (await client.post(REPORTS, json=request)).json()["code"] == "CONSENT_EXPIRED"


async def test_subject_type_must_fit_inn_length(client: httpx.AsyncClient) -> None:
    wrong_type = report_request(
        OWNER, subject={"type": "LEGAL_ENTITY", "inn": OWNER, "name": "ООО"}
    )
    response = await client.post(REPORTS, json=wrong_type)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    person_as_company = report_request(
        ROMASHKA, subject={"type": "PERSON", "inn": ROMASHKA, "lastName": "И"}
    )
    assert (await client.post(REPORTS, json=person_as_company)).status_code == 422


async def test_invalid_inn_is_400_and_broken_body_is_422(client: httpx.AsyncClient) -> None:
    bad_inn = report_request(ROMASHKA, subject=subject_of("0015557772"))
    response = await client.post(REPORTS, json=bad_inn)
    assert (response.status_code, response.json()["code"]) == (400, "INN_INVALID")
    missing = await client.post(REPORTS, json={"purpose": "LOAN_APPLICATION"})
    assert (missing.status_code, missing.json()["code"]) == (422, "VALIDATION_ERROR")
    naive = report_request(ROMASHKA, consent=consent(ROMASHKA, signedAt="2026-10-20T09:00:00"))
    assert (await client.post(REPORTS, json=naive)).status_code == 422


async def test_api_key_is_required(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        assert (await c.post(REPORTS, json={})).status_code == 401
        forbidden = await c.post(REPORTS, json={}, headers={"X-Api-Key": ADMIN_KEY})
        assert forbidden.status_code == 403


async def test_not_found_returns_zero_summary_and_still_leaves_a_trace(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    response = await client.post(REPORTS, json=report_request(NO_HISTORY))
    assert response.status_code == 200
    report = response.json()
    assert report["matchStatus"] == "NOT_FOUND"
    assert report["hasHistory"] is False
    assert report["bureauScore"] is None
    assert report["obligations"] == report["inquiries"] == []
    assert report["applications"] == report["bankruptcies"] == []
    summary = report["summary"]
    assert len(summary) == 14
    assert all(value == 0 for value in summary.values())  # нули, а не null
    assert report["meta"]["source"] == "CREDIT_BUREAU"
    assert report["meta"]["simulated"] is True
    # Когда субъект появится в БКИ, след виден в его отчётах (6.1)
    await put_subject(admin, NO_HISTORY, {"subject": subject_of(NO_HISTORY)})
    later = (await client.post(REPORTS, json=report_request(NO_HISTORY))).json()
    assert later["matchStatus"] == "MATCHED"
    assert later["hasHistory"] is False
    assert later["bureauScore"] is None
    assert [i["isOwn"] for i in later["inquiries"]] == [True, True]
    assert later["summary"]["inquiries30d"] == 2
    assert later["summary"]["inquiries30dExcludingOwn"] == 0


async def test_romashka_report_reproduces_spec_arithmetic(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, full_romashka_body())
    response = await client.post(REPORTS, json=report_request(ROMASHKA))
    assert response.status_code == 200
    report = response.json()
    assert report["matchStatus"] == "MATCHED"
    assert report["hasHistory"] is True
    assert report["reportId"].startswith("rep_")
    assert report["generatedAt"] == "2026-10-20T06:12:05Z"
    assert report["subject"]["name"] == "ООО «Ромашка»"
    assert report["summary"] == {
        "activeObligations": 2,
        "closedObligations": 3,
        "totalDebtRub": 1_813_000,
        "monthlyPaymentsRub": 318_500,
        "contingentLiabilitiesRub": 0,
        "currentOverdueRub": 452_000,
        "currentOverdueDays": 94,
        "maxOverdueDays24m": 94,
        "restructurings24m": 0,
        "inquiries30d": 7,  # 6 чужих и наш, только что сделанный
        "inquiries30dExcludingOwn": 6,
        "rejectedApplications90d": 2,
        "rejectedApplications90dExcludingOwn": 2,
        "historyLengthMonths": 84,
    }
    first = next(o for o in report["obligations"] if o["uid"].endswith("-4"))
    assert (first["balanceRub"], first["monthlyPaymentRub"], first["overdueRub"]) == (
        837_000,
        113_000,
        452_000,
    )
    assert first["overdueDays"] == 94
    assert first["paymentHistory"][-7:] == [
        {"month": "2026-04", "status": "OK"},
        {"month": "2026-05", "status": "OK"},
        {"month": "2026-06", "status": "OK"},
        {"month": "2026-07", "status": "D1_29"},
        {"month": "2026-08", "status": "D30_59"},
        {"month": "2026-09", "status": "D60_89"},
        {"month": "2026-10", "status": "D90_119"},
    ]
    assert len(first["paymentHistory"]) == 24
    second = next(o for o in report["obligations"] if o["uid"].endswith("-1"))
    assert second["overdueDays"] == 0
    assert {m["status"] for m in second["paymentHistory"]} == {"OK"}
    assert report["inquiries"][0] == {
        "date": "2026-10-20",
        "userType": "BANK",
        "purpose": "LOAN_APPLICATION",
        "isOwn": True,
    }
    assert 300 <= report["bureauScore"]["value"] <= 850
    assert report["bureauScore"]["scaleMin"] == 300
    # Название кредитора в отчёте не раскрывается
    assert "userName" not in report["inquiries"][0]


async def test_read_time_values_follow_app_today_without_touching_data(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, full_romashka_body())
    stored_before = (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()["data"]
    before = (await client.post(REPORTS, json=report_request(ROMASHKA))).json()

    app.state.clock = clock_at(TODAY + timedelta(days=30))
    request = report_request(ROMASHKA, consent=consent(ROMASHKA, app.state.clock))
    after = (await client.post(REPORTS, json=request)).json()

    assert after["summary"]["currentOverdueDays"] == 124
    assert after["summary"]["maxOverdueDays24m"] == 124
    first = next(o for o in after["obligations"] if o["uid"].endswith("-4"))
    assert first["overdueDays"] == 124
    assert first["paymentHistory"][-2:] == [
        {"month": "2026-10", "status": "D90_119"},  # на 31.10 — 105 дней
        {"month": "2026-11", "status": "D120_PLUS"},  # на 19.11 — 124
    ]
    # Окна сдвинулись: чужие запросы старше 30 дней выпали, остались два наших
    assert after["summary"]["inquiries30d"] == 2
    assert after["summary"]["inquiries30dExcludingOwn"] == 0
    assert after["summary"]["historyLengthMonths"] == before["summary"]["historyLengthMonths"] + 1
    # В базе по-прежнему даты и периоды, а не «замороженные» числа
    assert (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()["data"] == stored_before
    stored_loan = next(o for o in stored_before["obligations"] if o["uid"].endswith("-4"))
    assert stored_loan["overduePeriods"] == [{"since": "2026-07-18", "until": None}]


async def test_closed_overdue_period_is_history_not_current(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    body = spec_romashka_body()
    loan = body["obligations"][0]
    loan.update(
        overdueRub=0,
        overduePeriods=[{"since": "2026-03-10", "until": "2026-05-10"}],
    )
    await put_subject(admin, ROMASHKA, body)
    report = (await client.post(REPORTS, json=report_request(ROMASHKA))).json()
    assert report["summary"]["currentOverdueDays"] == 0
    assert report["summary"]["maxOverdueDays24m"] == 61
    history = {m["month"]: m["status"] for m in report["obligations"][0]["paymentHistory"]}
    assert (history["2026-03"], history["2026-04"], history["2026-05"]) == ("D1_29", "D30_59", "OK")


async def test_limit_kinds_and_contingent_liabilities(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    body: dict[str, Any] = {
        "subject": subject_of(OWNER),
        "obligations": [
            {
                "uid": "card-0001",
                "kind": "CREDIT_CARD",
                "openedAt": "2024-01-10",
                "limitRub": 300_000,
                "balanceRub": 90_000,
            },
            {
                "uid": "surety-0001",
                "kind": "SURETY",
                "role": "GUARANTOR",
                "openedAt": "2025-01-10",
                "amountRub": 2_000_000,
                "balanceRub": 1_500_000,
                "monthlyPaymentRub": 77_000,
            },
            {
                "uid": "coborrower-0001",
                "kind": "LOAN",
                "role": "CO_BORROWER",
                "openedAt": "2025-06-10",
                "amountRub": 1_000_000,
                "balanceRub": 700_000,
                "monthlyPaymentRub": 40_000,
            },
        ],
    }
    await put_subject(admin, OWNER, body)
    report = (await client.post(REPORTS, json=report_request(OWNER))).json()
    summary = report["summary"]
    assert summary["totalDebtRub"] == 790_000  # карта + созаёмщик, без поручительства
    assert summary["monthlyPaymentsRub"] == 4_500 + 40_000
    assert summary["contingentLiabilitiesRub"] == 1_500_000
    assert summary["activeObligations"] == 3
    by_uid = {o["uid"]: o for o in report["obligations"]}
    assert by_uid["card-0001"]["monthlyPaymentRub"] == 4_500
    assert by_uid["card-0001"]["limitRub"] == 300_000
    assert by_uid["surety-0001"]["monthlyPaymentRub"] is None
    assert report["subject"]["lastName"] == "Морозов"


async def test_explicit_payment_history_is_kept_as_is(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    body = spec_romashka_body()
    fixed = [{"month": "2026-08", "status": "OK"}, {"month": "2026-09", "status": "NO_DATA"}]
    body["obligations"][0]["paymentHistory"] = fixed
    await put_subject(admin, ROMASHKA, body)
    report = (await client.post(REPORTS, json=report_request(ROMASHKA))).json()
    assert report["obligations"][0]["paymentHistory"] == fixed
    data = (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()["data"]
    assert data["obligations"][0]["paymentHistory"] == fixed


async def test_idempotent_report_does_not_write_second_inquiry(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    headers = {"Idempotency-Key": "rep:APP-2026-000123:0015557771"}
    first = await client.post(REPORTS, json=report_request(ROMASHKA), headers=headers)
    second = await client.post(REPORTS, json=report_request(ROMASHKA), headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["reportId"] == second.json()["reportId"]
    assert second.headers["Idempotent-Replayed"] == "true"
    assert len((await snapshot_runtime(admin, ROMASHKA))["inquiries"]) == 1

    other = report_request(ROMASHKA, applicationRef="APP-2026-000999")
    conflict = await client.post(REPORTS, json=other, headers=headers)
    assert (conflict.status_code, conflict.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")

    # Без ключа каждый вызов — новый запрос и новый отчёт
    a = await client.post(REPORTS, json=report_request(ROMASHKA))
    b = await client.post(REPORTS, json=report_request(ROMASHKA))
    assert a.json()["reportId"] != b.json()["reportId"]
    assert len((await snapshot_runtime(admin, ROMASHKA))["inquiries"]) == 3
    assert b.json()["summary"]["inquiries30d"] == 4  # 1 чужой + 3 наших


async def test_parallel_report_requests_with_same_key_write_one_inquiry(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    headers = {"Idempotency-Key": f"rep-{uuid.uuid4()}"}
    responses = await asyncio.gather(
        *(client.post(REPORTS, json=report_request(ROMASHKA), headers=headers) for _ in range(6))
    )
    codes = [r.status_code for r in responses]
    assert set(codes) <= {200, 409}
    assert codes.count(200) >= 1
    for r in responses:
        if r.status_code == 409:
            assert r.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
            assert r.headers["Retry-After"] == "1"
    ids = {r.json()["reportId"] for r in responses if r.status_code == 200}
    assert len(ids) == 1
    assert len((await snapshot_runtime(admin, ROMASHKA))["inquiries"]) == 1


async def test_consent_is_stored_with_the_report(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    request = report_request(ROMASHKA)
    report = (await client.post(REPORTS, json=request)).json()
    async with app.state.database.engine.connect() as conn:
        from sqlalchemy import text

        row = (
            await conn.execute(
                text("SELECT consent, purpose, application_ref FROM reports WHERE id = :id"),
                {"id": report["reportId"]},
            )
        ).one()
    assert row.consent["consentId"] == request["consent"]["consentId"]
    assert row.consent["textVersion"] == "bki-consent-v1"
    assert (row.purpose, row.application_ref) == ("LOAN_APPLICATION", "APP-2026-000123")


# ---------- T-113: GET снимка ----------


async def test_get_report_returns_snapshot_without_new_inquiry(
    app: FastAPI, client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    posted = (await client.post(REPORTS, json=report_request(ROMASHKA))).json()
    first = await client.get(f"{REPORTS}/{posted['reportId']}")
    assert first.status_code == 200

    app.state.clock = clock_at(TODAY + timedelta(days=30))  # дни не пересчитываются
    second = await client.get(f"{REPORTS}/{posted['reportId']}")

    def report_part(body: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in body.items() if k != "meta"}

    assert report_part(first.json()) == report_part(posted) == report_part(second.json())
    assert second.json()["summary"]["currentOverdueDays"] == 94
    assert second.json()["meta"]["source"] == "CREDIT_BUREAU"
    assert len((await snapshot_runtime(admin, ROMASHKA))["inquiries"]) == 1


async def test_unknown_report_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{REPORTS}/rep_NOPE")
    assert (response.status_code, response.json()["code"]) == (404, "REPORT_NOT_FOUND")


# ---------- T-114: submissions ----------

ANNUITY_8M_36M_19_5 = 295_274


def annuity(amount: int, months: int, rate_percent: float) -> int:
    rate = rate_percent / 100 / 12
    return round(amount * rate / (1 - (1 + rate) ** -months))


def test_annuity_control_values_from_spec() -> None:
    assert annuity(8_000_000, 36, 19.5) == ANNUITY_8M_36M_19_5
    assert abs(annuity(8_000_000, 36, 21) - 301_400) < 100  # 301,4 тыс. из карточки T-114


def event(event_id: str, event_type: str, inn: str = SNAB, **payload: Any) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "eventType": event_type,
        "occurredAt": "2026-10-20T09:11:00Z",
        "subject": {"type": "LEGAL_ENTITY", "inn": inn},
        **payload,
    }


def registered(event_id: str = "evt_01JAKA1") -> dict[str, Any]:
    return event(
        event_id,
        "APPLICATION_REGISTERED",
        application={
            "ref": "APP-2026-000124",
            "kind": "LOAN",
            "amountRub": 8_000_000,
            "termMonths": 12,
        },
    )


def decided(event_id: str = "evt_01JAKA2", decision: str = "APPROVED") -> dict[str, Any]:
    return event(
        event_id,
        "APPLICATION_DECIDED",
        application={"ref": "APP-2026-000124", "decision": decision},
    )


def opened(
    event_id: str = "evt_01JAKA3", uid: str = "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-7"
) -> dict[str, Any]:
    body = event(
        event_id,
        "OBLIGATION_OPENED",
        obligation={
            "uid": uid,
            "kind": "LOAN",
            "role": "BORROWER",
            "openedAt": "2026-10-20",
            "plannedCloseAt": "2029-10-20",
            "amountRub": 8_000_000,
            "monthlyPaymentRub": ANNUITY_8M_36M_19_5,
            "secured": False,
        },
    )
    body["occurredAt"] = "2026-10-20T12:00:00Z"
    return body


def key() -> dict[str, str]:
    return {"Idempotency-Key": f"sub-{uuid.uuid4()}"}


async def submit(client: httpx.AsyncClient, body: dict[str, Any], **headers: str) -> httpx.Response:
    return await client.post(SUBMISSIONS, json=body, headers=headers or key())


async def test_three_events_close_the_loop_for_snabkontrakt(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    before = (await client.post(REPORTS, json=report_request(SNAB))).json()
    assert before["matchStatus"] == "NOT_FOUND"

    first = await submit(client, registered())
    assert first.status_code == 202
    assert first.json()["status"] == "ACCEPTED"
    assert first.json()["submissionId"].startswith("sub_")
    assert first.json()["meta"]["source"] == "CREDIT_BUREAU"

    # Субъекта не было — создан; заявка PENDING, isOwn
    mid = (await client.post(REPORTS, json=report_request(SNAB))).json()
    assert mid["matchStatus"] == "MATCHED"
    assert mid["hasHistory"] is False
    assert mid["applications"] == [
        {
            "date": "2026-10-20",
            "kind": "LOAN",
            "amountRub": 8_000_000,
            "decision": "PENDING",
            "decisionDate": None,
            "isOwn": True,
        }
    ]
    assert mid["summary"]["rejectedApplications90d"] == 0

    assert (await submit(client, decided())).status_code == 202
    assert (await submit(client, opened())).status_code == 202

    after = (await client.post(REPORTS, json=report_request(SNAB))).json()
    assert after["hasHistory"] is True
    assert after["applications"][0]["decision"] == "APPROVED"
    assert after["applications"][0]["decisionDate"] == "2026-10-20"
    assert after["applications"][0]["amountRub"] == 8_000_000  # заявка осталась на 8 млн
    [loan] = after["obligations"]
    assert loan["uid"] == "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-7"
    assert loan["balanceRub"] == 8_000_000
    assert loan["monthlyPaymentRub"] == ANNUITY_8M_36M_19_5
    assert loan["status"] == "ACTIVE"
    assert loan["overdueDays"] == 0
    assert loan["paymentHistory"] == [{"month": "2026-10", "status": "OK"}]
    assert after["summary"]["totalDebtRub"] == 8_000_000
    assert after["summary"]["monthlyPaymentsRub"] == ANNUITY_8M_36M_19_5
    assert after["summary"]["activeObligations"] == 1
    # Три наших запроса: до, середина, после; все помечены isOwn
    assert after["summary"]["inquiries30d"] == 3
    assert after["summary"]["inquiries30dExcludingOwn"] == 0

    runtime = await snapshot_runtime(admin, SNAB)
    assert [o["uid"] for o in runtime["obligations"]] == [loan["uid"]]
    assert len(runtime["submissions"]) == 3


async def test_own_rejection_counts_only_in_total(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    body = full_romashka_body()
    await put_subject(admin, ROMASHKA, body)
    reg = event("e1", "APPLICATION_REGISTERED", ROMASHKA, application={
        "ref": "APP-OWN-1", "kind": "LOAN", "amountRub": 3_000_000})  # fmt: skip
    assert (await submit(client, reg)).status_code == 202
    dec = event("e2", "APPLICATION_DECIDED", ROMASHKA, application={
        "ref": "APP-OWN-1", "decision": "REJECTED"})  # fmt: skip
    assert (await submit(client, dec)).status_code == 202
    summary = (await client.post(REPORTS, json=report_request(ROMASHKA))).json()["summary"]
    assert summary["rejectedApplications90d"] == 3
    assert summary["rejectedApplications90dExcludingOwn"] == 2
    assert summary["inquiries30d"] - summary["inquiries30dExcludingOwn"] == 1


async def test_submission_requires_idempotency_key(client: httpx.AsyncClient) -> None:
    response = await client.post(SUBMISSIONS, json=registered())
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_ERROR")


async def test_same_event_id_with_other_key_returns_original_202(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    first = await submit(client, registered())
    again = await submit(client, registered())  # другой ключ, то же событие
    assert again.status_code == 202
    assert again.json()["submissionId"] == first.json()["submissionId"]
    assert len((await snapshot_runtime(admin, SNAB))["submissions"]) == 1
    assert len((await snapshot_runtime(admin, SNAB))["applications"]) == 1

    changed = registered()
    changed["application"]["amountRub"] = 9_000_000
    conflict = await submit(client, changed)
    assert (conflict.status_code, conflict.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")


async def test_same_key_replays_and_other_body_conflicts(client: httpx.AsyncClient) -> None:
    headers = key()
    first = await submit(client, registered(), **headers)
    replay = await submit(client, registered(), **headers)
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    other = await submit(client, registered("evt_other"), **headers)
    assert (other.status_code, other.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")


async def test_parallel_duplicate_submissions_apply_once(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    same_key = key()
    same_key_results = await asyncio.gather(
        *(submit(client, registered(), **same_key) for _ in range(6))
    )
    codes = [r.status_code for r in same_key_results]
    assert set(codes) <= {202, 409}
    assert 202 in codes
    for r in same_key_results:
        if r.status_code == 409:
            assert r.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"

    # То же событие под разными ключами одновременно: один submissionId, одно применение
    ids = await asyncio.gather(*(submit(client, opened("evt-par")) for _ in range(6)))
    assert {r.status_code for r in ids} == {202}
    assert len({r.json()["submissionId"] for r in ids}) == 1

    runtime = await snapshot_runtime(admin, SNAB)
    assert len(runtime["applications"]) == 1
    assert len(runtime["obligations"]) == 1
    assert len(runtime["submissions"]) == 2


async def test_decision_for_unregistered_application_is_404(client: httpx.AsyncClient) -> None:
    response = await submit(client, decided())
    assert (response.status_code, response.json()["code"]) == (404, "APPLICATION_NOT_FOUND")
    await submit(client, registered())
    # Заявка есть, но у другого субъекта
    other = decided("evt-x")
    other["subject"]["inn"] = ROMASHKA
    assert (await submit(client, other)).json()["code"] == "APPLICATION_NOT_FOUND"
    # Ошибка не запоминает eventId: после регистрации то же событие проходит
    assert (await submit(client, decided())).status_code == 202


async def test_withdrawn_after_approved_replaces_decision(client: httpx.AsyncClient) -> None:
    await submit(client, registered())
    await submit(client, decided("evt-a", "APPROVED"))
    assert (await submit(client, decided("evt-w", "WITHDRAWN"))).status_code == 202
    report = (await client.post(REPORTS, json=report_request(SNAB))).json()
    assert report["applications"][0]["decision"] == "WITHDRAWN"
    assert report["summary"]["rejectedApplications90d"] == 0


async def test_same_obligation_uid_is_created_once(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await submit(client, opened("evt-1"))
    await submit(client, opened("evt-2"))  # другое событие, тот же uid
    report = (await client.post(REPORTS, json=report_request(SNAB))).json()
    assert len(report["obligations"]) == 1


async def test_obligation_closed_and_unknown_uid(client: httpx.AsyncClient) -> None:
    await submit(client, opened())
    closing = event(
        "evt-close",
        "OBLIGATION_CLOSED",
        obligation={"uid": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-7", "closedAt": "2026-10-20"},
    )
    assert (await submit(client, closing)).status_code == 202
    report = (await client.post(REPORTS, json=report_request(SNAB))).json()
    [loan] = report["obligations"]
    assert (loan["status"], loan["balanceRub"], loan["closedAt"]) == ("CLOSED", 0, "2026-10-20")
    assert report["summary"]["activeObligations"] == 0
    assert report["summary"]["closedObligations"] == 1
    unknown = event(
        "evt-unknown", "OBLIGATION_CLOSED", obligation={"uid": "nope", "closedAt": "2026-10-20"}
    )
    response = await submit(client, unknown)
    assert (response.status_code, response.json()["code"]) == (404, "OBLIGATION_NOT_FOUND")


@pytest.mark.parametrize(
    "broken",
    [
        {"eventType": "SOMETHING_ELSE"},
        {"application": None},
        {"occurredAt": "2026-10-20T09:11:00"},
        {"eventId": ""},
    ],
)
async def test_invalid_submissions_are_422(
    client: httpx.AsyncClient, broken: dict[str, Any]
) -> None:
    body = {**registered(), **broken}
    response = await submit(client, body)
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_ERROR")


async def test_submission_with_bad_inn_or_type(client: httpx.AsyncClient) -> None:
    bad = registered()
    bad["subject"]["inn"] = "0012345674"
    assert (await submit(client, bad)).json()["code"] == "INN_INVALID"
    wrong = registered()
    wrong["subject"]["type"] = "PERSON"
    assert (await submit(client, wrong)).status_code == 422


async def test_openapi_describes_all_event_types(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]
    for name in (
        "ApplicationRegistered",
        "ApplicationDecided",
        "ObligationOpened",
        "ObligationClosed",
    ):
        assert name in schemas
    post = spec["paths"]["/api/v1/submissions"]["post"]
    assert "202" in post["responses"]
    assert {"ApiKeyAuth": []} in post["security"]
    assert "/api/v1/credit-reports/{reportId}" in spec["paths"]


# ---------- админ-API (8.3) ----------


async def test_spec_admin_body_round_trips(admin: httpx.AsyncClient) -> None:
    body = spec_romashka_body()
    created = await admin.put(
        f"/admin/subjects/{ROMASHKA}", json=body, headers={"X-Scenario-Code": "romashka"}
    )
    assert created.status_code == 201
    view = (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()
    assert (view["scenarioCode"], view["origin"]) == ("romashka", "SCENARIO")
    data = view["data"]
    assert data["subject"]["inn"] == ROMASHKA
    assert data["subject"]["name"] == body["subject"]["name"]
    for key_, value in body["obligations"][0].items():
        assert data["obligations"][0][key_] == value, key_
    assert data["inquiries"] == body["inquiries"]
    assert data["applications"] == body["applications"]
    assert data["bankruptcies"] == []
    # Повторный PUT заменяет данные, не дублируя
    assert (await admin.put(f"/admin/subjects/{ROMASHKA}", json=body)).status_code == 200
    again = (await admin.get(f"/admin/subjects/{ROMASHKA}")).json()["data"]
    assert len(again["obligations"]) == len(again["inquiries"]) == 1


async def test_put_keeps_runtime_records_and_patch_replaces_arrays(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, full_romashka_body())
    await client.post(REPORTS, json=report_request(ROMASHKA))
    await put_subject(admin, ROMASHKA, spec_romashka_body())
    runtime = await snapshot_runtime(admin, ROMASHKA)
    assert len(runtime["inquiries"]) == 1  # наш запрос пережил переприменение

    patch = {"subject": {"name": "ООО «Ромашка-2»"}, "obligations": []}
    response = await admin.patch(f"/admin/subjects/{ROMASHKA}", json=patch)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["subject"]["name"] == "ООО «Ромашка-2»"
    assert data["subject"]["ogrn"] == "1190000007890"
    assert data["obligations"] == []
    assert len(data["inquiries"]) == 1  # чужие запросы из сценария на месте
    assert len((await snapshot_runtime(admin, ROMASHKA))["inquiries"]) == 1


async def test_admin_validation_errors(admin: httpx.AsyncClient) -> None:
    mismatch = spec_romashka_body()
    mismatch["subject"]["inn"] = NO_HISTORY
    response = await admin.put(f"/admin/subjects/{ROMASHKA}", json=mismatch)
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_ERROR")

    wrong_type = spec_romashka_body()
    wrong_type["subject"]["type"] = "PERSON"
    assert (await admin.put(f"/admin/subjects/{ROMASHKA}", json=wrong_type)).status_code == 422

    duplicate = spec_romashka_body()
    duplicate["obligations"].append(copy.deepcopy(duplicate["obligations"][0]))
    assert (await admin.put(f"/admin/subjects/{ROMASHKA}", json=duplicate)).status_code == 422

    reversed_period = spec_romashka_body()
    reversed_period["obligations"][0]["overduePeriods"] = [
        {"since": "2026-07-18", "until": "2026-07-01"}
    ]
    assert (await admin.put(f"/admin/subjects/{ROMASHKA}", json=reversed_period)).status_code == 422

    await put_subject(admin, ROMASHKA, spec_romashka_body())
    steal = {"subject": subject_of(NO_HISTORY), "obligations": spec_romashka_body()["obligations"]}
    response = await admin.put(f"/admin/subjects/{NO_HISTORY}", json=steal)
    assert response.status_code == 422
    assert "uid" in response.json()["detail"]


async def test_delete_subject_scenario_and_wipe_remove_runtime_too(
    client: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await put_subject(admin, ROMASHKA, spec_romashka_body(), scenario="romashka")
    await put_subject(admin, OWNER, {"subject": subject_of(OWNER)}, scenario="owner")
    report = (await client.post(REPORTS, json=report_request(ROMASHKA))).json()
    await client.post(REPORTS, json=report_request(OWNER))
    await submit(client, registered())  # RUNTIME-субъект без сценария

    counts = (await admin.get("/admin/scenarios")).json()
    assert counts == [
        {"scenarioCode": "owner", "subjects": 1},
        {"scenarioCode": "romashka", "subjects": 1},
    ]
    listing = (await admin.get("/admin/subjects", params={"origin": "RUNTIME"})).json()
    assert [i["inn"] for i in listing["items"]] == [SNAB]

    assert (await admin.delete("/admin/scenarios/romashka")).json() == {"deleted": 1}
    assert (await admin.get(f"/admin/subjects/{ROMASHKA}")).status_code == 404
    assert (await client.get(f"{REPORTS}/{report['reportId']}")).status_code == 404
    assert len((await snapshot_runtime(admin, OWNER))["inquiries"]) == 1  # чужой сценарий цел

    assert (await admin.delete(f"/admin/subjects/{SNAB}")).status_code == 204
    # Событие забыто вместе с субъектом, его можно принять снова
    assert (await submit(client, registered())).status_code == 202

    assert (await admin.post("/admin/wipe")).status_code == 204
    assert (await admin.get("/admin/subjects")).json()["total"] == 0
    assert (await admin.delete(f"/admin/subjects/{OWNER}")).status_code == 404
