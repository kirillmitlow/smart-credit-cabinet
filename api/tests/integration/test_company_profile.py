"""T-220: автозаполнение, недоступность, кэш и доступ на настоящих Postgres/Valkey."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, text

from app.modules.companies import profile
from app.modules.companies.models import Company
from app.modules.integrations import Ok, SelfEmployedStatus, SnapshotMeta, System
from app.modules.integrations.registry import map_roles
from app.shared import clock, db
from tests.fixtures import pipeline_world as pw
from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = pytest.mark.integration
INN = pw.SOKOLOVA_INN
LLC = "0017654322"
PERSON = "001310000115"
ORLOV = "001310000436"
FIRMS = [
    Firm(
        "sokolova",
        INN,
        "ИП Соколова",
        kind="IP",
        members=[
            Member("boss", "Соколова", "DIRECTOR", INN),
            Member("guarantor", "Поручитель", "GUARANTOR", PERSON),
        ],
    ),
    Firm(
        "stankoprom",
        LLC,
        "ООО СтанкоПром",
        members=[Member("boss", "Кузнецов", "DIRECTOR", PERSON)],
    ),
    Firm(
        "orlov",
        ORLOV,
        "Орлов",
        kind="SELF_EMPLOYED",
        members=[Member("owner", "Орлов", "DIRECTOR", ORLOV)],
    ),
]


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    with make_stand(postgres_url, redis_url, monkeypatch, FIRMS) as result:
        world = pw.sokolova_world()
        world.tax[INN]["taxRegimes"][0]["year"] = 2026
        world.registry[LLC] = {
            "type": "LEGAL_ENTITY",
            "inn": LLC,
            "shortName": "ООО СтанкоПром",
            "registrationDate": "2017-03-14",
            "status": {"code": "ACTIVE"},
            "director": {"fullName": "Кузнецов", "inn": PERSON},
        }
        world.tax[LLC] = pw.tax_profile(LLC, "OSNO")
        ports = pw.build_integrations(world)
        monkeypatch.setattr(profile, "get_integrations", lambda: ports)
        result.update(world=world, ports=ports)
        try:
            yield result
        finally:
            with db.transaction() as session:
                session.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))


async def test_profile_sources_dates_cache_and_explicit_refresh(stand: dict[str, Any]) -> None:
    world = stand["world"]
    company_id = stand["companies"]["sokolova"]
    async with client_for(stand, "sokolova:boss") as client:
        response = await client.get(f"/companies/lookup/{INN}")
        assert response.status_code == 200
        data = response.json()
        assert data["companyId"] == str(company_id)
        assert data["eligibility"] == "ELIGIBLE"
        fields = data["fields"]
        for key, source in [
            ("name", "registry"),
            ("taxRegime", "tax"),
            ("isBankCustomer", "bank_core"),
        ]:
            assert fields[key]["confirmed"] is True
            assert fields[key]["retrievedAt"]
            assert fields[key]["source"] == source
        assert fields["taxRegime"]["value"] == "USN_INCOME"
        assert fields["isBankCustomer"]["value"] is True
        assert (await client.get(f"/companies/{company_id}")).json() == data
        assert world.count("registry:company", INN) == 1
        await client.get(f"/companies/lookup/{INN}")
        assert world.count("registry:company", INN) == 2
        with db.transaction() as session:
            row = session.get(Company, company_id)
            row.profile_fetched_at -= timedelta(days=2)
        assert (await client.get(f"/companies/{company_id}")).status_code == 200
        assert world.count("registry:company", INN) == 3


async def test_registry_down_keeps_card_unconfirmed_and_other_sources(
    stand: dict[str, Any],
) -> None:
    stand["world"].down.add("registry:company")
    async with client_for(stand, "sokolova:boss") as client:
        response = await client.get(f"/companies/lookup/{INN}")
    assert response.status_code == 200
    body = response.json()
    assert body["eligibility"] == "UNCONFIRMED"
    assert body["fields"]["name"] == {
        "value": "ИП Соколова",
        "source": "registry",
        "retrievedAt": None,
        "confirmed": False,
    }
    assert body["fields"]["address"]["confirmed"] is False
    assert body["fields"]["taxRegime"]["confirmed"] is True


async def test_all_sources_down_still_returns_manual_card(stand: dict[str, Any]) -> None:
    stand["world"].down.update({"registry:company", "tax:profile", "tax:sme", "bank_core:customer"})
    async with client_for(stand, "sokolova:boss") as client:
        response = await client.get(f"/companies/lookup/{INN}")
    assert response.status_code == 200
    assert all(not field["confirmed"] for field in response.json()["fields"].values())


async def test_liquidating_company_and_bank_non_customer(stand: dict[str, Any]) -> None:
    world = stand["world"]
    world.registry[LLC]["status"]["code"] = "LIQUIDATING"
    async with client_for(stand, "stankoprom:boss") as client:
        body = (await client.get(f"/companies/lookup/{LLC}")).json()
    assert body["eligibility"] == "COMPANY_NOT_ACTIVE"
    assert body["fields"]["directorName"]["value"] == "Кузнецов"
    assert body["fields"]["isBankCustomer"]["value"] is False
    assert body["fields"]["isBankCustomer"]["confirmed"] is True


async def test_foreign_and_guarantor_cannot_read_profile_before_network(
    stand: dict[str, Any],
) -> None:
    async with client_for(stand, "sokolova:boss") as client:
        for path in (f"/companies/lookup/{LLC}", f"/companies/{stand['companies']['stankoprom']}"):
            assert (await client.get(path)).status_code == 404
        assert (await client.get("/companies/lookup/0017654323")).status_code == 422
    async with client_for(stand, "sokolova:guarantor") as client:
        assert (await client.get(f"/companies/lookup/{INN}")).status_code == 404
    assert stand["world"].calls == []


async def test_self_employed_and_personal_inn_roles(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ports = stand["ports"]

    def roles(inn: str) -> Any:
        return Ok(
            map_roles(
                {
                    "personInn": inn,
                    "roles": [{"role": "DIRECTOR", "entityInn": LLC, "entityName": "СтанкоПром"}],
                }
            ),
            SnapshotMeta(System.REGISTRY, None, None, clock.system_now()),
        )

    monkeypatch.setattr(ports.registry, "get_person_roles", roles, raising=False)
    monkeypatch.setattr(
        ports.tax,
        "get_self_employed_status",
        lambda inn: Ok(
            SelfEmployedStatus(inn, inn == ORLOV, clock.today()),
            SnapshotMeta(System.TAX, None, None, clock.system_now()),
        ),
    )
    async with client_for(stand, "orlov:owner") as client:
        body = (await client.get(f"/companies/lookup/{ORLOV}")).json()
    assert body["eligibility"] == "NOT_ELIGIBLE"
    assert body["relatedCompanies"] == []  # чужая компания из ролей не раскрывается
    async with client_for(stand, "stankoprom:boss") as client:
        body = (await client.get(f"/companies/lookup/{PERSON}")).json()
    assert body["eligibility"] == "PERSON_ROLES"
    assert body["relatedCompanies"][0]["id"] == str(stand["companies"]["stankoprom"])
    with db.transaction() as session:
        assert session.scalar(select(Company.inn).where(Company.inn == PERSON)) is None


async def test_profile_limit_is_per_session(stand: dict[str, Any]) -> None:
    path = f"/companies/{stand['companies']['sokolova']}"
    async with client_for(stand, "sokolova:boss") as client:
        for _ in range(30):
            assert (await client.get(path)).status_code == 200
        response = await client.get(path)
        assert response.status_code == 429
        assert response.json()["code"] == "RATE_LIMITED"
        assert 1 <= int(response.headers["Retry-After"]) <= 60
    async with client_for(stand, "sokolova:boss") as another:
        assert (await another.get(path)).status_code == 200
