"""T-255: клиентский журнал не раскрывает исходные события и старые проверки."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.applications.models import ApplicationEvent
from app.modules.applications.states import Status
from app.modules.applications.timeline import project_timeline

pytestmark = pytest.mark.unit
APPLICATION = uuid4()
AT = datetime(2026, 10, 21, 10, tzinfo=UTC)


def event(number: int, **fields: object) -> ApplicationEvent:
    return ApplicationEvent(
        id=number,
        application_id=APPLICATION,
        at=AT,
        kind="TRANSITION" if "to_status" in fields else "STEP",
        actor_type="SYSTEM",
        payload={},
        **fields,
    )


@pytest.mark.parametrize("status", list(Status))
def test_all_statuses_have_steps_or_a_closed_state(status: Status) -> None:
    result = project_timeline(APPLICATION, status, 3, AT, [])
    assert result.version == 3
    assert result.last_event_id == 0
    if status == Status.DRAFT:
        assert not result.steps
        assert result.note_key is None
    elif status in (Status.WITHDRAWN, Status.EXPIRED):
        assert not result.steps
        assert result.note_key is not None
    else:
        assert len(result.steps) == (
            7 if status == Status.NEEDS_INFO else 4 if status == Status.REJECTED else 6
        )
        assert any(s.state != "waiting" for s in result.steps)
    if status == Status.SIGNED:
        assert result.steps[4].state == "done"
        assert result.steps[5].state == "waiting"


def test_projection_uses_completed_checks_and_does_not_expose_internal_fields() -> None:
    sources = event(2, step_code="SOURCES")
    sources.payload = {
        "unavailable": ["tax:financials"],
        "dscr": "secret-number",
        "inn": "secret-inn",
        "reason": "SECRET_SCORING_REASON",
        "runId": "secret-run",
    }
    rows = [event(1, to_status="CHECKING"), sources, event(3, step_code="BUREAU")]
    result = project_timeline(APPLICATION, Status.MANUAL_REVIEW, 5, AT, rows)
    assert [(c.key, c.state) for c in result.checks] == [
        ("registry", "done"),
        ("taxes", "delayed"),
        ("creditHistory", "done"),
        ("turnover", "done"),
    ]
    assert result.note_key == "sourceDelayed"
    assert result.last_event_id == 3
    dumped = result.model_dump_json(by_alias=True)
    for hidden in (
        "payload",
        "reasonCode",
        "secret-",
        "SECRET_SCORING_REASON",
        "tax:financials",
        "actor",
    ):
        assert hidden not in dumped


def test_recheck_removes_previous_checks_delays_and_decision() -> None:
    old = event(2, step_code="SOURCES")
    old.payload = {"unavailable": ["registry:company"]}
    rows = [
        event(1, to_status="CHECKING"),
        old,
        event(3, step_code="BUREAU"),
        event(4, to_status="CHECKING"),
    ]
    result = project_timeline(APPLICATION, Status.CHECKING, 7, AT, rows)
    assert result.note_key is None
    assert [c.state for c in result.checks] == ["running", "running", "waiting", "running"]
    assert all(c.at is None for c in result.checks)
    rows.append(event(5, step_code="SOURCES"))
    result = project_timeline(APPLICATION, Status.CHECKING, 7, AT, rows)
    assert [c.state for c in result.checks] == ["done", "done", "running", "done"]


def test_no_consent_is_not_a_completed_credit_history_check() -> None:
    bureau = event(1, step_code="BUREAU")
    bureau.payload = {"noConsent": 1}
    result = project_timeline(APPLICATION, Status.NEEDS_INFO, 4, AT, [bureau])
    assert next(c.state for c in result.checks if c.key == "creditHistory") == "waiting"


def test_counter_offer_remains_in_history_after_signing_without_guessing_paid_amount() -> None:
    result = project_timeline(
        APPLICATION,
        Status.DISBURSED,
        10,
        AT,
        [
            event(1, to_status="COUNTER_OFFER"),
            event(2, to_status="OFFER_ACCEPTED"),
            event(3, to_status="SIGNED"),
            event(4, to_status="DISBURSED"),
        ],
    )
    decision = next(s for s in result.steps if s.key == "decision")
    assert decision.text_key == "decision.counter"
    assert next(s for s in result.steps if s.key == "signing").at == AT
    assert next(s for s in result.steps if s.key == "money").params == {"date": AT.isoformat()}
