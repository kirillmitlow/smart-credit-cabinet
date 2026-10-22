"""T-224: маппинг ЕИС, часовой кэш, пагинация, доступ и недоступность."""

from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from redis import RedisError
from sqlalchemy import text

from app.modules.companies import gov_contracts
from app.modules.integrations import (
    GovContract,
    Ok,
    Reason,
    SnapshotMeta,
    SourceUnavailable,
    System,
)
from app.shared import clock, db
from app.shared.cache import get_redis
from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = pytest.mark.integration
INN = "0017654322"


def contract(number: str, **changes: Any) -> GovContract:
    return GovContract(
        **{
            "registry_number": number,
            "customer_name": "Городская больница",
            "customer_inn": "0010000000",
            "subject": "Поставка медицинских изделий",
            "price_rub": 12_000_000,
            "paid_rub": 3_000_000,
            "concluded_at": date(2026, 9, 21),
            "execution_deadline": date(2026, 12, 21),
            "payment_deadline": date(2027, 1, 21),
            "status": "IN_PROGRESS",
            **changes,
        }
    )


class Tax:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.down = False
        self.items = (
            contract("1000000000000000001", concluded_at=date(2026, 8, 1)),
            contract("1000000000000000002", status="EXECUTED", paid_rub=12_000_000),
            contract("1000000000000000003"),
        )

    def get_gov_contracts(self, inn: str) -> Any:
        self.calls.append(inn)
        if self.down:
            return SourceUnavailable(System.TAX, Reason.TIMEOUT, attempts=3, resource="eis")
        return Ok(self.items, SnapshotMeta(System.TAX, "EIS", "req-eis", clock.system_now()))


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    firms = [
        Firm(
            "snab",
            INN,
            "СнабКонтракт",
            members=[
                Member("boss", "Директор", "DIRECTOR", None),
                Member("guarantor", "Поручитель", "GUARANTOR", None),
            ],
        ),
        Firm("other", "0010000000", "Чужая", members=[Member("boss", "Другой", "DIRECTOR", None)]),
    ]
    with make_stand(postgres_url, redis_url, monkeypatch, firms) as result:
        tax = Tax()
        monkeypatch.setattr(gov_contracts, "get_integrations", lambda: SimpleNamespace(tax=tax))
        result["tax"] = tax
        result["path"] = f"/companies/{result['companies']['snab']}/gov-contracts"
        try:
            yield result
        finally:
            with db.transaction() as session:
                session.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))


async def test_mapping_cache_filter_and_pages(stand: dict[str, Any]) -> None:
    path = stand["path"]
    async with client_for(stand, "snab:boss") as client:
        first = (await client.get(path, params={"limit": 1})).json()
        item = first["items"][0]
        assert item["registryNumber"] == "1000000000000000003"
        assert item["priceRub"] == 12_000_000
        assert item["unpaidRub"] == 9_000_000
        assert item["paymentDeadline"] == "2027-01-21"
        assert first["retrievedAt"]
        assert first["source"] == "EIS"
        rest = (await client.get(path, params={"cursor": first["nextCursor"], "limit": 2})).json()
        assert [x["registryNumber"] for x in rest["items"]] == [
            "1000000000000000002",
            "1000000000000000001",
        ]
        assert rest["items"][0]["unpaidRub"] == 0
        assert rest["nextCursor"] is None
        filtered = (await client.get(path, params={"status": "IN_PROGRESS"})).json()
        assert len(filtered["items"]) == 2
        assert stand["tax"].calls == [INN]
        key = gov_contracts.CACHE_PREFIX + str(stand["companies"]["snab"])
        assert 1 <= get_redis().ttl(key) <= 3600
        get_redis().expire(key, 0)
        assert (await client.get(path)).status_code == 200
        assert stand["tax"].calls == [INN, INN]


async def test_source_down_is_problem_and_retry_recovers(stand: dict[str, Any]) -> None:
    stand["tax"].down = True
    async with client_for(stand, "snab:boss") as client:
        response = await client.get(stand["path"])
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "SERVICE_UNAVAILABLE"
        assert response.json()["requestId"]
        assert "Не удалось получить список" in response.json()["detail"]
        stand["tax"].down = False
        assert (await client.get(stand["path"])).status_code == 200
        assert stand["tax"].calls == [INN, INN]


async def test_foreign_and_guarantor_forbidden_before_source(stand: dict[str, Any]) -> None:
    for who in ("other:boss", "snab:guarantor"):
        async with client_for(stand, who) as client:
            assert (await client.get(stand["path"])).status_code == 404
    assert stand["tax"].calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"cursor": "bad"},
        {"cursor": "1999999999999999999"},
        {"status": "UNKNOWN"},
    ],
)
async def test_invalid_page_parameters(stand: dict[str, Any], params: dict[str, Any]) -> None:
    async with client_for(stand, "snab:boss") as client:
        assert (await client.get(stand["path"], params=params)).status_code == 422


async def test_empty_and_corrupt_cache(stand: dict[str, Any]) -> None:
    stand["tax"].items = ()
    key = gov_contracts.CACHE_PREFIX + str(stand["companies"]["snab"])
    get_redis().set(key, "broken cache", ex=3600)
    async with client_for(stand, "snab:boss") as client:
        for _ in range(2):
            body = (await client.get(stand["path"])).json()
            assert body["items"] == []
            assert body["nextCursor"] is None
    assert stand["tax"].calls == [INN]


async def test_cache_down_does_not_hide_available_source(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenCache:
        def get(self, *_args: Any) -> None:
            raise RedisError("cache offline")

        def set(self, *_args: Any, **_kwargs: Any) -> None:
            raise RedisError("cache offline")

    monkeypatch.setattr(gov_contracts, "get_redis", BrokenCache)
    async with client_for(stand, "snab:boss") as client:
        assert (await client.get(stand["path"])).status_code == 200
        assert (await client.get(stand["path"])).status_code == 200
    assert stand["tax"].calls == [INN, INN]
