# ruff: noqa: F811
"""T-255: HTTP-проекция с настоящими журналом, ролями и изоляцией компаний."""

from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.modules import applications
from app.modules.applications.models import Application
from app.modules.companies.models import CompanyMember
from app.shared import db
from tests.integration.test_applications import (  # noqa: F401 — фикстуры
    TERMS,
    sokolova,
    stand,
    stranger,
    submit,
)

pytestmark = pytest.mark.integration


async def test_timeline_contains_only_safe_check_states_and_is_company_scoped(
    sokolova: httpx.AsyncClient, stranger: httpx.AsyncClient
) -> None:
    created = (await sokolova.post("/applications", json=TERMS)).json()
    application_id = created["id"]
    assert (await submit(sokolova, application_id)).status_code == 200
    with db.transaction() as session:
        application = session.get(Application, UUID(application_id))
        assert application is not None
        applications.transition(
            session, application, applications.Status.CHECKING, actor=applications.Actor.SYSTEM
        )
        source = applications.record_event(
            session,
            application,
            "STEP",
            actor_type=applications.Actor.SYSTEM,
            step_code="SOURCES",
            payload={"unavailable": ["tax:profile"], "private": "secret-bank-data"},
        )
        last_id = source.id
    response = await sokolova.get(f"/applications/{application_id}/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["applicationId"] == application_id
    assert body["lastEventId"] == last_id
    assert len(body["steps"]) == 6
    assert body["steps"][1]["state"] == "running"
    assert [c["state"] for c in body["checks"]] == ["done", "delayed", "running", "done"]
    assert "secret-bank-data" not in response.text
    assert "tax:profile" not in response.text
    assert (await stranger.get(f"/applications/{application_id}/timeline")).status_code == 404


@pytest.mark.parametrize("role", ["ACCOUNTANT", "GUARANTOR", None])
async def test_timeline_checks_current_membership_not_cached_cookie(
    sokolova: httpx.AsyncClient, stand: dict[str, Any], role: str | None
) -> None:
    application_id = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    who = stand["principals"]["001234567887"]
    with db.transaction() as session:
        member = session.scalar(
            select(CompanyMember).where(
                CompanyMember.company_id == who.active_company_id,
                CompanyMember.user_id == who.user_id,
            )
        )
        assert member is not None
        if role is None:
            member.status = "SUSPENDED"
        else:
            member.role = role
    response = await sokolova.get(f"/applications/{application_id}/timeline")
    assert response.status_code == (200 if role == "ACCOUNTANT" else 404)
