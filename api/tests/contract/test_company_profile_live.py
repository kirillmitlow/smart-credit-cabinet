"""T-220: карточки ИП, ООО, ликвидации и НПД через API на живых моках."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text

from app.modules.companies import profile
from app.modules.integrations import Integrations
from app.shared import db
from tests.contract.conftest import Persona
from tests.integration.conftest import postgres_url, redis_url  # noqa: F401 — Testcontainers
from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@pytest.mark.parametrize(
    ("name", "kind", "eligibility"),
    [
        ("sokolova", "IP", "ELIGIBLE"),
        ("stankoprom", "LEGAL", "ELIGIBLE"),
        ("vektor", "LEGAL", "COMPANY_NOT_ACTIVE"),
        ("orlov", "SELF_EMPLOYED", "NOT_ELIGIBLE"),
    ],
)
async def test_live_company_card(
    name: str,
    kind: str,
    eligibility: str,
    postgres_url: str,  # noqa: F811
    redis_url: str,  # noqa: F811
    persona: Callable[[str], Persona],
    live: Integrations,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = persona(name)
    member = Member("owner", "Владелец", "DIRECTOR", p.inn if kind != "LEGAL" else None)
    firm = Firm(name, p.inn, name, kind=kind, members=[member])
    with make_stand(postgres_url, redis_url, monkeypatch, [firm]) as stand:
        monkeypatch.setattr(profile, "get_integrations", lambda: live)
        try:
            async with client_for(stand, f"{name}:owner") as client:
                response = await client.get(f"/companies/lookup/{p.inn}")
                assert response.status_code == 200, response.text
                body: dict[str, Any] = response.json()
                assert body["eligibility"] == eligibility
                assert body["form"] == kind
                fields = body["fields"]
                if kind == "SELF_EMPLOYED":
                    assert fields["isSelfEmployed"]["value"] is True
                else:
                    for key, source in [
                        ("name", "registry"),
                        ("taxDebtRub", "tax"),
                        ("isBankCustomer", "bank_core"),
                    ]:
                        assert fields[key]["confirmed"] is True, (key, fields[key])
                        assert fields[key]["source"] == source
                        assert fields[key]["retrievedAt"] is not None
                    if kind == "LEGAL":
                        assert fields["directorName"]["value"]
                    else:
                        assert fields["directorName"]["confirmed"] is False
                assert (await client.get("/applications")).json()["items"] == []
        finally:
            with db.transaction() as session:
                session.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))
