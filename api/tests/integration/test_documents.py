"""T-332 / TS-007, TS-008: source preservation, permissions, retries, quota and reset."""

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.modules import applications, audit, companies, documents
from app.modules.applications import Application, ApplicationVersion, TaskSpec
from app.modules.documents.models import Document, DocumentBlob
from app.shared import db, operations
from app.shared.resets import collect_persona, reset_persona_rows, run_all_resets
from tests.integration.support import Firm, Member, client_for, make_stand
from tests.unit.test_document_validation import pdf_bytes

pytestmark = pytest.mark.integration
CONTENT = "1CClientBankExchange\r\nВерсияФормата=1.03\r\nКонецФайла\r\n".encode("cp1251")


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    firms = [
        Firm(
            "a",
            "001298765490",
            "Гарипов",
            kind="IP",
            members=[
                Member("d", "Директор", "DIRECTOR", "001298765490"),
                Member("acc", "Бухгалтер", "ACCOUNTANT", None),
                Member("g", "Поручитель", "GUARANTOR", "001234567887"),
            ],
        ),
        Firm("b", "001234567887", "Чужая", members=[Member("d", "Другой", "DIRECTOR", None)]),
    ]
    with make_stand(postgres_url, redis_url, monkeypatch, firms) as state:
        with db.transaction() as session:
            # Test helper truncates applications, which cascades metadata but not retained bytea.
            session.execute(text("TRUNCATE document_blobs CASCADE"))
            for key in ("a", "b"):
                application = Application(
                    number=f"АЗ-2026-{key}",
                    company_id=state["companies"][key],
                    created_by=state["principals"][f"{key}:d"].user_id,
                    status="NEEDS_INFO",
                    version=1,
                    product_code="EXPRESS",
                    amount_rub=1_500_000,
                    term_months=36,
                    draft={},
                    flags=[],
                )
                session.add(application)
                session.flush()
                version = ApplicationVersion(
                    application_id=application.id, number=1, reason="SUBMIT", data={}, data_hash="h"
                )
                session.add(version)
                session.flush()
                application.current_version_id = version.id
                receipt = applications.request_information(
                    session,
                    application.id,
                    expected_version=1,
                    actor=applications.Actor.SYSTEM,
                    items=[TaskSpec("DOCUMENT", "Выписка", "Подтвердите выручку")],
                )
                state[f"{key}_app"] = application.id
                state[f"{key}_task"] = receipt.task_ids[0]
        yield state


def fields(stand: dict[str, Any], key: str = "a") -> dict[str, str]:
    return {
        "applicationId": str(stand[f"{key}_app"]),
        "taskId": str(stand[f"{key}_task"]),
        "kind": "BANK_STATEMENT_1C",
    }


async def upload(
    stand: dict[str, Any],
    *,
    who: str = "a:d",
    key: str = "once",
    content: bytes = CONTENT,
    data: dict[str, str] | None = None,
) -> Any:
    async with client_for(stand, who) as client:
        return await client.post(
            "/documents",
            data=data or fields(stand),
            files={"file": ("../../данные.txt", content, "application/pdf")},
            headers={"Idempotency-Key": key},
        )


