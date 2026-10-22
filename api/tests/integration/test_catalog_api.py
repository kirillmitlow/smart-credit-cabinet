"""T-240…T-242: каталог, калькулятор и мастер по HTTP, по персонам."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx
import pytest

from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = pytest.mark.integration

FIRMS = [
    Firm(
        "sokolova",
        "001234567887",
        "ИП Соколова",
        kind="IP",
        registered_on=date(2023, 4, 12),
        is_bank_customer=True,
        profile={"customerSince": "2023-05-02"},
        members=[Member("sokolova", "Соколова", "DIRECTOR", "001234567887")],
    ),
    Firm(
        "garipov",
        "001234567999",
        "ИП Гарипов",
        kind="IP",
        registered_on=date(2021, 6, 1),
        is_bank_customer=False,
        members=[Member("garipov", "Гарипов", "DIRECTOR", "001234567999")],
    ),
    Firm(
        "quick",
        "0019991114",
        "Быстрый старт",
        registered_on=date(2026, 7, 21),
        is_bank_customer=True,
        profile={"customerSince": "2026-07-21"},
        members=[Member("owner", "Соколов", "DIRECTOR", "001310000999")],
    ),
]


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    with make_stand(postgres_url, redis_url, monkeypatch, FIRMS) as s:
        yield s


async def test_unauthenticated_is_401(stand: dict[str, Any]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stand["app"]), base_url="http://api"
    ) as c:
        for method, path in (
            ("GET", "/products"),
            ("POST", "/calculator/payment"),
            ("POST", "/wizard/recommendations"),
        ):
            assert (await c.request(method, path)).status_code == 401


async def test_catalog_for_sokolova_all_six_available(stand: dict[str, Any]) -> None:
    async with client_for(stand, "sokolova:sokolova") as c:
        body = (await c.get("/products")).json()
    assert [p["code"] for p in body["items"]] == [
        "EXPRESS",
        "WORKING_CAPITAL",
        "CONTRACT",
        "CREDIT_LINE",
        "OVERDRAFT",
        "INVESTMENT",
    ]
    assert all(p["available"] for p in body["items"])
    express = body["items"][0]
    assert express["amountMinRub"] == 100_000
    assert express["ratePercentFrom"] == 24.0
    assert express["autoDecisionMode"] == "UP_TO"
    assert express["autoDecisionUpToRub"] == 3_000_000


async def test_overdraft_grey_for_non_client_with_hint(stand: dict[str, Any]) -> None:
    async with client_for(stand, "garipov:garipov") as c:
        one = await c.get("/products/OVERDRAFT")
        assert (await c.get("/products/MAGIC")).status_code == 404
    product = one.json()
    assert product["available"] is False
    assert product["unavailableReasons"][0]["code"] == "NOT_BANK_CLIENT"
    assert product["hint"] == "Овердрафт станет доступен после 6 мес. обслуживания у нас"


async def test_young_business_catalog_is_not_a_dead_end(stand: dict[str, Any]) -> None:
    async with client_for(stand, "quick:owner") as c:
        items = {p["code"]: p for p in (await c.get("/products")).json()["items"]}
    assert items["EXPRESS"]["available"]
    assert items["EXPRESS"]["requiresSecurity"]
    assert not items["CREDIT_LINE"]["available"]
    assert items["CREDIT_LINE"]["unavailableReasons"][0]["availableFrom"] == "2028-07-21"
    assert items["OVERDRAFT"]["unavailableReasons"][0]["availableFrom"] == "2027-01-21"


async def test_calculator_matches_oracle_and_reports_field_errors(stand: dict[str, Any]) -> None:
    async with client_for(stand, "sokolova:sokolova") as c:
        ok = await c.post(
            "/calculator/payment",
            json={"productCode": "EXPRESS", "amountRub": 500_000, "termMonths": 12},
        )
        offer = await c.post(
            "/calculator/payment",
            json={
                "productCode": "EXPRESS",
                "amountRub": 500_000,
                "termMonths": 12,
                "ratePercent": 21.5,
            },
        )
        low = await c.post(
            "/calculator/payment",
            json={"productCode": "EXPRESS", "amountRub": 50_000, "termMonths": 12},
        )
        bad_product = await c.post(
            "/calculator/payment",
            json={"productCode": "NOPE", "amountRub": 500_000, "termMonths": 12},
        )
    body = ok.json()
    assert (body["paymentRub"], body["overpaymentRub"], body["ratePercentFrom"]) == (
        47_280,
        67_358,
        24.0,
    )
    assert body["approximate"] is True
    assert body["paymentKind"] == "ANNUITY"
    assert (offer.json()["paymentRub"], offer.json()["approximate"]) == (46_677, False)
    assert low.status_code == 422
    assert low.json()["code"] == "VALIDATION_ERROR"
    assert low.json()["errors"][0]["loc"] == ["body", "amountRub"]
    assert bad_product.status_code == 422


async def test_wizard_creates_draft_and_saves_answers(stand: dict[str, Any]) -> None:
    async with client_for(stand, "sokolova:sokolova") as c:
        answers = {
            "purpose": "GOODS",
            "frequency": "ONCE",
            "amountRub": 2_000_000,
            "termMonths": 12,
        }
        first = await c.post("/wizard/recommendations", json={"answers": answers})
        assert first.status_code == 200
        result = first.json()
        assert result["outcome"] == "RECOMMENDED"
        assert result["primary"]["productCode"] == "WORKING_CAPITAL"
        assert result["alternative"]["productCode"] == "EXPRESS"
        app_id = result["applicationId"]
        application = (await c.get(f"/applications/{app_id}")).json()
        assert application["status"] == "DRAFT"
        assert (
            application["productCode"],
            application["amountRub"],
            application["termMonths"],
        ) == (
            "WORKING_CAPITAL",
            2_000_000,
            12,
        )
        assert application["draft"]["wizard"]["answers"]["purpose"] == "GOODS"
        # меняем ответ: результат пересчитывается, тот же черновик обновляется
        changed = await c.post(
            "/wizard/recommendations",
            json={
                "answers": {**answers, "frequency": "REGULAR", "amountRub": 5_000_000},
                "applicationId": app_id,
            },
        )
        assert changed.json()["primary"]["productCode"] == "CREDIT_LINE"
        assert changed.json()["applicationId"] == app_id
        assert (await c.get(f"/applications/{app_id}")).json()["productCode"] == "CREDIT_LINE"


async def test_wizard_foreign_draft_is_404_and_young_business_gets_start_path(
    stand: dict[str, Any],
) -> None:
    async with (
        client_for(stand, "sokolova:sokolova") as sok,
        client_for(stand, "quick:owner") as quick,
    ):
        mine = (
            await sok.post("/wizard/recommendations", json={"answers": {"purpose": "OTHER"}})
        ).json()
        foreign = await quick.post(
            "/wizard/recommendations",
            json={"answers": {"purpose": "OTHER"}, "applicationId": mine["applicationId"]},
        )
        assert foreign.status_code == 404
        start = (
            await quick.post(
                "/wizard/recommendations",
                json={"answers": {"purpose": "OTHER", "amountRub": 1_000_000, "termMonths": 24}},
            )
        ).json()
    assert start["startPath"] is True
    assert start["primary"]["productCode"] == "EXPRESS"
    assert start["primary"]["decisionTime"] == "MANUAL"
    assert start["primary"]["requiresSecurity"]


async def test_wizard_unknown_answers_and_catalog_hint(stand: dict[str, Any]) -> None:
    async with client_for(stand, "sokolova:sokolova") as c:
        unknown = (
            await c.post(
                "/wizard/recommendations",
                json={
                    "answers": {"purpose": "GOODS", "frequency": "UNKNOWN", "amountRub": 8_000_000}
                },
            )
        ).json()
        hint = (
            await c.post(
                "/wizard/recommendations",
                json={"answers": {"purpose": "OTHER", "amountRub": 9_000_000}},
            )
        ).json()
    assert unknown["primary"]["productCode"] == "WORKING_CAPITAL"
    assert hint["outcome"] == "CATALOG_HINT"
    assert hint["primary"] is None
    assert hint["hint"]
    assert hint["rejected"][0]["reasons"][0]["code"] == "AMOUNT_OUT_OF_RANGE"
