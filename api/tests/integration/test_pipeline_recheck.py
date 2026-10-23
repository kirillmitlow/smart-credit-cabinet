# ruff: noqa: F811
"""T-277: `pipeline.request_recheck` — новый уникальный запуск после NEEDS_INFO и MANUAL_REVIEW."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from app.modules import pipeline
from app.modules.applications import Actor, Application, ApplicationVersion
from app.modules.pipeline.models import Decision, PipelineRun
from app.shared import db, tasks
from app.shared.errors import AppError
from tests.integration.test_pipeline import (  # noqa: F401  (фикстуры)
    Case,
    consents_for,
    database,
    decision_of,
    sokolova,
    status_of,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    box: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: box.append((name, kw)))
    return box


def version_of(database: db.Database, application_id: UUID) -> int:
    with database.transaction() as s:
        application = s.get(Application, application_id)
        assert application is not None
        return application.version


def recheck(
    database: db.Database, case: Case, actor: Actor, **kwargs: Any
) -> pipeline.RecheckReceipt:
    with database.transaction() as s:
        return pipeline.request_recheck(
            s,
            case.application_id,
            expected_version=kwargs.pop(
                "expected_version", version_of(database, case.application_id)
            ),
            actor=actor,
            **kwargs,
        )


def to_manual_review(database: db.Database, case: Case) -> None:
    case.world.down.add("registry:company")
    pipeline.run_pipeline(case.application_id, integrations=case.integrations)
    assert status_of(database, case.application_id) == "MANUAL_REVIEW"
    case.world.down.discard("registry:company")


def test_recheck_after_needs_info_reaches_decision(
    database: db.Database, sokolova: Case, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    pipeline.set_consents_provider(consents_for())
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    assert status_of(database, sokolova.application_id) == "NEEDS_INFO"
    pipeline.set_consents_provider(consents_for((sokolova.inn, "COMPANY")))

    receipt = recheck(database, sokolova, Actor.CLIENT, version_reason="INFO_PROVIDED")

    assert status_of(database, sokolova.application_id) == "CHECKING"
    assert sent == [("pipeline.run", {"application_id": str(sokolova.application_id)})]
    assert receipt.version_number == 2
    result = pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    assert result == pipeline.RunResult.DONE
    assert status_of(database, sokolova.application_id) == "APPROVED"
    with database.transaction() as s:
        runs = s.scalars(select(PipelineRun).order_by(PipelineRun.created_at)).all()
        assert [r.status for r in runs] == ["DONE", "DONE"]
        assert runs[1].run_key == receipt.run_key
        assert runs[1].trigger == "INFO_PROVIDED"
        assert len(s.scalars(select(Decision)).all()) == 2
        assert len(s.scalars(select(ApplicationVersion)).all()) == 2
    assert decision_of is not None


def test_recheck_does_not_buy_bureau_report_again(
    database: db.Database, sokolova: Case, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    to_manual_review(database, sokolova)
    assert sokolova.world.count("credit_bureau:report") == 1

    recheck(database, sokolova, Actor.UNDERWRITER)
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert status_of(database, sokolova.application_id) == "APPROVED"
    assert sokolova.world.count("credit_bureau:report") == 1
    assert sokolova.world.count("registry:company") == 2  # бесплатные источники спрошены свежо
    assert len(sent) == 1


def test_version_conflict(database: db.Database, sokolova: Case) -> None:
    to_manual_review(database, sokolova)
    stale = version_of(database, sokolova.application_id) - 1

    with pytest.raises(AppError) as error:
        recheck(database, sokolova, Actor.UNDERWRITER, expected_version=stale)

    assert error.value.code == "VERSION_CONFLICT"
    assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"


def test_wrong_actor_is_invalid_transition(database: db.Database, sokolova: Case) -> None:
    to_manual_review(database, sokolova)

    with pytest.raises(AppError) as error:
        recheck(database, sokolova, Actor.CLIENT)

    assert error.value.code == "INVALID_TRANSITION"


def test_rollback_leaves_no_run_and_no_task(
    database: db.Database, sokolova: Case, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    to_manual_review(database, sokolova)
    version = version_of(database, sokolova.application_id)

    with pytest.raises(RuntimeError):  # noqa: PT012
        with database.transaction() as s:
            pipeline.request_recheck(
                s, sokolova.application_id, expected_version=version, actor=Actor.UNDERWRITER
            )
            raise RuntimeError("откат вызывающего")

    assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"
    assert version_of(database, sokolova.application_id) == version
    assert sent == []
    with database.transaction() as s:
        assert len(s.scalars(select(PipelineRun)).all()) == 1


def test_double_call_is_rejected(
    database: db.Database, sokolova: Case, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    to_manual_review(database, sokolova)
    recheck(database, sokolova, Actor.UNDERWRITER)

    with pytest.raises(AppError) as error:
        recheck(database, sokolova, Actor.UNDERWRITER)

    assert error.value.code == "RECHECK_ALREADY_RUNNING"
    assert len(sent) == 1
    with database.transaction() as s:
        assert len(s.scalars(select(PipelineRun)).all()) == 2
