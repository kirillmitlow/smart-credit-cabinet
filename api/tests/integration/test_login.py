"""T-210/T-211/T-212/T-221: вход по ИНН и коду, две сессии, коды, синхронизация учёток."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.main import create_app
from app.modules.auth import codes, sessions
from app.modules.auth.principal import Principal, Zone
from app.modules.integrations import scenarios
from app.shared import db
from app.shared.errors import AppError
from app.shared.settings import Settings

pytestmark = pytest.mark.integration

SOKOLOVA_INN = "001234567887"
STANKO_INN = "0017654322"
KUZNETSOV_INN = "001310000115"


def person(ref: str, inn: str, name: str) -> dict[str, Any]:
    return {"ref": ref, "refs": [ref], "inn": inn, "fullName": name}


VIEWS: dict[str, dict[str, Any]] = {
    "sokolova": {
        "code": "sokolova",
        "title": "ИП Соколова",
        "inn": SOKOLOVA_INN,
        "users": [
            {"login": "sokolova", "role": "DIRECTOR", "personRef": "self", "inn": SOKOLOVA_INN}
        ],
        "expanded": {
            "identity": {
                "inn": SOKOLOVA_INN,
                "form": "IP",
                "shortName": "ИП Соколова Анна Сергеевна",
                "status": "ACTIVE",
                "persons": [person("self", SOKOLOVA_INN, "Соколова Анна Сергеевна")],
            }
        },
    },
    "stankoprom": {
        "code": "stankoprom",
        "title": "СтанкоПром",
        "inn": STANKO_INN,
        "users": [
            {"login": "kuznetsov", "role": "DIRECTOR", "personRef": "kuznetsov"},
            {
                "login": "belova",
                "role": "ACCOUNTANT",
                "fullName": "Белова Ольга Николаевна",
                "inn": "001310000299",
                "powerOfAttorney": True,
            },
        ],
        "expanded": {
            "identity": {
                "inn": STANKO_INN,
                "form": "LLC",
                "shortName": "ООО «СтанкоПром»",
                "status": "ACTIVE",
                "persons": [person("kuznetsov", KUZNETSOV_INN, "Кузнецов Игорь Петрович")],
            }
        },
    },
    "orlov": {
        "code": "orlov",
        "title": "Орлов",
        "inn": "001310000436",
        "users": [],
        "expanded": {
            "identity": {"inn": "001310000436", "form": "SELF_EMPLOYED", "shortName": "Орлов"}
        },
    },
    "vektor": {
        "code": "vektor",
        "title": "Вектор",
        "inn": "0015557771",
        "users": [
            {
                "login": "vektor",
                "role": "DIRECTOR",
                "fullName": "Петров П. П.",
                "inn": "001310000757",
            }
        ],
        "expanded": {
            "identity": {
                "inn": "0015557771",
                "form": "LLC",
                "shortName": "ООО «Вектор»",
                "status": "LIQUIDATING",
            }
        },
    },
}


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(
        scenarios, "list_scenarios", lambda: [{"code": c, "status": "APPLIED"} for c in VIEWS]
    )
    monkeypatch.setattr(scenarios, "get_scenario", lambda code: VIEWS[code])
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, demo_mode=True))
    db.migrate(db.get_database().engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as c:
        yield c
    db.get_database().dispose()


async def login(client: httpx.AsyncClient, inn: str, pick: int = 0) -> httpx.Response:
    roles = (await client.get(f"/auth/roles/{inn}")).json()
    user_id = roles["people"][pick]["userId"]
    company_id = roles["company"]["id"] if roles["kind"] == "COMPANY" else None
    issued = (
        await client.post("/auth/request-code", json={"userId": user_id, "companyId": company_id})
    ).json()
    return await client.post(
        "/auth/verify-code", json={"requestId": issued["requestId"], "code": issued["demoCode"]}
    )


async def test_sokolova_logs_in_and_sees_her_company(client: httpx.AsyncClient) -> None:
    response = await login(client, SOKOLOVA_INN)
    assert response.status_code == 200
    assert "sid_client" in response.cookies
    me = (await client.get("/me")).json()
    assert me["displayName"] == "Соколова Анна Сергеевна"
    assert [c["company"]["inn"] for c in me["companies"]] == [SOKOLOVA_INN]
    assert me["activeCompanyId"] == me["companies"][0]["company"]["id"]


async def test_company_inn_lists_both_stankoprom_users(client: httpx.AsyncClient) -> None:
    roles = (await client.get(f"/auth/roles/{STANKO_INN}")).json()
    assert roles["kind"] == "COMPANY"
    assert {(p["displayName"], p["role"]) for p in roles["people"]} == {
        ("Кузнецов Игорь Петрович", "DIRECTOR"),
        ("Белова Ольга Николаевна", "ACCOUNTANT"),
    }


async def test_personal_inn_of_director_leads_to_company_choice(client: httpx.AsyncClient) -> None:
    roles = (await client.get(f"/auth/roles/{KUZNETSOV_INN}")).json()
    assert roles["kind"] == "PERSON"
    assert roles["companies"][0]["company"]["inn"] == STANKO_INN
    assert roles["companies"][0]["role"] == "DIRECTOR"


async def test_self_employed_gets_explanation_and_liquidating_can_log_in(
    client: httpx.AsyncClient,
) -> None:
    orlov = (await client.get("/auth/roles/001310000436")).json()
    assert orlov["kind"] == "NOT_ELIGIBLE"
    assert orlov["reasonCode"] == "SELF_EMPLOYED"
    assert (await login(client, "0015557771")).status_code == 200
    vektor = (await client.get("/me")).json()
    assert vektor["companies"][0]["company"]["canApply"] is False


async def test_unknown_and_invalid_inn(client: httpx.AsyncClient) -> None:
    assert (await client.get("/auth/roles/0019999995")).json()["code"] in {
        "INN_NOT_FOUND",
        "INN_INVALID",
    }
    assert (await client.get("/auth/roles/0017654323")).json()["code"] == "INN_INVALID"


async def test_code_for_one_person_does_not_open_another(client: httpx.AsyncClient) -> None:
    roles = (await client.get(f"/auth/roles/{STANKO_INN}")).json()
    kuz, bel = roles["people"][0]["userId"], roles["people"][1]["userId"]
    first = (await client.post("/auth/request-code", json={"userId": kuz})).json()
    second = (await client.post("/auth/request-code", json={"userId": bel})).json()
    wrong = await client.post(
        "/auth/verify-code", json={"requestId": second["requestId"], "code": first["demoCode"]}
    )
    if first["demoCode"] != second["demoCode"]:
        assert wrong.status_code == 422
        assert wrong.json()["code"] == "CODE_INVALID"


async def test_three_wrong_attempts_block_the_code(client: httpx.AsyncClient) -> None:
    roles = (await client.get(f"/auth/roles/{SOKOLOVA_INN}")).json()
    issued = (
        await client.post("/auth/request-code", json={"userId": roles["people"][0]["userId"]})
    ).json()
    bad = "000000" if issued["demoCode"] != "000000" else "111111"
    statuses = [
        (
            await client.post(
                "/auth/verify-code", json={"requestId": issued["requestId"], "code": bad}
            )
        ).json()["code"]
        for _ in range(3)
    ]
    assert statuses == ["CODE_INVALID", "CODE_INVALID", "CODE_ATTEMPTS_EXCEEDED"]
    late = await client.post(
        "/auth/verify-code", json={"requestId": issued["requestId"], "code": issued["demoCode"]}
    )
    assert late.json()["code"] == "CODE_ATTEMPTS_EXCEEDED"


async def test_logout_kills_session_and_bank_zone_is_separate(client: httpx.AsyncClient) -> None:
    await login(client, SOKOLOVA_INN)
    assert (await client.get("/me")).status_code == 200
    client.cookies.set("sid_bank", "something")
    assert (await client.post("/auth/logout")).status_code == 204
    after = await client.get("/me")
    assert after.status_code == 401
    assert after.json()["code"] == "UNAUTHENTICATED"


async def test_active_company_switch_checks_membership(client: httpx.AsyncClient) -> None:
    await login(client, SOKOLOVA_INN)
    stranger = (await client.get(f"/auth/roles/{STANKO_INN}")).json()["company"]["id"]
    refused = await client.put("/me/active-company", json={"companyId": stranger})
    assert refused.status_code == 404


async def test_public_config(client: httpx.AsyncClient) -> None:
    config = (await client.get("/public-config")).json()
    assert config["demoMode"] is True
    assert set(config) == {
        "demoMode",
        "productName",
        "version",
        "nluAvailable",
        "demoCodeRequired",
        "docsLinks",
    }
    assert config["demoCodeRequired"] is False
    assert config["docsLinks"] == {"api": "/docs"}


def test_session_store_down_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    principal = Principal(
        user_id=__import__("uuid").uuid4(), role="CLIENT", zone=Zone.CLIENT, display_name="x"
    )
    with pytest.raises(AppError) as err:
        sessions.create(principal)
    assert err.value.status == 503
    with pytest.raises(AppError):
        codes.issue("001234567887", "LOGIN")


def test_code_bound_to_purpose(redis_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", redis_url)
    issued = codes.issue("001234567887", "SIGN", "bundle-1")
    with pytest.raises(AppError) as err:
        codes.verify(issued.request_id, issued.code, purpose="LOGIN")
    assert err.value.code == "CODE_INVALID"
    assert codes.verify(issued.request_id, issued.code, purpose="SIGN").subject == "bundle-1"
