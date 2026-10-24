"""T-333: original → fenced worker → one result, client error/replacement and round gate."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select, text

from app import document_tasks
from app.modules import applications, audit, companies
from app.modules.applications.models import Task
from app.modules.documents import processing
from app.modules.documents.models import Document
from app.shared import db, operations
from app.shared.resets import collect_persona, reset_persona_rows
from tests.integration import test_documents
from tests.integration.support import client_for
from tests.integration.test_documents import fields, upload

pytestmark = pytest.mark.integration
stand = test_documents.stand
FIXTURES = Path(__file__).parents[1] / "fixtures" / "statements"


def content(name: str = "manual-good.txt") -> bytes:
    return (FIXTURES / name).read_bytes().replace(b"001234567887", b"001298765490")


def result_events(document_id: UUID) -> int:
    with db.transaction() as session:
        return (
            session.scalar(
                select(func.count(applications.ApplicationEvent.id)).where(
                    applications.ApplicationEvent.step_code.in_(
                        ("STATEMENT_PARSED", "STATEMENT_PARSE_FAILED")
                    ),
                    applications.ApplicationEvent.payload["documentId"].astext == str(document_id),
                )
            )
            or 0
        )


async def test_upload_enqueues_once_and_worker_result_is_idempotent(stand: dict[str, Any]) -> None:
    response = await upload(stand, content=content())
    document_id = UUID(response.json()["id"])
    assert response.json()["parseStatus"] == "PENDING"
    await upload(stand, content=content())
    queued = [item for item in stand["sent"] if item[0] == document_tasks.PARSE_TASK]
    assert queued == [(document_tasks.PARSE_TASK, {"document_id": str(document_id)})]
    assert document_tasks.run_statement(document_id) == "PARSED"
    assert document_tasks.run_statement(document_id) == "ALREADY"
    assert result_events(document_id) == 1
    async with client_for(stand, "a:d") as client:
        result = (await client.get(f"/documents/{document_id}")).json()
        original = await client.get(f"/documents/{document_id}/download")
    assert original.content == content()
    assert result["parsed"]["period"] == {"start": "2026-01-01", "end": "2026-03-31"}
    assert result["parsed"]["provenance"]["completeMonthCount"] == 3
    assert result["parsed"]["requiresReview"] is True
    assert result["confirmedAt"] is None
    with db.transaction() as session:
        assert session.get(Task, stand["a_task"]).status == "OPEN"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("manual-foreign-inn.txt", "INN_MISMATCH"), ("manual-bad-balance.txt", "BALANCE_MISMATCH")],
)
async def test_bad_statement_stays_open_then_replacement_can_be_sent(
    stand: dict[str, Any], filename: str, expected: str
) -> None:
    bad_content = content(filename)
    item = (await upload(stand, content=bad_content)).json()
    document_id = UUID(item["id"])
    assert document_tasks.run_statement(document_id) == "FAILED"
    assert document_tasks.run_statement(document_id) == "ALREADY"
    async with client_for(stand, "a:d") as client:
        detail = (await client.get(f"/documents/{document_id}")).json()
        assert detail["parseError"] == expected
        assert detail["parsed"] is None
        assert (await client.get(f"/documents/{document_id}/download")).content == bad_content
        await client.post(f"/tasks/{stand['a_task']}/answer", json={"text": "Прикладываю выписку"})
        blocked = await client.post(f"/applications/{stand['a_app']}/tasks/submit")
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "ROUND_INCOMPLETE"
    replaced = await upload(
        stand, key="replace", content=content(), data={**fields(stand), "replacesId": item["id"]}
    )
    assert replaced.status_code == 201
    replacement_id = UUID(replaced.json()["id"])
    assert document_tasks.run_statement(document_id) == "SKIPPED"
    assert document_tasks.run_statement(replacement_id) == "PARSED"
    assert result_events(document_id) == 1
    async with client_for(stand, "a:d") as client:
        original = (await client.get(f"/documents/{document_id}")).json()
        assert original["cancelledAt"] is not None
        sent = await client.post(f"/applications/{stand['a_app']}/tasks/submit")
        assert sent.status_code == 200, sent.text


@pytest.mark.parametrize("status", ["PENDING", "PROCESSING", "FAILED"])
async def test_round_blocks_any_unready_statement_even_with_another_pdf(
    stand: dict[str, Any], status: str
) -> None:
    item = (await upload(stand, content=content())).json()
    from tests.unit.test_document_validation import pdf_bytes

    await upload(stand, key="pdf", content=pdf_bytes(), data={**fields(stand), "kind": "OTHER"})
    with db.transaction() as session:
        session.get(Document, UUID(item["id"])).parse_status = status
    async with client_for(stand, "a:d") as client:
        await client.post(f"/tasks/{stand['a_task']}/answer", json={"text": "Документы готовы"})
        response = await client.post(f"/applications/{stand['a_app']}/tasks/submit")
    assert response.status_code == 409
    with db.transaction() as session:
        assert session.get(Task, stand["a_task"]).status == "OPEN"


async def test_concurrent_workers_commit_one_result(stand: dict[str, Any]) -> None:
    document_id = UUID((await upload(stand, content=content())).json()["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(document_tasks.run_statement, [document_id, document_id]))
    assert sorted(outcomes) == ["ALREADY", "PARSED"]
    assert result_events(document_id) == 1


async def test_audit_failure_rolls_back_result_then_retry_can_finish(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = UUID((await upload(stand, content=content())).json()["id"])

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(audit, "record", fail)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            document_tasks.run_statement(document_id)
    assert result_events(document_id) == 0
    with db.transaction() as session:
        row = session.get(Document, document_id)
        assert row.parse_status == "PENDING"
        assert row.parsed is None
    assert document_tasks.run_statement(document_id) == "PARSED"
    assert result_events(document_id) == 1


@pytest.mark.parametrize("error", [RuntimeError, SoftTimeLimitExceeded])
async def test_unexpected_failure_and_timeout_are_safe_file_errors(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch, error: type[Exception], capsys: Any
) -> None:
    document_id = UUID((await upload(stand, content=content())).json()["id"])

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise error("secret payment purpose: do not log")

    monkeypatch.setattr(processing, "parse_statement", fail)
    assert document_tasks.run_statement(document_id) == "FAILED"
    with db.transaction() as session:
        row = session.get(Document, document_id)
        assert row.parsed is None
        assert row.parse_error == (
            "PARSE_TIMEOUT" if error is SoftTimeLimitExceeded else "PARSE_FAILED"
        )
    captured = capsys.readouterr()
    assert "secret payment purpose" not in captured.out + captured.err


async def test_late_job_after_withdrawal_or_reset_is_skipped(stand: dict[str, Any]) -> None:
    document_id = UUID((await upload(stand, content=content())).json()["id"])
    async with client_for(stand, "a:d") as client:
        withdrawn = await client.post(f"/applications/{stand['a_app']}/withdraw")
        assert withdrawn.status_code == 200, withdrawn.text
    assert document_tasks.run_statement(document_id) == "SKIPPED"
    assert result_events(document_id) == 0
    with db.transaction() as session:
        scope = collect_persona(session, stand["companies"]["a"], "001298765490")
        reset_persona_rows(session, scope)
    assert document_tasks.run_statement(document_id) == "SKIPPED"
    assert document_tasks.run_statement(uuid4()) == "SKIPPED"
    with db.transaction() as session:
        assert session.get(Document, document_id) is None


async def test_reset_cannot_cross_inflight_parser_and_removes_finished_result(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = UUID((await upload(stand, content=content())).json()["id"])
    original = processing.parse_statement

    def guarded(*args: Any, **kwargs: Any) -> Any:
        with pytest.raises(operations.ResetInProgress):
            with operations.hold(
                lambda: companies.operation_scope(stand["companies"]["a"]), exclusive=True
            ):
                pytest.fail("reset must not overlap the parser")
        return original(*args, **kwargs)

    monkeypatch.setattr(processing, "parse_statement", guarded)
    assert await asyncio.to_thread(document_tasks.run_statement, document_id) == "PARSED"
    with db.transaction() as session:
        scope = collect_persona(session, stand["companies"]["a"], "001298765490")
        reset_persona_rows(session, scope)
    assert document_tasks.run_statement(document_id) == "SKIPPED"


async def test_recovery_requeues_pending_but_not_closed_replaced_or_finished(
    stand: dict[str, Any],
) -> None:
    old = (await upload(stand, content=content())).json()
    replacement = (
        await upload(
            stand, key="replace", content=content(), data={**fields(stand), "replacesId": old["id"]}
        )
    ).json()
    assert document_tasks.recover_statements() == 1
    assert stand["sent"][-1] == (document_tasks.PARSE_TASK, {"document_id": replacement["id"]})
    assert document_tasks.run_statement(UUID(replacement["id"])) == "PARSED"
    assert document_tasks.recover_statements() == 0
    await upload(stand, key="pending", content=content())
    async with client_for(stand, "a:d") as client:
        await client.post(f"/applications/{stand['a_app']}/withdraw")
    assert document_tasks.recover_statements() == 0


async def test_upload_rollback_does_not_enqueue_parser(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(audit, "record", fail)
    assert (await upload(stand, content=content())).status_code == 500
    assert not [item for item in stand["sent"] if item[0] == document_tasks.PARSE_TASK]
    with db.transaction() as session:
        assert session.scalar(text("SELECT count(*) FROM documents")) == 0
