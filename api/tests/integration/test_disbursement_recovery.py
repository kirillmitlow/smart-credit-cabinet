"""Потеря толчка после подписи не теряет выдачу и не создаёт её повторно."""

# ruff: noqa: F811 — общая фикстура стенда выдачи
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.modules import disbursement
from app.modules.applications import Application
from app.modules.companies.models import Company
from app.modules.disbursement import tasks as recovery
from app.modules.disbursement.models import Disbursement
from app.modules.loans import Loan
from app.shared import db, outbox, tasks
from app.shared.models import OutboxMessage
from app.shared.operations import ResetInProgress
from tests.integration.test_disbursement_flows import (
    account,
    disbursed,
    status_of,
    world,  # noqa: F401 — общая фикстура с настоящим подписанным договором
)

pytestmark = pytest.mark.integration


def ready_bank(world: dict[str, Any]) -> None:
    world["bank"].accounts = [account()]
    world["bank"].disburse_answers = [disbursed()]


def test_lost_dispatch_recovers_then_late_original_task_cannot_issue_twice(world: dict) -> None:
    ready_bank(world)
    application_id = world["application_id"]
    assert status_of(application_id) == "SIGNED"
    assert recovery.recover()["STARTED"] == 1
    assert status_of(application_id) == "DISBURSING"
    assert recovery.recover()["STARTED"] == 0
    assert disbursement.run(application_id) == "ALREADY"
    assert outbox.relay(budget_s=5).delivered == 2  # АБС, затем обязательство БКИ
    assert status_of(application_id) == "DISBURSED"
    assert recovery.recover()["STARTED"] == 0
    assert disbursement.run(application_id) == "ALREADY"
    assert world["bank"].disburse_calls == 1
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Loan)) == 1
        assert session.scalar(select(func.count()).select_from(Disbursement)) == 1


def test_two_recovery_workers_share_the_same_disbursement(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_bank(world)
    barrier = threading.Barrier(2)
    original = recovery.run

    def simultaneous(application_id: UUID, **kwargs: Any) -> str:
        barrier.wait(timeout=10)
        return original(application_id, **kwargs)

    monkeypatch.setattr(recovery, "run", simultaneous)
    with ThreadPoolExecutor(max_workers=2) as workers:
        a, b = [
            future.result(timeout=20)
            for future in [workers.submit(recovery.recover), workers.submit(recovery.recover)]
        ]
    assert a["STARTED"] + b["STARTED"] == 1
    assert a["ERROR"] + b["ERROR"] == 0
    assert outbox.relay(budget_s=5).delivered == 2
    assert world["bank"].disburse_calls == 1


def test_busy_application_is_skipped_without_waiting_for_transaction(world: dict) -> None:
    with db.transaction() as session:
        session.scalar(
            select(Application).where(Application.id == world["application_id"]).with_for_update()
        )
        result = recovery.recover()
        assert result["SKIPPED"] == 1
        assert result["STARTED"] == 0
    assert recovery.recover()["STARTED"] == 1


def test_broker_loss_after_commit_keeps_durable_outbox(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_bank(world)

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("test broker unavailable")

    monkeypatch.setattr(tasks, "send_now", unavailable)
    assert recovery.recover()["ERROR"] == 1
    assert status_of(world["application_id"]) == "DISBURSING"
    with db.transaction() as session:
        assert session.scalars(select(OutboxMessage.status)).all() == ["PENDING"]
    monkeypatch.setattr(tasks, "send_now", lambda *args, **kwargs: None)
    assert outbox.relay(budget_s=5).delivered == 2
    assert world["bank"].disburse_calls == 1


def test_other_states_and_empty_budget_do_not_start_a_disbursement(world: dict) -> None:
    assert recovery.recover(budget_s=0)["STARTED"] == 0
    with db.transaction() as session:
        session.get(Application, world["application_id"]).status = "OFFER_ACCEPTED"
    assert recovery.recover()["STARTED"] == 0
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_one_broken_application_does_not_stop_other_companies(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    with db.transaction() as session:
        source = session.get(Application, world["application_id"])
        company = Company(inn="7707083893", kind="LEGAL", name="Тест", status="ACTIVE")
        session.add(company)
        session.flush()
        broken = Application(
            number="АЗ-2026-000002",
            company_id=company.id,
            created_by=source.created_by,
            status="SIGNED",
            draft={},
            flags=[],
        )
        session.add(broken)
        session.flush()
        broken_id = broken.id
    original = recovery.run

    def fail_one(application_id: UUID, **kwargs: Any) -> str:
        if application_id == broken_id:
            raise RuntimeError("test defect")
        return original(application_id, **kwargs)

    monkeypatch.setattr(recovery, "run", fail_one)
    result = recovery.recover()
    assert result["STARTED"] == 1
    assert result["ERROR"] == 1
    assert status_of(world["application_id"]) == "DISBURSING"


def test_reset_fence_prevents_recovery_until_reset_finishes(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = recovery.hold_operation

    @contextmanager
    def resetting(application_id: UUID):
        raise ResetInProgress()
        yield  # pragma: no cover — необходима сигнатура контекстного менеджера

    monkeypatch.setattr(recovery, "hold_operation", resetting)
    assert recovery.recover()["SKIPPED"] == 1
    assert status_of(world["application_id"]) == "SIGNED"
    monkeypatch.setattr(recovery, "hold_operation", original)
    assert recovery.recover()["STARTED"] == 1
