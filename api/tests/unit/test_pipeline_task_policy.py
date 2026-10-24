"""T-270, T-273, T-274: задача Celery, политика из файла, переходник к согласиям."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from celery.exceptions import Retry
from sqlalchemy.exc import OperationalError

from app.main import create_app
from app.modules import applications, pipeline
from app.modules.decisioning import PolicyError, policy_hash
from app.modules.pipeline import consents, policy_registry, tasks
from app.modules.pipeline.consents import ConsentView, valid_consent
from app.shared import clock
from app.shared.settings import Settings
from app.shared.tasks import celery_app
from tests.fixtures.core_personas import POLICY_PATH

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- задача pipeline.run


def test_task_is_registered_under_its_name_with_limits() -> None:
    assert "pipeline.run" in celery_app.tasks
    assert tasks.pipeline_run.name == "pipeline.run"
    assert (tasks.pipeline_run.soft_time_limit, tasks.pipeline_run.time_limit) == (60, 90)
    assert tasks.pipeline_run.max_retries == 3
    assert tasks.pipeline_reaper.name == "pipeline.reaper"
    assert (tasks.pipeline_reaper.soft_time_limit, tasks.pipeline_reaper.time_limit) == (60, 90)


def test_retry_pauses_are_2_10_30_seconds() -> None:
    assert [tasks.retry_pause(n) for n in range(5)] == [2, 10, 30, 30, 30]


def test_infrastructure_error_retries_with_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    pauses: list[int] = []

    def boom(_id: UUID) -> Any:
        raise OperationalError("SELECT 1", {}, Exception("соединение разорвано"))

    def fake_retry(exc: Exception | None = None, countdown: int | None = None, **_: Any) -> Retry:
        pauses.append(countdown or 0)
        return Retry()

    monkeypatch.setattr(tasks, "run_pipeline", boom)
    monkeypatch.setattr(tasks.pipeline_run, "retry", fake_retry)

    with pytest.raises(Retry):
        tasks.pipeline_run.run(str(UUID(int=1)))

    assert pauses == [2]


def test_business_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "run_pipeline", lambda _id: pipeline.RunResult.SKIPPED)
    monkeypatch.setattr(
        tasks.pipeline_run, "retry", lambda **_: pytest.fail("бизнес-исход не повторяют")
    )

    assert tasks.pipeline_run.run(str(UUID(int=1))) == "SKIPPED"


def test_programming_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_id: UUID) -> Any:
        raise ValueError("ошибка в коде")

    monkeypatch.setattr(tasks, "run_pipeline", broken)

    with pytest.raises(ValueError, match="ошибка в коде"):
        tasks.pipeline_run.run(str(UUID(int=1)))


# ---------------------------------------------------------------- политика (T-274)


@pytest.fixture
def policy_text() -> dict[str, Any]:
    data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def write_policy(tmp_path: Path, data: dict[str, Any], **dump: Any) -> Path:
    path = tmp_path / "v1.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, **dump), encoding="utf-8")
    return path


def test_same_policy_with_other_formatting_has_same_hash(
    tmp_path: Path, policy_text: dict[str, Any]
) -> None:
    original = pipeline.load_policy_file(POLICY_PATH)
    flow = pipeline.load_policy_file(write_policy(tmp_path, policy_text, sort_keys=True, indent=4))

    assert policy_hash(flow) == policy_hash(original)


def test_changed_number_changes_hash(tmp_path: Path, policy_text: dict[str, Any]) -> None:
    original = pipeline.load_policy_file(POLICY_PATH)
    policy_text["catalog"]["rate_corridor"]["value"] = "0.05"

    changed = pipeline.load_policy_file(write_policy(tmp_path, policy_text))

    assert policy_hash(changed) != policy_hash(original)


def test_number_without_source_is_rejected(tmp_path: Path, policy_text: dict[str, Any]) -> None:
    del policy_text["catalog"]["rate_corridor"]["source"]

    with pytest.raises(PolicyError):
        pipeline.load_policy_file(write_policy(tmp_path, policy_text))


def test_api_does_not_start_with_invalid_policy(
    tmp_path: Path, policy_text: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    del policy_text["catalog"]["rate_corridor"]["note"]
    monkeypatch.setenv("POLICY_FILE", str(write_policy(tmp_path, policy_text)))
    policy_registry.reset_policy_cache()
    try:
        with pytest.raises(PolicyError):
            create_app(Settings(database_url="postgresql+psycopg://x:x@127.0.0.1:1/x"))
    finally:
        policy_registry.reset_policy_cache()


def test_relative_policy_path_is_resolved_against_api_dir() -> None:
    assert policy_registry.policy_path().is_file()
    assert policy_registry.current_policy().meta.version == 1


# ---------------------------------------------------------------- согласия (T-273)


@dataclass
class FakeSigned:
    consent_id: str
    subject_inn: str
    subject_kind: str
    role: str
    signed_at: datetime
    valid_until: date
    purpose: str


@pytest.fixture(autouse=True)
def _frozen_clock() -> Iterator[None]:
    clock.set_clock(
        clock.Clock(date(2026, 10, 21), real_now=lambda: datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
    )
    yield
    clock.set_clock(clock.Clock())
    pipeline.set_consents_provider(None)


def consent(
    inn: str,
    *,
    signed_ago: timedelta = timedelta(hours=1),
    until: date = date(2027, 4, 21),
    purpose: str = "LOAN_APPLICATION",
    cid: str = "c",
) -> ConsentView:
    return ConsentView(cid, inn, "COMPANY", clock.now() - signed_ago, until, purpose)


def test_without_bki_consents_in_applications_nothing_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(applications, "bki_consents", raising=False)

    # T-260 не влит: согласий нет → БКИ не вызывается, заявка уйдёт в NEEDS_INFO
    assert consents.load_bki_consents(None, UUID(int=1)) == ()  # type: ignore[arg-type]


def test_adapter_converts_signed_consents_from_applications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signed = FakeSigned(
        "cns_1",
        "001234567887",
        "PERSON",
        "COMPANY",
        clock.now(),
        date(2027, 4, 21),
        "LOAN_APPLICATION",
    )
    monkeypatch.setattr(applications, "bki_consents", lambda _s, _a: [signed], raising=False)

    (view,) = consents.load_bki_consents(None, UUID(int=1))  # type: ignore[arg-type]

    assert (view.consent_id, view.subject_inn, view.role) == ("cns_1", "001234567887", "COMPANY")
    bki = view.to_bki()
    assert (bki.signer_inn, bki.sign_method, bki.text_version) == (
        "001234567887",
        "SIMPLE_ESIGN",
        "bki-consent-v1",
    )


def test_consent_validity_rules() -> None:
    assert consent("1").is_valid()
    assert not consent("1", until=date(2026, 10, 20)).is_valid()  # срок вышел
    assert not consent("1", purpose="MARKETING").is_valid()  # другая цель
    assert not consent("1", signed_ago=timedelta(minutes=-30)).is_valid()  # «из будущего»
    assert consent("1", signed_ago=timedelta(minutes=-3)).is_valid()  # допуск часов 5 минут


def test_newest_valid_consent_of_the_subject_is_chosen() -> None:
    old = consent("1", signed_ago=timedelta(days=30), cid="old")
    new = consent("1", signed_ago=timedelta(days=1), cid="new")
    expired = consent("1", signed_ago=timedelta(hours=1), until=date(2026, 1, 1), cid="expired")
    other = consent("2", cid="other")

    chosen = valid_consent([old, expired, other, new], "1")

    assert chosen is not None
    assert chosen.consent_id == "new"
    assert valid_consent([expired, other], "1") is None
