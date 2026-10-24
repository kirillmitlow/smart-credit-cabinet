"""Права на выданный кредит и график проверяются по БД, а не снимку старой сессии."""

# ruff: noqa: F811 — общий стенд с настоящими Postgres, Redis и клиентскими сессиями
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.modules import auth, loans
from app.modules.applications import Application
from app.modules.companies.models import CompanyMember
from app.shared import clock, db
from tests.integration.test_applications import client_for, stand  # noqa: F401 — общая фикстура

pytestmark = pytest.mark.integration
OWNER = "001234567887"
OTHER = "0017654322"


@pytest.fixture(autouse=True)
def _clean_loan_data(stand: dict[str, Any]) -> Iterator[None]:
    """Общий stand очищает БД только до теста; не оставляем свои роли набору входа."""
    database = db.get_database()
    try:
        yield
    finally:
        # Зависимость от stand запускает очистку до закрытия его соединений.
        with database.transaction() as session:
            session.execute(
                text("TRUNCATE applications, company_members, companies, users, outbox CASCADE")
            )


def open_loan(stand: dict[str, Any], owner: str = OWNER) -> UUID:
    principal = stand["principals"][owner]
    with db.transaction() as session:
        application = Application(
            number=f"ТЕСТ-{owner}", company_id=principal.active_company_id,
            created_by=principal.user_id, status="DISBURSED", product_code="EXPRESS",
            amount_rub=500_000, term_months=12, draft={}, flags=[], closed_at=clock.now(),
        )  # fmt: skip
        session.add(application)
        session.flush()
        loan = loans.open_loan(session, loans.NewLoan(
            company_id=application.company_id, application_id=application.id,
            disbursement_id=uuid4(), bank_core_loan_id=f"loan_{owner}",
            contract_number=f"КД-{owner}", contract_uid=str(uuid4()), product_code="EXPRESS",
            kind="LOAN", repayment_type="ANNUITY", amount_rub=500_000, limit_rub=None,
            rate_percent=Decimal("24"), term_months=12, loan_account="45406810000000000001",
            settlement_account="40802810800000001234", opened_on=clock.today(),
        ))  # fmt: skip
        return loan.id


def member(session, stand, owner=OWNER):
    principal = stand["principals"][owner]
    return session.scalar(
        select(CompanyMember).where(
            CompanyMember.user_id == principal.user_id,
            CompanyMember.company_id == principal.active_company_id,
        )
    )


@pytest.mark.parametrize("change", ["GUARANTOR", "SUSPENDED", "DELETED"])
async def test_old_director_session_loses_loan_and_schedule_access(stand, change):
    loan_id = open_loan(stand)
    async with await client_for(stand, OWNER) as client:
        assert len((await client.get("/loans")).json()["items"]) == 1
        assert (await client.get(f"/loans/{loan_id}")).status_code == 200
        assert len((await client.get(f"/loans/{loan_id}/schedule")).json()) == 12
        with db.transaction() as session:
            row = member(session, stand)
            if change == "DELETED":
                session.delete(row)
            elif change == "SUSPENDED":
                row.status = change
            else:
                row.role = change
        assert (await client.get("/loans")).json()["items"] == []
        for path in (f"/loans/{loan_id}", f"/loans/{loan_id}/schedule"):
            response = await client.get(path)
            assert response.status_code == 404
            assert "500000" not in response.text


@pytest.mark.parametrize("change", ["SUSPENDED", "BANK_ROLE"])
async def test_inactive_or_changed_user_cannot_reuse_a_client_session(stand, change):
    loan_id = open_loan(stand)
    async with await client_for(stand, OWNER) as client:
        with db.transaction() as session:
            user = auth.get(session, stand["principals"][OWNER].user_id)
            if change == "SUSPENDED":
                user.status = change
            else:
                user.role, user.level = "UNDERWRITER", "L2"
        for path in ("/loans", f"/loans/{loan_id}", f"/loans/{loan_id}/schedule"):
            assert (await client.get(path)).status_code == 401


async def test_each_company_uses_its_current_role_and_accountant_keeps_access(stand):
    first, second = open_loan(stand), open_loan(stand, OTHER)
    principal = stand["principals"][OWNER]
    other_company = stand["principals"][OTHER].active_company_id
    stand["principals"][OWNER] = replace(
        principal,
        memberships=(
            auth.Membership(principal.active_company_id, "DIRECTOR"),
            auth.Membership(other_company, "DIRECTOR"),
        ),
    )
    with db.transaction() as session:
        member(session, stand).role = "ACCOUNTANT"
        session.add(
            CompanyMember(
                company_id=other_company,
                user_id=principal.user_id,
                role="GUARANTOR",
                status="ACTIVE",
                poa_permissions=[],
            )
        )
    async with await client_for(stand, OWNER) as client:
        items = (await client.get("/loans")).json()["items"]
        assert [item["id"] for item in items] == [str(first)]
        assert (await client.get(f"/loans/{first}")).status_code == 200
        assert (await client.get(f"/loans/{second}")).status_code == 404
        assert (await client.get(f"/loans/{second}/schedule")).status_code == 404
