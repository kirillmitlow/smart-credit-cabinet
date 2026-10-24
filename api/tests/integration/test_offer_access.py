"""Старый вход и ранее выданный код не сохраняют отозванные права на договор."""

# ruff: noqa: F811 — общий стенд настоящих сессий и предложений
import pytest
from sqlalchemy import select

from app.modules import auth
from app.modules.companies.models import CompanyMember
from app.shared import db
from tests.integration.support import client_for
from tests.integration.test_offers_signing import (
    accept,
    approve_sokolova,
    sql,
    stand,  # noqa: F401 — общая фикстура
    start_signing,
    status_of,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("change", ["GUARANTOR", "SUSPENDED", "DELETED", "USER_SUSPENDED"])
async def test_revoked_old_session_cannot_read_accept_or_sign_contract(stand, change):
    app_id = approve_sokolova(stand)
    principal = stand["principals"]["sokolova:sokolova"]
    async with client_for(stand, "sokolova:sokolova") as client:
        accepted = (await accept(client, app_id)).json()
        contract_id, offer_id = accepted["contract"]["id"], accepted["offer"]["id"]
        issued = (await start_signing(client, contract_id)).json()
        with db.transaction() as session:
            member = session.scalar(
                select(CompanyMember).where(
                    CompanyMember.user_id == principal.user_id,
                    CompanyMember.company_id == principal.active_company_id,
                )
            )
            if change == "DELETED":
                session.delete(member)
            elif change == "SUSPENDED":
                member.status = change
            elif change == "USER_SUSPENDED":
                auth.get(session, principal.user_id).status = "SUSPENDED"
            else:
                member.role = change
        expected = 401 if change == "USER_SUSPENDED" else 404
        requests = [
            ("GET", f"/applications/{app_id}/offer", None),
            ("POST", f"/offers/{offer_id}/accept", {}),
            ("POST", f"/offers/{offer_id}/decline", None),
            ("GET", f"/contracts/{contract_id}", None),
            ("GET", f"/contracts/{contract_id}/document", None),
            ("POST", f"/contracts/{contract_id}/request-signature", None),
            (
                "POST",
                f"/contracts/{contract_id}/sign/request",
                {"agree": True, "acceptPepRules": True},
            ),
            (
                "POST",
                f"/contracts/{contract_id}/sign",
                {"requestId": issued["requestId"], "code": issued["demoCode"]},
            ),
        ]
        for method, path, body in requests:
            response = await client.request(
                method, path, **({"json": body} if body is not None else {})
            )
            assert response.status_code == expected, (path, response.text)
            assert "500000" not in response.text
        assert status_of(app_id) == "OFFER_ACCEPTED"
        assert sql("SELECT count(*) FROM signatures")[0][0] == 0
        assert not any(name == "disbursement.run" for name, _ in stand["sent"])


async def test_changed_director_roles_update_buttons_handoff_and_signing_permission(stand):
    app_id = approve_sokolova(stand)
    former, successor = [stand["principals"][f"sokolova:{who}"] for who in ("sokolova", "petrova")]
    async with (
        client_for(stand, "sokolova:sokolova") as old_director,
        client_for(stand, "sokolova:petrova") as new_director,
    ):
        contract_id = (await accept(old_director, app_id)).json()["contract"]["id"]
        with db.transaction() as session:
            for user_id, role in ((former.user_id, "ACCOUNTANT"), (successor.user_id, "DIRECTOR")):
                session.scalar(
                    select(CompanyMember).where(
                        CompanyMember.user_id == user_id,
                        CompanyMember.company_id == former.active_company_id,
                    )
                ).role = role
        old_view = (await old_director.get(f"/contracts/{contract_id}")).json()
        assert old_view["canSign"] is False
        assert old_view["canPassToDirector"] is True
        assert (await start_signing(old_director, contract_id)).status_code == 403
        assert (
            await old_director.post(f"/contracts/{contract_id}/request-signature")
        ).status_code == 200
        new_view = (await new_director.get(f"/contracts/{contract_id}")).json()
        assert new_view["canSign"] is True
        assert new_view["canPassToDirector"] is False
        assert (await start_signing(new_director, contract_id)).status_code == 200
