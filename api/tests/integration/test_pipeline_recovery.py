# ruff: noqa: F811
"""T-271: потерянная очередь, живая/потерянная аренда, предел попыток и технический исход."""

import threading
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app.modules import auth, pipeline
from app.modules.applications import Application
from app.modules.decisioning import Level, Outcome
from app.modules.pipeline import recovery, runner, underwriter
from app.modules.pipeline.models import Decision, PipelineRun
from app.shared import clock, db, tasks
from tests.integration.test_pipeline import Case, database, sokolova, status_of  # noqa: F401 — фикстуры

pytestmark = pytest.mark.integration


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    messages: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kwargs: messages.append((name, kwargs)))
    return messages


def expire(database: db.Database, run_id: UUID) -> None:
    with database.transaction() as session:
        session.get(PipelineRun, run_id).locked_until = clock.system_now() - timedelta(seconds=1)


def only_run(database: db.Database) -> PipelineRun:
    with database.transaction() as session:
        run = session.scalars(select(PipelineRun)).one()
        session.expunge(run)
        return run


def test_lost_initial_task_is_recreated_and_runs_without_waiting_dispatch_lease(
    database: db.Database,
    sokolova: Case,
    sent: list,
) -> None:
    assert recovery.reap()["queued"] == 1
    assert sent == [("pipeline.run", {"application_id": str(sokolova.application_id)})]
    assert only_run(database).attempts == 0
    assert recovery.reap()["queued"] == 0
    assert (
        pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
        == pipeline.RunResult.DONE
    )
    assert status_of(database, sokolova.application_id) == "APPROVED"
    assert only_run(database).attempts == 1


def test_live_lease_is_untouched(database: db.Database, sokolova: Case, sent: list) -> None:
    claim = runner.claim_run(sokolova.application_id)
    assert claim is not None
    before = only_run(database)
    assert recovery.reap()["queued"] == 0
    assert sent == []
    after = only_run(database)
    assert (after.lease_token, after.locked_until, after.attempts) == (
        before.lease_token,
        before.locked_until,
        1,
    )


def test_recovery_after_bureau_checkpoint_reuses_paid_report_and_fences_old_worker(
    database: db.Database,
    sokolova: Case,
    sent: list,
) -> None:
    claim = runner.claim_run(sokolova.application_id)
    assert claim is not None
    runner.step_completeness(claim)
    runner.step_sources(claim, sokolova.integrations)
    runner.step_bureau(claim, sokolova.integrations)
    assert sokolova.world.count("credit_bureau:report") == 1
    expire(database, claim.run_id)
    assert recovery.reap()["queued"] == 1
    with pytest.raises(runner.LeaseLostError):
        runner.step_decision(claim)
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    assert status_of(database, sokolova.application_id) == "APPROVED"
    assert sokolova.world.count("credit_bureau:report") == 1
    assert only_run(database).attempts == 2
    with database.transaction() as session:
        assert len(session.scalars(select(Decision)).all()) == 1


def test_five_failed_attempts_go_to_manual_without_calling_broken_engine(
    database: db.Database,
    sokolova: Case,
    sent: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Технический исход не должен вызывать decide")

    monkeypatch.setattr(runner, "decide", broken)
    monkeypatch.setattr(underwriter, "decide", broken)
    for number in range(1, 6):
        claim = runner.claim_run(sokolova.application_id)
        assert claim is not None
        if number == 1:
            runner.step_completeness(claim)
        expire(database, claim.run_id)
        if number == 5:
            assert runner.claim_run(sokolova.application_id) is None
        result = recovery.reap()
        assert result["manual" if number == 5 else "queued"] == 1
    assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"
    assert only_run(database).status == "FAILED"
    with database.transaction() as session:
        decision = session.scalars(select(Decision)).one()
        assert decision.features is None
        assert decision.grade is None
        assert decision.score is None
        assert decision.explain["kind"] == "PIPELINE_ERROR"
        assert decision.explain["reasons"][0]["code"] == "PIPELINE_ERROR"
        application = session.get(Application, sokolova.application_id)
        employee = auth.User(
            login_ref=f"recovery-bank-{uuid4()}",
            display_name="Андеррайтер",
            role="UNDERWRITER",
            level="L2",
            status="ACTIVE",
        )
        session.add(employee)
        session.flush()
        receipt = pipeline.record_underwriter_decision(
            session,
            application_id=application.id,
            expected_version=application.version,
            actor_id=employee.id,
            actor_level=Level.L2,
            outcome=Outcome.REJECTED,
            reason_code="UW_DOCUMENT_ISSUE",
            comment="После технического сбоя сведения не подтверждены. Решение принято специалистом вручную.",
        )
        assert receipt.outcome == Outcome.REJECTED
    assert status_of(database, sokolova.application_id) == "REJECTED"
    assert recovery.reap()["manual"] == 0


def test_two_reapers_publish_one_task(database: db.Database, sokolova: Case, sent: list) -> None:
    barrier = threading.Barrier(2)
    results: list[str] = []

    def execute() -> None:
        barrier.wait()
        results.append(recovery.reap_one(sokolova.application_id))

    threads = [threading.Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert sorted(results) == ["queued", "skipped"]
    assert len(sent) == 1
    assert only_run(database).status == "QUEUED"


def test_locked_checkpoint_is_skipped_without_deadlocking_on_application(
    database: db.Database,
    sokolova: Case,
    sent: list,
) -> None:
    claim = runner.claim_run(sokolova.application_id)
    assert claim is not None
    expire(database, claim.run_id)
    with database.transaction() as session:
        session.scalar(select(PipelineRun).where(PipelineRun.id == claim.run_id).with_for_update())
        assert recovery.reap_one(sokolova.application_id) == "skipped"
    assert sent == []


def test_lost_dispatch_after_commit_is_recoverable_on_next_tick(
    database: db.Database,
    sokolova: Case,
    sent: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lost(*_args: Any, **_kwargs: Any) -> None:
        raise RedisConnectionError("Очередь недоступна")

    with monkeypatch.context() as local:
        local.setattr(tasks, "send_now", lost)
        assert recovery.reap()["errors"] == 1
    run = only_run(database)
    assert run.status == "QUEUED"
    assert run.attempts == 0
    expire(database, run.id)
    assert recovery.reap()["queued"] == 1
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    assert status_of(database, sokolova.application_id) == "APPROVED"
    assert only_run(database).id == run.id
