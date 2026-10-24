# ruff: noqa: F811
"""T-256: явное подтверждение, безопасные повторы и закрытие задач."""

import asyncio
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.modules.applications.models import Application, ApplicationEvent, Task
from app.shared import db
from tests.integration.test_applications import TERMS, sokolova, stand  # noqa: F401 — фикстуры

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("body", [None, {}, {"confirmed": False}])
async def test_withdraw_requires_confirmation(
    sokolova: httpx.AsyncClient, body: dict | None
) -> None:
    application_id = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    with db.transaction() as session:
        session.get(Application, UUID(application_id)).status = "SUBMITTED"
    response = await sokolova.post(f"/applications/{application_id}/withdraw", json=body)
    assert response.status_code == 422
    assert (await sokolova.get(f"/applications/{application_id}")).json()["status"] == "SUBMITTED"
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ApplicationEvent)
                .where(ApplicationEvent.to_status == "WITHDRAWN")
            )
            == 0
        )


@pytest.mark.parametrize(
    "status",
    [
        "SUBMITTED",
        "CHECKING",
        "NEEDS_INFO",
        "MANUAL_REVIEW",
        "APPROVED",
        "COUNTER_OFFER",
        "OFFER_ACCEPTED",
    ],
)
async def test_concurrent_withdrawals_return_one_result_and_cancel_tasks_once(
    sokolova: httpx.AsyncClient, status: str
) -> None:
    application_id = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    with db.transaction() as session:
        application = session.get(Application, UUID(application_id))
        application.status = status
        session.add(
            Task(
                application_id=application.id,
                round=1,
                kind="EXPLANATION",
                title="Пояснение",
                why_text="Проверка",
                status="OPEN",
                created_by_actor="UNDERWRITER",
            )
        )
    replies = await asyncio.gather(
        *(
            sokolova.post(f"/applications/{application_id}/withdraw", json={"confirmed": True})
            for _ in range(2)
        )
    )
    assert [r.status_code for r in replies] == [200, 200]
    assert all(r.json()["status"] == "WITHDRAWN" for r in replies)
    assert replies[0].json()["version"] == replies[1].json()["version"]
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ApplicationEvent)
                .where(ApplicationEvent.to_status == "WITHDRAWN")
            )
            == 1
        )
        task = session.scalar(select(Task))
        assert (task.status, task.cancel_reason) == ("CANCELLED", "APPLICATION_WITHDRAWN")
        assert (
            session.scalar(
                select(func.count())
                .select_from(ApplicationEvent)
                .where(ApplicationEvent.step_code == "TASK_CANCELLED")
            )
            == 1
        )


@pytest.mark.parametrize(
    "status", ["DRAFT", "SIGNED", "DISBURSING", "DISBURSED", "REJECTED", "EXPIRED"]
)
async def test_withdraw_forbidden_after_signing_or_closure(
    sokolova: httpx.AsyncClient, status: str
) -> None:
    application_id = (await sokolova.post("/applications", json=TERMS)).json()["id"]
    with db.transaction() as session:
        session.get(Application, UUID(application_id)).status = status
    response = await sokolova.post(
        f"/applications/{application_id}/withdraw", json={"confirmed": True}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_TRANSITION"
    assert (await sokolova.get(f"/applications/{application_id}")).json()["status"] == status
