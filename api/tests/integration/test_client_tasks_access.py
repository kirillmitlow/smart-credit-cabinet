"""Права задач проверяются по БД, даже если сессия ещё хранит роль директора."""

# ruff: noqa: F811
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import select, text

from app.modules import auth
from app.modules.applications import Application
from app.modules.applications.models import Task
from app.modules.companies.models import CompanyMember
from app.shared import db
from tests.integration.support import client_for
from tests.integration.test_client_tasks_http import stand  # noqa: F401

pytestmark = pytest.mark.integration
PERSON = "770100000001"
OTHER_PERSON = "770100000009"


@pytest.fixture
def acl_stand(stand: dict[str, Any]) -> Iterator[dict[str, Any]]:
    database = db.get_database()
    try:
        principal = stand["principals"]["a:d"]
        stand["principals"]["a:d"] = replace(principal, person_inn=PERSON)
        with database.transaction() as session:
            user = auth.get(session, principal.user_id)
            assert user is not None
            user.person_inn = PERSON
            other = auth.upsert_client(
                session,
                login_ref="t:acl:guarantor",
                display_name="Другой поручитель",
                person_inn=OTHER_PERSON,
                scenario_code=None,
            )
            session.add(
                CompanyMember(
                    company_id=principal.active_company_id,
                    user_id=other.id,
                    role="GUARANTOR",
                    status="ACTIVE",
                    poa_permissions=[],
                )
            )
            common = session.scalar(select(Task))
            assert common is not None
            stand["common_task"] = common.id
            for inn in (PERSON, OTHER_PERSON):
                task = Task(
                    application_id=stand["application_id"],
                    round=1,
                    kind="EXPLANATION",
                    title=f"Личная задача {inn}",
                    why_text="Личное подтверждение",
                    assignee_person_inn=inn,
                    status="OPEN",
                    created_by_actor="UNDERWRITER",
                )
                session.add(task)
                session.flush()
                stand[inn] = task.id
            # Раунд готов: отказ submit должен быть именно по правам, а не из-за ответов.
            for task in session.scalars(select(Task)):
                task.answer = {"text": "Сохранено до смены прав"}
        yield stand
    finally:
        with database.transaction() as session:
            session.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))


def change_access(stand: dict[str, Any], change: str) -> None:
    principal = stand["principals"]["a:d"]
    with db.transaction() as session:
        member = session.scalar(
            select(CompanyMember).where(
                CompanyMember.user_id == principal.user_id,
                CompanyMember.company_id == principal.active_company_id,
            )
        )
        assert member is not None
        if change == "GUARANTOR":
            member.role = change
        elif change == "DELETED_MEMBER":
            session.delete(member)
        elif change == "SUSPENDED_MEMBER":
            member.status = "SUSPENDED"
        else:
            user = auth.get(session, principal.user_id)
            assert user is not None
            if change == "SUSPENDED_USER":
                user.status = "SUSPENDED"
            else:
                user.role, user.level = "UNDERWRITER", "L2"


@pytest.mark.parametrize(
    "change", ["GUARANTOR", "DELETED_MEMBER", "SUSPENDED_MEMBER", "SUSPENDED_USER", "BANK_ROLE"]
)
@pytest.mark.parametrize("operation", ["list", "answer", "submit"])
async def test_old_session_uses_current_task_access(acl_stand, change, operation):
    app_id = acl_stand["application_id"]
    async with client_for(acl_stand, "a:d") as client:
        assert (await client.get(f"/applications/{app_id}/tasks")).status_code == 200
        change_access(acl_stand, change)
        if operation == "list":
            response = await client.get(f"/applications/{app_id}/tasks")
        elif operation == "answer":
            response = await client.post(
                f"/tasks/{acl_stand['common_task']}/answer", json={"text": "Недопустимая правка"}
            )
        else:
            response = await client.post(f"/applications/{app_id}/tasks/submit")
        if change == "GUARANTOR" and operation == "list":
            assert response.status_code == 200
            body = response.json()
            assert [t["id"] for t in body["items"]] == [str(acl_stand[PERSON])]
            assert body["items"][0]["canAnswer"] is True
            assert body["canSubmit"] is False
        else:
            expected = 401 if change in {"SUSPENDED_USER", "BANK_ROLE"} else 404
            if change == "GUARANTOR" and operation == "submit":
                expected = 403
            assert response.status_code == expected
    with db.transaction() as session:
        assert session.get(Application, app_id).status == "NEEDS_INFO"
        assert all(
            t.status == "OPEN" and t.answer == {"text": "Сохранено до смены прав"}
            for t in session.scalars(select(Task))
        )
    assert acl_stand["sent"] == []


@pytest.mark.parametrize("cached_role", ["DIRECTOR", "GUARANTOR"])
async def test_guarantor_can_answer_only_own_personal_task(acl_stand, cached_role):
    app_id = acl_stand["application_id"]
    principal = acl_stand["principals"]["a:d"]
    acl_stand["principals"]["a:d"] = replace(
        principal, memberships=(auth.Membership(principal.active_company_id, cached_role),)
    )
    async with client_for(acl_stand, "a:d") as client:
        change_access(acl_stand, "GUARANTOR")
        for task_id in (acl_stand["common_task"], acl_stand[OTHER_PERSON]):
            response = await client.post(f"/tasks/{task_id}/answer", json={"text": "Чужое"})
            assert response.status_code == 404
        own_path = f"/tasks/{acl_stand[PERSON]}/answer"
        response = await client.post(own_path, json={"text": "Мой ответ"})
        assert response.status_code == 200
        assert response.json()["draftAnswer"] == "Мой ответ"
        assert response.json()["canAnswer"] is True
        # Встроенная отправка раунда также запрещена и откатывает новый черновик.
        response = await client.post(own_path, json={"text": "Не сохранять", "submitRound": True})
        assert response.status_code == 403
        listing = (await client.get(f"/applications/{app_id}/tasks")).json()
        assert listing["canSubmit"] is False
        assert listing["items"][0]["draftAnswer"] == "Мой ответ"


@pytest.mark.parametrize("role", ["DIRECTOR", "ACCOUNTANT"])
async def test_current_company_roles_keep_answer_and_submit_access(acl_stand, role):
    app_id = acl_stand["application_id"]
    async with client_for(acl_stand, "a:d") as client:
        with db.transaction() as session:
            principal = acl_stand["principals"]["a:d"]
            member = session.scalar(
                select(CompanyMember).where(CompanyMember.user_id == principal.user_id)
            )
            member.role = role
        response = await client.post(
            f"/tasks/{acl_stand['common_task']}/answer", json={"text": "Ответ компании"}
        )
        assert response.status_code == 200
        listing = (await client.get(f"/applications/{app_id}/tasks")).json()
        assert listing["canSubmit"] is True
        assert (await client.post(f"/applications/{app_id}/tasks/submit")).status_code == 200
