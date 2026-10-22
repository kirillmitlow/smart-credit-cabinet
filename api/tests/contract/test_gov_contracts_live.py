"""T-224: ЕИС «СнабКонтракт» доступен через API выбора контракта."""

from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import text

from app.modules.companies import gov_contracts
from app.modules.integrations import Integrations
from app.shared import clock, db
from tests.contract.conftest import Persona
from tests.integration.conftest import postgres_url, redis_url  # noqa: F401 — Testcontainers
from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = [pytest.mark.contract, pytest.mark.integration]


async def test_snabkontrakt_list_from_live_eis(
    postgres_url: str,  # noqa: F811
    redis_url: str,  # noqa: F811
    persona: Callable[[str], Persona],
    live: Integrations,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = persona("snabkontrakt")
    firm = Firm(
        "snab", p.inn, "СнабКонтракт", members=[Member("boss", "Директор", "DIRECTOR", None)]
    )
    with make_stand(postgres_url, redis_url, monkeypatch, [firm]) as stand:
        monkeypatch.setattr(gov_contracts, "get_integrations", lambda: live)
        try:
            async with client_for(stand, "snab:boss") as client:
                path = f"/companies/{stand['companies']['snab']}/gov-contracts"
                response = await client.get(path, params={"status": "IN_PROGRESS"})
                assert response.status_code == 200, response.text
                body = response.json()
                assert len(body["items"]) == 1
                contract = body["items"][0]
                assert contract["priceRub"] == 12_000_000
                assert contract["unpaidRub"] == 12_000_000
                assert date.fromisoformat(contract["paymentDeadline"]) > clock.today()
                assert len(contract["registryNumber"]) == 19
                assert body["retrievedAt"]
                assert body["nextCursor"] is None
        finally:
            with db.transaction() as session:
                session.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))