async def test_ts007_original_metadata_download_and_idempotency(stand: dict[str, Any]) -> None:
    response = await upload(stand)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["filename"] == "данные.txt"
    assert item["mime"] == "text/plain; charset=windows-1251"
    assert item["parseStatus"] == "PENDING"
    assert "storageKey" not in item
    again = await upload(stand)
    assert again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == item["id"]
    conflict = await upload(stand, content=CONTENT + b"x")
    assert (conflict.status_code, conflict.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")
    async with client_for(stand, "a:d") as client, client_for(stand, "b:d") as other:
        assert (await client.get(f"/documents/{item['id']}")).json()["sha256"] == item["sha256"]
        downloaded = await client.get(f"/documents/{item['id']}/download")
        assert downloaded.content == CONTENT
        assert downloaded.headers["X-Content-Type-Options"] == "nosniff"
        assert downloaded.headers["Content-Disposition"].startswith("attachment;")
        for suffix in ("", "/download"):
            assert (await other.get(f"/documents/{item['id']}{suffix}")).status_code == 404
    with db.transaction() as session:
        assert session.scalar(select(func.count(Document.id))) == 1
        assert session.scalar(select(func.count(DocumentBlob.id))) == 1
        actions = (
            session.execute(text("SELECT action FROM audit_log WHERE object_type='document'"))
            .scalars()
            .all()
        )
        assert actions.count("FILE_UPLOADED") == 1
        assert actions.count("FILE_DOWNLOADED") == 1


@pytest.mark.parametrize("who", ["b:d", "a:g"])
async def test_foreign_or_guarantor_cannot_upload(stand: dict[str, Any], who: str) -> None:
    result = await upload(stand, who=who)
    assert result.status_code == 404


async def test_accountant_can_upload_but_bank_cannot_use_client_endpoint(
    stand: dict[str, Any],
) -> None:
    assert (await upload(stand, who="a:acc")).status_code == 201
    async with client_for(stand, "a:d") as client:
        client.cookies.clear()
        assert (await client.post("/documents")).status_code == 401


async def test_membership_revocation_takes_effect_without_relogin(stand: dict[str, Any]) -> None:
    item = (await upload(stand)).json()
    async with client_for(stand, "a:d") as client:
        with db.transaction() as session:
            session.execute(
                text("UPDATE company_members SET status='SUSPENDED' WHERE user_id=:id"),
                {"id": stand["principals"]["a:d"].user_id},
            )
        assert (await client.get(f"/documents/{item['id']}")).status_code == 404
        assert (await client.get(f"/documents/{item['id']}/download")).status_code == 404


async def test_ts008_bad_files_and_replacement_preserve_original(stand: dict[str, Any]) -> None:
    item = (await upload(stand)).json()
    bad = await upload(stand, key="bad", content=pdf_bytes())
    assert (bad.status_code, bad.json()["code"]) == (422, "UNSUPPORTED_FORMAT")
    replaced = await upload(stand, key="replace", data={**fields(stand), "replacesId": item["id"]})
    assert replaced.status_code == 201, replaced.text
    async with client_for(stand, "a:d") as client:
        old = (await client.get(f"/documents/{item['id']}")).json()
        assert old["cancelledAt"] is not None
        assert (await client.get(f"/documents/{item['id']}/download")).content == CONTENT
    retry = await upload(stand, key="replace", data={**fields(stand), "replacesId": item["id"]})
    assert retry.json()["id"] == replaced.json()["id"]


async def test_files_quota_counts_originals_after_replacement(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPLOAD_MAX_FILES_PER_APPLICATION", "2")
    from app.shared.settings import get_settings

    get_settings.cache_clear()
    item = (await upload(stand)).json()
    assert (
        await upload(stand, key="two", data={**fields(stand), "replacesId": item["id"]})
    ).status_code == 201
    result = await upload(stand, key="three")
    assert (result.status_code, result.json()["code"]) == (422, "TOO_MANY_FILES")


async def test_company_reset_removes_only_its_bytes(stand: dict[str, Any]) -> None:
    a = (await upload(stand)).json()
    b = (await upload(stand, who="b:d", data=fields(stand, "b"))).json()
    with db.transaction() as session:
        scope = collect_persona(session, stand["companies"]["a"], "001298765490")
        assert a["id"] in scope.keys("documents")
        reset_persona_rows(session, scope)
    with db.transaction() as session:
        assert session.get(Document, UUID(a["id"])) is None
        assert session.scalar(select(func.count(DocumentBlob.id))) == 1
        assert session.get(Document, UUID(b["id"])) is not None
    with db.transaction() as session:
        run_all_resets(session)
    with db.transaction() as session:
        assert session.scalar(select(func.count(DocumentBlob.id))) == 0


async def test_db_prevents_original_mutation_and_public_store_verifies_hash(
    stand: dict[str, Any],
) -> None:
    item = (await upload(stand)).json()
    with pytest.raises(DBAPIError, match="immutable"):
        with db.transaction() as session:
            session.execute(text("UPDATE document_blobs SET content=:data"), {"data": b"tampered"})
    with pytest.raises(DBAPIError, match="immutable"):
        with db.transaction() as session:
            session.execute(text("UPDATE documents SET sha256='bad'"))
    with db.transaction() as session:
        access = documents.Access(stand["principals"]["a:d"].user_id, (stand["companies"]["a"],))
        row, content = documents.verified_content(session, access, UUID(item["id"]))
        assert row.sha256 == item["sha256"]
        assert content == CONTENT


async def test_bank_read_requires_its_own_live_session(stand: dict[str, Any]) -> None:
    item = (await upload(stand)).json()
    async with client_for(stand, "a:d") as client:
        assert (await client.get(f"/documents/{item['id']}?zone=bank")).status_code == 401
        bank = await client.post("/auth/bank-demo-login", json={"role": "UNDERWRITER"})
        assert bank.status_code == 200, bank.text
        result = await client.get(f"/documents/{item['id']}/download?zone=bank")
        assert result.status_code == 200, result.text
        assert result.content == CONTENT


async def test_concurrent_replay_creates_only_one_original(stand: dict[str, Any]) -> None:
    first, second = await asyncio.gather(upload(stand), upload(stand))
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    with db.transaction() as session:
        assert session.scalar(select(func.count(DocumentBlob.id))) == 1


async def test_failed_audit_rolls_back_file_and_replay_key(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("test transaction failure")

    monkeypatch.setattr(audit, "record", fail)
    response = await upload(stand)
    assert response.status_code == 500
    assert response.json()["code"] == "DOCUMENT_OPERATION_FAILED"
    with db.transaction() as session:
        assert session.scalar(select(func.count(Document.id))) == 0
        assert session.scalar(select(func.count(DocumentBlob.id))) == 0
        assert (
            session.scalar(
                text("SELECT count(*) FROM idempotency_keys WHERE scope LIKE :scope"),
                {"scope": f"documents:{stand['companies']['a']}:%"},
            )
            == 0
        )


async def test_upload_holds_company_scope_while_reading_file(stand: dict[str, Any]) -> None:
    reading, release = asyncio.Event(), asyncio.Event()
    form = fields(stand)
    prefix = b"".join(
        f'--abc\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        for key, value in form.items()
    )
    prefix += b'--abc\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n\r\n'

    async def chunks() -> Any:
        yield prefix + CONTENT[:10]
        reading.set()
        await release.wait()
        yield CONTENT[10:] + b"\r\n--abc--\r\n"

    async with client_for(stand, "a:d") as client:
        sending = asyncio.create_task(
            client.post(
                "/documents",
                content=chunks(),
                headers={
                    "Content-Type": "multipart/form-data; boundary=abc",
                    "Idempotency-Key": "slow",
                },
            )
        )
        await asyncio.wait_for(reading.wait(), 5)
        try:
            with pytest.raises(operations.ResetInProgress):
                with operations.hold(
                    lambda: companies.operation_scope(stand["companies"]["a"]), exclusive=True
                ):
                    pytest.fail("Reset must wait for the source upload")
        finally:
            release.set()
        result = await asyncio.wait_for(sending, 5)
        assert result.status_code == 201, result.text
