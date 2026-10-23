"""T-351: HTTP-ручки «Что нужно от вас» — список, ответ, отправка раунда, чужая компания."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.modules import applications
from app.modules.applications import Actor, Application, ApplicationVersion, TaskSpec
from app.shared import db
from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = pytest.mark.integration


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    firms = [
        Firm("a", "0017654322", "СтанкоПром", members=[Member("d", "Директор", "DIRECTOR", None)]),
        Firm("b", "001234567887", "Чужая", members=[Member("d", "Чужой", "DIRECTOR", None)]),
    ]
    with make_stand(postgres_url, redis_url, monkeypatch, firms) as stand:
        with db.transaction() as s:
            application = Application(
                number="АЗ-2026-000001",
                company_id=stand["companies"]["a"],
                created_by=stand["principals"]["a:d"].user_id,
                status="MANUAL_REVIEW",
                version=5,
                product_code="EXPRESS",
                amount_rub=500_000,
                term_months=12,
                draft={},
                flags=[],
            )
            s.add(application)
            s.flush()
            version = ApplicationVersion(
                application_id=application.id,
                number=1,
                reason="SUBMIT",
                data={"productCode": "EXPRESS", "amountRub": 500_000, "termMonths": 12},
                data_hash="h",
            )
            s.add(version)
            s.flush()
            application.current_version_id = version.id
            stand["application_id"] = application.id
        with db.transaction() as s:
            applications.request_information(
                s,
                stand["application_id"],
                expected_version=5,
                actor=Actor.UNDERWRITER,
                items=[TaskSpec("EXPLANATION", "Пояснение по поставке", "Нужно для оценки")],
            )
        yield stand


async def test_answer_and_submit_flow(stand: dict[str, Any]) -> None:
    app_id = stand["application_id"]
    async with client_for(stand, "a:d") as client, client_for(stand, "b:d") as stranger:
        assert (await stranger.get(f"/applications/{app_id}/tasks")).status_code == 404
        listing = (await client.get(f"/applications/{app_id}/tasks")).json()
        assert (listing["currentRound"], listing["roundsLimit"], listing["canSubmit"]) == (
            1,
            3,
            False,
        )
        task = listing["items"][0]
        assert task["canAnswer"] is True
        foreign = await stranger.post(f"/tasks/{task['id']}/answer", json={"text": "x"})
        assert foreign.status_code == 404

        early = await client.post(f"/applications/{app_id}/tasks/submit")
        assert (early.status_code, early.json()["code"]) == (409, "ROUND_INCOMPLETE")

        saved = await client.post(f"/tasks/{task['id']}/answer", json={"text": "Договор №1"})
        assert saved.status_code == 200
        assert (saved.json()["draftAnswer"], saved.json()["answer"]) == ("Договор №1", None)

        done = await client.post(f"/applications/{app_id}/tasks/submit")
        assert done.status_code == 200
        assert done.json()["items"][0]["answer"] == "Договор №1"
        assert (await client.get(f"/applications/{app_id}")).json()["status"] == "CHECKING"
        again = await client.post(f"/applications/{app_id}/tasks/submit")
        assert (again.status_code, again.json()["code"]) == (409, "ROUND_ALREADY_SENT")
    assert [n for n, _ in stand["sent"]] == ["pipeline.run"]
