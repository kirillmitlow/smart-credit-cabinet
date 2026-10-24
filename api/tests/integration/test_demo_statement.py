"""T-373 / TS-007: generation shares the real upload, parser, confirmation and reset fences.

The independent 1C writer is a test fixture, not a substitute for the missing T-130 mock.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from app import document_tasks
from app.modules import applications, audit, companies, integrations
from app.modules.applications.models import Task
from app.modules.documents.models import Document, DocumentBlob
from app.shared import db, operations
from tests.integration import test_documents, test_statement_source
from tests.integration.support import client_for

pytestmark = pytest.mark.integration
stand = test_documents.stand


@pytest.fixture
def generator(stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    with db.transaction() as session:
        companies.by_id(session, stand["companies"]["a"]).scenario_code = "garipov"
    calls: list[str] = []

    def generate(code: str, *, max_bytes: int) -> bytes:
        calls.append(code)
        assert max_bytes <= 5 * 1024 * 1024
        return test_statement_source.statement()

    monkeypatch.setattr(integrations.scenarios, "bank_statement", generate)
    return calls


async def generate(
    stand: dict[str, Any], *, who: str = "a:d", key: str = "demo-file", **changes: Any
) -> Any:
    body = {
        "applicationId": str(stand["a_app"]),
        "taskId": str(stand["a_task"]),
        **changes,
    }
    async with client_for(stand, who) as client:
        return await client.post(
            "/demo/bank-statement", json=body, headers={"Idempotency-Key": key}
        )


async def test_original_is_saved_once_and_not_confirmed_by_its_demo_origin(stand, generator):
    first = await generate(stand)
    assert first.status_code == 201, first.text
    item = first.json()
    assert (item["origin"], item["parseStatus"], item["confirmedAt"]) == (
        "DEMO_GENERATED",
        "PENDING",
        None,
    )
    assert item["taskId"] == str(stand["a_task"])
    again = await generate(stand)
    assert again.json() == item
    assert again.headers["Idempotent-Replayed"] == "true"
    assert generator == ["garipov"]
    assert document_tasks.run_statement(UUID(item["id"])) == "PARSED"
    assert test_statement_source.source(stand) is None
    async with client_for(stand, "a:d") as client:
        parsed = (await client.get(f"/documents/{item['id']}")).json()
        assert (await client.get(f"/documents/{item['id']}/download")).content == (
            test_statement_source.statement()
        )
    assert (await test_statement_source.confirm(stand, parsed)).status_code == 200
    source = test_statement_source.source(stand)
    assert source["documents"][0]["origin"] == "DEMO_GENERATED"
    with db.transaction() as session:
        assert session.scalar(select(func.count(Document.id))) == 1
        assert session.scalar(select(func.count(DocumentBlob.id))) == 1
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM audit_log WHERE action='FILE_UPLOADED' AND object_id=:id"
                ),
                {"id": item["id"]},
            )
            == 1
        )
    assert [name for name, _ in stand["sent"]].count("documents.parse_statement") == 1


@pytest.mark.parametrize("who", ["b:d", "a:g"])
async def test_foreign_and_guarantor_do_not_call_generator(stand, generator, who):
    assert (await generate(stand, who=who)).status_code == 404
    assert generator == []


@pytest.mark.parametrize("failure", ["closed", "wrong-task", "draft", "no-scenario", "revoked"])
async def test_authorization_precedes_external_request(stand, generator, failure):
    with db.transaction() as session:
        if failure == "closed":
            session.get(Task, stand["a_task"]).status = "CANCELLED"
        elif failure == "wrong-task":
            session.get(Task, stand["a_task"]).kind = "EXPLANATION"
        elif failure == "draft":
            session.get(applications.Application, stand["a_app"]).status = "DRAFT"
        elif failure == "no-scenario":
            companies.by_id(session, stand["companies"]["a"]).scenario_code = None
        else:
            session.execute(
                text("UPDATE company_members SET status='SUSPENDED' WHERE company_id=:id"),
                {"id": stand["companies"]["a"]},
            )
    assert (await generate(stand)).status_code in {403, 404, 409, 422}
    assert generator == []


async def test_mode_disabled_does_not_call_generator(stand, generator):
    app = stand["app"]
    app.state.settings = app.state.settings.model_copy(update={"demo_mode": False})
    response = await generate(stand)
    assert (response.status_code, response.json()["code"]) == (403, "DEMO_MODE_DISABLED")
    assert generator == []


async def test_client_cannot_choose_another_scenario_or_origin(stand, generator):
    response = await generate(stand, code="b", inn="001234567887", origin="UPLOADED")
    assert response.status_code == 422
    assert generator == []


async def test_outage_rolls_back_and_same_key_can_retry(stand, generator, monkeypatch):
    working = integrations.scenarios.bank_statement

    def unavailable(*args, **kwargs):
        raise integrations.scenarios.ScenariosUnavailableError("private-upstream-body")

    monkeypatch.setattr(integrations.scenarios, "bank_statement", unavailable)
    response = await generate(stand)
    assert (response.status_code, response.json()["code"]) == (503, "DEMO_STATEMENT_UNAVAILABLE")
    assert "private-upstream-body" not in response.text
    with db.transaction() as session:
        assert session.scalar(select(func.count(Document.id))) == 0
    monkeypatch.setattr(integrations.scenarios, "bank_statement", working)
    assert (await generate(stand)).status_code == 201


async def test_audit_rollback_has_no_original_or_queued_job(stand, generator, monkeypatch):
    original = audit.record

    def fail(*args, **kwargs):
        raise RuntimeError("private-file-content")

    monkeypatch.setattr(audit, "record", fail)
    response = await generate(stand)
    assert response.status_code == 500
    assert "private-file-content" not in response.text
    with db.transaction() as session:
        assert session.scalar(select(func.count(Document.id))) == 0
        assert session.scalar(select(func.count(DocumentBlob.id))) == 0
    assert not stand["sent"]
    monkeypatch.setattr(audit, "record", original)
    assert (await generate(stand)).status_code == 201


async def test_reset_fence_prevents_late_file_generation(stand, generator):
    with operations.hold(
        lambda: companies.operation_scope(stand["companies"]["a"]), exclusive=True
    ):
        response = await generate(stand)
    assert (response.status_code, response.json()["code"]) == (409, "DEMO_RESET_IN_PROGRESS")
    assert generator == []


async def test_replacement_preserves_old_original_and_bad_content_does_not_cancel(
    stand, generator, monkeypatch
):
    first = (await generate(stand)).json()
    working = integrations.scenarios.bank_statement
    monkeypatch.setattr(integrations.scenarios, "bank_statement", lambda *a, **kw: b"bad-file")
    assert (await generate(stand, key="replace", replacesId=first["id"])).status_code == 422
    with db.transaction() as session:
        assert session.get(Document, UUID(first["id"])).cancelled_at is None
    monkeypatch.setattr(integrations.scenarios, "bank_statement", working)
    second = await generate(stand, key="replace", replacesId=first["id"])
    assert second.status_code == 201
    with db.transaction() as session:
        assert session.get(Document, UUID(first["id"])).cancelled_at is not None
        assert session.scalar(select(func.count(DocumentBlob.id))) == 2
