"""T-107, T-108 (интеграция): mock-registry — карточки ЕГРЮЛ/ЕГРИП, роли людей и ЕФРСБ."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from tests.conftest import ADMIN_KEY, API_KEY, database_url, make_settings

pytestmark = pytest.mark.integration

STANKOPROM = "0017654322"
KUZNETSOV = "001310000115"
SOKOLOVA = "001234567887"
LEBEDEV = "001310000757"
GROMOV = "001310000820"
LEBEDEV_LLC = "0019000011"
ORLOV = "001211122200"  # самозанятый: в ЕГРИП его нет

GRN_STANKOPROM = "2230000123450"
UNRELIABLE = {
    "since": "2026-08-01",
    "grn": "2260000987651",
    "reason": "Результаты проверки достоверности",
}


def stankoprom() -> dict[str, Any]:
    return {
        "type": "LEGAL_ENTITY",
        "inn": STANKOPROM,
        "kpp": "001701001",
        "ogrn": "1170000004569",
        "registrationDate": "2017-03-14",
        "fullName": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «СТАНКОПРОМ»",
        "shortName": "ООО «СтанкоПром»",
        "legalForm": {"okopf": "12300", "name": "Общество с ограниченной ответственностью"},
        "status": {"code": "ACTIVE", "name": "Действующее", "since": "2017-03-14"},
        "pendingExclusion": None,
        "address": {
            "regionCode": "66",
            "regionName": "Свердловская область",
            "full": "620000, Свердловская обл., г. Екатеринбург, ул. Заводская, д. 1",
            "unreliable": None,
        },
        "authorizedCapitalRub": 500000,
        "director": {
            "fullName": "Кузнецов Игорь Петрович",
            "inn": KUZNETSOV,
            "position": "Генеральный директор",
            "since": "2017-03-14",
            "unreliable": None,
        },
        "founders": [
            {
                "type": "PERSON",
                "fullName": "Кузнецов Игорь Петрович",
                "inn": KUZNETSOV,
                "sharePercent": 100,
                "shareNominalRub": 500000,
                "unreliable": None,
            }
        ],
        "okvedMain": {"code": "25.62", "name": "Обработка металлических изделий механическая"},
        "okvedAdditional": [
            {"code": "28.41", "name": "Производство металлообрабатывающего оборудования"}
        ],
        "taxAuthority": {"code": "0017", "name": "Межрайонная ИФНС России № 17 (синтетическая)"},
        "lastRecord": {"grn": GRN_STANKOPROM, "date": "2023-06-01"},
    }


def kuznetsov() -> dict[str, Any]:
    return {
        "inn": KUZNETSOV,
        "lastName": "Кузнецов",
        "firstName": "Игорь",
        "middleName": "Петрович",
        "birthDate": "1978-05-12",
    }


def stankoprom_body() -> dict[str, Any]:
    return {"entity": stankoprom(), "persons": [kuznetsov()], "bankruptcies": []}


def sokolova() -> dict[str, Any]:
    return {
        "type": "INDIVIDUAL_ENTREPRENEUR",
        "inn": SOKOLOVA,
        "ogrnip": "323000000123450",
        "registrationDate": "2023-04-12",
        "person": {
            "lastName": "Соколова",
            "firstName": "Анна",
            "middleName": "Сергеевна",
            "fullName": "Соколова Анна Сергеевна",
        },
        "status": {"code": "ACTIVE", "name": "Действующий", "since": "2023-04-12"},
        "region": {"code": "16", "name": "Республика Татарстан"},
        "okvedMain": {
            "code": "56.10",
            "name": "Деятельность ресторанов и услуги по доставке продуктов питания",
        },
        "okvedAdditional": [],
        "taxAuthority": {"code": "0012", "name": "ИФНС России № 12 (синтетическая)"},
        "lastRecord": {"grn": "423000000123450", "date": "2023-04-12"},
    }


def sokolova_body() -> dict[str, Any]:
    person = {
        "inn": SOKOLOVA,
        "lastName": "Соколова",
        "firstName": "Анна",
        "middleName": "Сергеевна",
        "birthDate": "1990-02-02",
    }
    return {"entity": sokolova(), "persons": [person], "bankruptcies": []}


def lebedev_llc_body() -> dict[str, Any]:
    """Пример из 8.3: директор Лебедев, учредитель Громов с завершённым делом ЕФРСБ."""
    entity = stankoprom()
    entity.update(
        inn=LEBEDEV_LLC,
        kpp="001901001",
        ogrn="1190000004567",
        shortName="ООО «Лебедев и Ко»",
        taxAuthority={"code": "0019", "name": "ИФНС России № 19 (синтетическая)"},
        lastRecord={"grn": "2190000123454", "date": "2023-06-01"},
    )
    entity["director"] = {
        **entity["director"],
        "fullName": "Лебедев Артём Игоревич",
        "inn": LEBEDEV,
    }
    entity["founders"] = [
        {
            **entity["founders"][0],
            "fullName": "Громов Кирилл Олегович",
            "inn": GROMOV,
            "sharePercent": 100,
        }
    ]
    persons = [
        {
            "inn": LEBEDEV,
            "lastName": "Лебедев",
            "firstName": "Артём",
            "middleName": "Игоревич",
            "birthDate": "1975-08-03",
        },
        {
            "inn": GROMOV,
            "lastName": "Громов",
            "firstName": "Кирилл",
            "middleName": "Олегович",
            "birthDate": "1983-01-21",
        },
    ]
    case = {
        "subjectInn": GROMOV,
        "subjectType": "PERSON",
        "caseNumber": "А00-45012/2022",
        "stage": "COMPLETED",
        "startedAt": "2022-03-10",
        "completedAt": "2024-10-15",
    }
    return {"entity": entity, "persons": persons, "bankruptcies": [case]}


@pytest.fixture(scope="module")
def registry_url(postgres_url: str) -> str:
    return database_url(postgres_url, "mock_registry_test")


@pytest.fixture
async def app(registry_url: str) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(database_url=registry_url, app_today="2026-10-20"))
    await app.state.database.migrate()
    yield app
    await app.state.database.dispose()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Admin-Key": ADMIN_KEY}
    ) as c:
        assert (await c.post("/admin/wipe")).status_code == 204
        yield c


@pytest.fixture
async def client(app: FastAPI, admin: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://mock", headers={"X-Api-Key": API_KEY}
    ) as c:
        yield c


def msk_date(moment: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return (
        datetime.fromisoformat(moment.replace("Z", "+00:00"))
        .astimezone(ZoneInfo("Europe/Moscow"))
        .date()
        .isoformat()
    )


async def put(
    admin: httpx.AsyncClient, inn: str, body: dict[str, Any], scenario: str | None = "demo"
) -> httpx.Response:
    headers = {"X-Scenario-Code": scenario} if scenario else {}
    return await admin.put(f"/admin/subjects/{inn}", json=body, headers=headers)


async def test_legal_entity_round_trip_matches_spec_example(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    assert (await put(admin, STANKOPROM, stankoprom_body())).status_code == 201
    response = await client.get(f"/api/v1/companies/{STANKOPROM}")
    assert response.status_code == 200
    body = response.json()
    meta = body.pop("meta")
    assert meta["source"] == "EGRUL"
    assert meta["simulated"] is True
    assert meta["dataActualAt"] == "2026-10-19"
    # Сутки стенда — по Москве: в UTC дата бывает вчерашней (00:00–03:00 МСК)
    assert msk_date(meta["retrievedAt"]) == "2026-10-20"
    assert meta["requestId"]
    assert body == stankoprom()


async def test_individual_entrepreneur_has_no_kpp_director_or_founders(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    assert (await put(admin, SOKOLOVA, sokolova_body())).status_code == 201
    body = (await client.get(f"/api/v1/companies/{SOKOLOVA}")).json()
    assert body.pop("meta")["source"] == "EGRIP"
    assert body == sokolova()
    for absent in ("kpp", "director", "founders", "authorizedCapitalRub", "address"):
        assert absent not in body


async def test_joint_stock_company_has_empty_founders(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    body = stankoprom_body()
    body["entity"]["legalForm"] = {"okopf": "12267", "name": "Публичные акционерные общества"}
    body["entity"]["founders"] = []
    assert (await put(admin, STANKOPROM, body)).status_code == 201
    card = (await client.get(f"/api/v1/companies/{STANKOPROM}")).json()
    assert card["founders"] == []
    assert card["director"]["inn"] == KUZNETSOV


async def test_joint_stock_company_with_founders_is_rejected(admin: httpx.AsyncClient) -> None:
    body = stankoprom_body()
    body["entity"]["legalForm"] = {"okopf": "12267", "name": "Публичные акционерные общества"}
    response = await put(admin, STANKOPROM, body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "акционерного" in str(response.json()["errors"])


async def test_llc_without_founders_is_rejected(admin: httpx.AsyncClient) -> None:
    body = stankoprom_body()
    body["entity"]["founders"] = []
    assert (await put(admin, STANKOPROM, body)).status_code == 422


async def test_unreliable_marks_and_pending_exclusion_round_trip(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    body = stankoprom_body()
    entity = body["entity"]
    entity["address"]["unreliable"] = UNRELIABLE
    entity["director"]["unreliable"] = UNRELIABLE
    entity["founders"][0]["unreliable"] = UNRELIABLE
    entity["pendingExclusion"] = {
        "decisionDate": "2026-09-10",
        "grn": "2260000111226",
        "objectionsDeadline": "2026-12-10",
    }
    assert (await put(admin, STANKOPROM, body)).status_code == 201
    card = (await client.get(f"/api/v1/companies/{STANKOPROM}")).json()
    assert card["address"]["unreliable"] == UNRELIABLE
    assert card["director"]["unreliable"] == UNRELIABLE
    assert card["founders"][0]["unreliable"] == UNRELIABLE
    assert card["pendingExclusion"] == entity["pendingExclusion"]


async def test_legal_entity_founder_keeps_name(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    body = stankoprom_body()
    body["entity"]["founders"] = [
        {
            "type": "LEGAL_ENTITY",
            "fullName": "ООО «Холдинг»",
            "inn": "0015557771",
            "sharePercent": 60.5,
            "shareNominalRub": 302500,
            "unreliable": None,
        },
        body["entity"]["founders"][0] | {"sharePercent": 39.5, "shareNominalRub": 197500},
    ]
    assert (await put(admin, STANKOPROM, body)).status_code == 201
    founders = (await client.get(f"/api/v1/companies/{STANKOPROM}")).json()["founders"]
    assert [f["type"] for f in founders] == ["LEGAL_ENTITY", "PERSON"]
    assert founders[0]["fullName"] == "ООО «Холдинг»"
    assert founders[0]["sharePercent"] == 60.5


async def test_missing_company_and_self_employed_are_404(client: httpx.AsyncClient) -> None:
    for inn in (STANKOPROM, ORLOV):
        response = await client.get(f"/api/v1/companies/{inn}")
        assert response.status_code == 404
        assert response.json()["code"] == "ENTITY_NOT_FOUND"
        assert response.headers["content-type"].startswith("application/problem+json")


async def test_bad_inn_is_400_everywhere(client: httpx.AsyncClient) -> None:
    for path in (
        "companies/0017654323",
        "companies/123",
        "persons/001310000116/roles",
        "bankruptcies/abc",
        "bankruptcies/0017654323",
    ):
        response = await client.get(f"/api/v1/{path}")
        assert response.status_code == 400, path
        assert response.json()["code"] == "INN_INVALID"


async def test_keys_are_checked(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        for path in (
            f"companies/{STANKOPROM}",
            f"persons/{KUZNETSOV}/roles",
            f"bankruptcies/{STANKOPROM}",
        ):
            url = f"/api/v1/{path}"
            assert (await c.get(url)).status_code == 401
            assert (await c.get(url, headers={"X-Api-Key": "dev-tax-key"})).status_code == 401
            assert (await c.get(url, headers={"X-Admin-Key": ADMIN_KEY})).status_code == 403


async def test_person_roles_director_founder_and_ip(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, STANKOPROM, stankoprom_body())
    body = (await client.get(f"/api/v1/persons/{KUZNETSOV}/roles")).json()
    assert body.pop("meta")["source"] == "EGRUL"
    assert body == {
        "personInn": KUZNETSOV,
        "roles": [
            {
                "role": "DIRECTOR",
                "entityInn": STANKOPROM,
                "entityName": "ООО «СтанкоПром»",
                "entityStatus": "ACTIVE",
                "since": "2017-03-14",
                "sharePercent": None,
            },
            {
                "role": "FOUNDER",
                "entityInn": STANKOPROM,
                "entityName": "ООО «СтанкоПром»",
                "entityStatus": "ACTIVE",
                "since": "2017-03-14",
                "sharePercent": 100,
            },
        ],
    }
    await put(admin, SOKOLOVA, sokolova_body(), scenario="sokolova")
    ip_roles = (await client.get(f"/api/v1/persons/{SOKOLOVA}/roles")).json()["roles"]
    assert ip_roles == [
        {
            "role": "INDIVIDUAL_ENTREPRENEUR",
            "entityInn": SOKOLOVA,
            "entityName": "ИП Соколова Анна Сергеевна",
            "entityStatus": "ACTIVE",
            "since": "2023-04-12",
            "sharePercent": None,
        }
    ]


async def test_person_roles_empty_is_200_and_ten_digits_is_400(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/persons/{ORLOV}/roles")
    assert response.status_code == 200
    assert response.json()["roles"] == []
    too_short = await client.get(f"/api/v1/persons/{STANKOPROM}/roles")
    assert too_short.status_code == 400
    assert too_short.json()["code"] == "INN_INVALID"


async def test_bankruptcy_of_founder_but_not_director(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    assert (await put(admin, LEBEDEV_LLC, lebedev_llc_body())).status_code == 201
    founder = (await client.get(f"/api/v1/bankruptcies/{GROMOV}")).json()
    assert founder["meta"]["source"] == "FEDRESURS"
    assert founder["meta"]["dataActualAt"] == "2026-10-19"
    assert founder["inn"] == GROMOV
    assert founder["bankruptcies"] == [
        {
            "caseNumber": "А00-45012/2022",
            "subjectType": "PERSON",
            "stage": "COMPLETED",
            "startedAt": "2022-03-10",
            "completedAt": "2024-10-15",
        }
    ]
    director = await client.get(f"/api/v1/bankruptcies/{LEBEDEV}")
    assert director.status_code == 200
    assert director.json()["bankruptcies"] == []


async def test_no_cases_is_200_with_empty_list(client: httpx.AsyncClient) -> None:
    for inn in (STANKOPROM, ORLOV):
        response = await client.get(f"/api/v1/bankruptcies/{inn}")
        assert response.status_code == 200
        assert response.json()["bankruptcies"] == []


async def test_cases_are_sorted_newest_first_and_company_case_is_visible(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    body = stankoprom_body()
    body["bankruptcies"] = [
        {
            "subjectInn": STANKOPROM,
            "subjectType": "LEGAL_ENTITY",
            "caseNumber": "А00-1/2019",
            "stage": "COMPLETED",
            "startedAt": "2019-01-10",
            "completedAt": "2020-01-10",
        },
        {
            "subjectInn": STANKOPROM,
            "subjectType": "LEGAL_ENTITY",
            "caseNumber": "А00-2/2026",
            "stage": "OBSERVATION",
            "startedAt": "2026-09-01",
            "completedAt": None,
        },
    ]
    assert (await put(admin, STANKOPROM, body)).status_code == 201
    cases = (await client.get(f"/api/v1/bankruptcies/{STANKOPROM}")).json()["bankruptcies"]
    assert [c["caseNumber"] for c in cases] == ["А00-2/2026", "А00-1/2019"]
    assert cases[0]["completedAt"] is None


async def test_person_only_subject_with_bankruptcy(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    body = {
        "entity": None,
        "persons": [
            {
                "inn": GROMOV,
                "lastName": "Громов",
                "firstName": "Кирилл",
                "middleName": None,
                "birthDate": None,
            }
        ],
        "bankruptcies": [
            {
                "subjectInn": GROMOV,
                "subjectType": "PERSON",
                "caseNumber": "А00-7/2025",
                "stage": "PROPERTY_REALIZATION",
                "startedAt": "2025-02-01",
                "completedAt": None,
            }
        ],
    }
    assert (await put(admin, GROMOV, body)).status_code == 201
    cases = (await client.get(f"/api/v1/bankruptcies/{GROMOV}")).json()["bankruptcies"]
    assert cases[0]["stage"] == "PROPERTY_REALIZATION"
    assert (await client.get(f"/api/v1/companies/{GROMOV}")).status_code == 404
    listing = (await admin.get("/admin/subjects")).json()
    assert [(i["inn"], i["title"]) for i in listing["items"]] == [(GROMOV, "Громов Кирилл")]


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda b: b["entity"].update(kpp="009901001"), "КПП"),
        (lambda b: b["entity"]["taxAuthority"].update(code="0099"), "налоговой"),
        (lambda b: b["entity"].update(ogrn="1170000004560"), "ОГРН"),
        (lambda b: b["entity"].update(inn="0017654323"), "ИНН"),
        (lambda b: b["entity"].update(unknown=1), "Extra"),
        (lambda b: b["persons"].clear(), "persons"),
        (lambda b: b["entity"]["director"].update(fullName="Иванов Иван"), "ФИО"),
        (lambda b: b["entity"]["founders"][0].update(inn="0015557771"), "ИНН"),
        (lambda b: b["entity"]["founders"][0].update(sharePercent=101), "100"),
        (lambda b: b["entity"]["status"].update(code="status"), "status"),
    ],
)
async def test_invalid_legal_entity_is_422(
    admin: httpx.AsyncClient, mutate: Any, needle: str
) -> None:
    body = copy.deepcopy(stankoprom_body())
    mutate(body)
    response = await put(admin, STANKOPROM, body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert needle in response.text


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda e: e.update(kpp="001201001"), "kpp"),
        (lambda e: e.update(director={"fullName": "x"}), "director"),
        (lambda e: e.update(founders=[]), "founders"),
        (lambda e: e.update(authorizedCapitalRub=10000), "authorizedCapitalRub"),
        (lambda e: e.update(address={"full": "Казань"}), "address"),
        (lambda e: e.update(ogrnip="323000000123451"), "ОГРНИП"),
    ],
)
async def test_entrepreneur_with_company_fields_is_422(
    admin: httpx.AsyncClient, mutate: Any, needle: str
) -> None:
    body = sokolova_body()
    mutate(body["entity"])
    response = await put(admin, SOKOLOVA, body)
    assert response.status_code == 422, response.text
    assert needle in response.text


async def test_path_inn_must_match_card(admin: httpx.AsyncClient) -> None:
    response = await put(admin, LEBEDEV_LLC, stankoprom_body())
    assert response.status_code == 422
    assert "в пути" in response.json()["detail"]


async def test_entrepreneur_must_be_in_persons(admin: httpx.AsyncClient) -> None:
    body = sokolova_body()
    body["persons"] = []
    assert (await put(admin, SOKOLOVA, body)).status_code == 422


async def test_ogrn_must_be_unique(admin: httpx.AsyncClient) -> None:
    await put(admin, STANKOPROM, stankoprom_body())
    twin = lebedev_llc_body()
    twin["entity"]["ogrn"] = "1170000004569"
    response = await put(admin, LEBEDEV_LLC, twin)
    assert response.status_code == 422
    assert STANKOPROM in response.json()["detail"]


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda c: c.update(subjectInn="0015557771", subjectType="LEGAL_ENTITY"), "subjectInn"),
        (lambda c: c.update(subjectType="LEGAL_ENTITY"), "subjectType"),
        (lambda c: c.update(completedAt=None), "completedAt"),
        (lambda c: c.update(stage="OBSERVATION"), "completedAt"),
        (lambda c: c.update(stage="BANKRUPT"), "stage"),
        (lambda c: c.update(completedAt="2020-01-01"), "раньше"),
    ],
)
async def test_invalid_bankruptcy_is_422(
    admin: httpx.AsyncClient, mutate: Any, needle: str
) -> None:
    body = lebedev_llc_body()
    mutate(body["bankruptcies"][0])
    response = await put(admin, LEBEDEV_LLC, body)
    assert response.status_code == 422, response.text
    assert needle in response.text


async def test_duplicate_case_is_422(admin: httpx.AsyncClient) -> None:
    body = lebedev_llc_body()
    body["bankruptcies"].append(copy.deepcopy(body["bankruptcies"][0]))
    assert (await put(admin, LEBEDEV_LLC, body)).status_code == 422


async def test_put_replaces_and_get_admin_returns_same_body(
    admin: httpx.AsyncClient,
) -> None:
    await put(admin, LEBEDEV_LLC, lebedev_llc_body(), scenario="lebedev")
    view = (await admin.get(f"/admin/subjects/{LEBEDEV_LLC}")).json()
    assert view["scenarioCode"] == "lebedev"
    assert view["origin"] == "SCENARIO"
    assert view["data"]["entity"] == lebedev_llc_body()["entity"]
    assert view["data"]["persons"] == sorted(lebedev_llc_body()["persons"], key=lambda p: p["inn"])
    assert view["data"]["bankruptcies"] == lebedev_llc_body()["bankruptcies"]
    cleared = lebedev_llc_body() | {"bankruptcies": []}
    assert (await put(admin, LEBEDEV_LLC, cleared, scenario="lebedev")).status_code == 200
    data = (await admin.get(f"/admin/subjects/{LEBEDEV_LLC}")).json()["data"]
    assert data["bankruptcies"] == []


async def test_sokolova_declared_bankrupt_by_patch(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    """Пример 8.3: «Соколову признали банкротом» — PATCH со сменой статуса."""
    await put(admin, SOKOLOVA, sokolova_body(), scenario="sokolova")
    response = await admin.patch(
        f"/admin/subjects/{SOKOLOVA}",
        json={"entity": {"status": {"code": "BANKRUPT"}}},
        headers={"Content-Type": "application/merge-patch+json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["scenarioCode"] == "sokolova"
    card = (await client.get(f"/api/v1/companies/{SOKOLOVA}")).json()
    assert card["status"]["code"] == "BANKRUPT"
    assert card["person"]["fullName"] == "Соколова Анна Сергеевна"
    roles = (await client.get(f"/api/v1/persons/{SOKOLOVA}/roles")).json()["roles"]
    assert roles[0]["entityStatus"] == "BANKRUPT"


async def test_patch_adds_bankruptcy_and_replaces_array(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, SOKOLOVA, sokolova_body())
    case = {
        "subjectInn": SOKOLOVA,
        "subjectType": "PERSON",
        "caseNumber": "А00-9/2026",
        "stage": "OBSERVATION",
        "startedAt": "2026-10-01",
        "completedAt": None,
    }
    assert (
        await admin.patch(f"/admin/subjects/{SOKOLOVA}", json={"bankruptcies": [case]})
    ).status_code == 200
    cases = (await client.get(f"/api/v1/bankruptcies/{SOKOLOVA}")).json()["bankruptcies"]
    assert [c["caseNumber"] for c in cases] == ["А00-9/2026"]
    bad = await admin.patch(f"/admin/subjects/{SOKOLOVA}", json={"entity": {"kpp": "001201001"}})
    assert bad.status_code == 422


async def test_delete_subject_and_scenario(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    await put(admin, STANKOPROM, stankoprom_body(), scenario="stankoprom")
    await put(admin, LEBEDEV_LLC, lebedev_llc_body(), scenario="lebedev")
    await put(admin, SOKOLOVA, sokolova_body(), scenario=None)
    counts = (await admin.get("/admin/scenarios")).json()
    assert counts == [
        {"scenarioCode": "lebedev", "subjects": 1},
        {"scenarioCode": "stankoprom", "subjects": 1},
    ]
    runtime = (await admin.get("/admin/subjects", params={"origin": "RUNTIME"})).json()
    assert [i["inn"] for i in runtime["items"]] == [SOKOLOVA]
    assert runtime["items"][0]["title"] == "ИП Соколова Анна Сергеевна"

    assert (await admin.delete("/admin/scenarios/lebedev")).json() == {"deleted": 1}
    assert (await client.get(f"/api/v1/companies/{LEBEDEV_LLC}")).status_code == 404
    assert (await client.get(f"/api/v1/bankruptcies/{GROMOV}")).json()["bankruptcies"] == []
    assert (await client.get(f"/api/v1/companies/{STANKOPROM}")).status_code == 200

    assert (await admin.delete(f"/admin/subjects/{STANKOPROM}")).status_code == 204
    assert (await admin.delete(f"/admin/subjects/{STANKOPROM}")).status_code == 404
    assert (await client.get(f"/api/v1/persons/{KUZNETSOV}/roles")).json()["roles"] == []
    assert (await admin.get("/admin/subjects")).json()["total"] == 1


async def test_shared_person_survives_deleting_one_company(
    admin: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    other = stankoprom_body()
    other["entity"].update(
        inn=LEBEDEV_LLC,
        kpp="001901001",
        ogrn="1190000004567",
        taxAuthority={"code": "0019", "name": "ИФНС"},
        lastRecord={"grn": "2190000123454", "date": "2023-06-01"},
    )
    await put(admin, STANKOPROM, stankoprom_body())
    await put(admin, LEBEDEV_LLC, other)
    assert (await admin.delete(f"/admin/subjects/{LEBEDEV_LLC}")).status_code == 204
    roles = (await client.get(f"/api/v1/persons/{KUZNETSOV}/roles")).json()["roles"]
    assert {r["entityInn"] for r in roles} == {STANKOPROM}
    data = (await admin.get(f"/admin/subjects/{STANKOPROM}")).json()["data"]
    assert [p["inn"] for p in data["persons"]] == [KUZNETSOV]


async def test_wipe_keeps_okved_directory(admin: httpx.AsyncClient, app: FastAPI) -> None:
    await put(admin, STANKOPROM, stankoprom_body())
    assert (await admin.post("/admin/wipe")).status_code == 204
    assert (await admin.get("/admin/subjects")).json()["total"] == 0
    async with app.state.database.engine.connect() as conn:
        from sqlalchemy import text

        count = (await conn.execute(text("SELECT count(*) FROM okved"))).scalar_one()
    assert count >= 3


async def test_openapi_has_both_schemes_and_error_codes(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    schemes = spec["components"]["securitySchemes"]
    assert {"ApiKeyAuth", "AdminKeyAuth"} <= set(schemes)
    for path in (
        "/api/v1/companies/{inn}",
        "/api/v1/persons/{inn}/roles",
        "/api/v1/bankruptcies/{inn}",
    ):
        op = spec["paths"][path]["get"]
        assert {"ApiKeyAuth": []} in op["security"]
        assert {"400", "401", "403"} <= set(op["responses"])
    assert "404" in spec["paths"]["/api/v1/companies/{inn}"]["get"]["responses"]
