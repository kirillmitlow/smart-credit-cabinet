"""Клиентская проекция журнала: шесть шагов, пауза и проверки текущего запуска (T-255).

Наружу выходят только разрешённые ключи текстов, даты и параметры отображения.
Payload, акторы, причины скоринга и идентификаторы источников остаются на сервере.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth
from app.modules.applications import service
from app.modules.applications.models import Application, ApplicationEvent
from app.modules.applications.states import Status
from app.shared.errors import not_found

StepKey = Literal[
    "submitted", "checking", "needsHelp", "evaluating", "decision", "signing", "money"
]
StepState = Literal["waiting", "running", "done"]
CheckKey = Literal["registry", "taxes", "creditHistory", "turnover"]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TimelineStepOut(Camel):
    key: StepKey
    state: StepState
    text_key: str
    params: dict[str, str | int] = Field(default_factory=dict)
    at: datetime | None = None


class TimelineCheckOut(Camel):
    key: CheckKey
    state: Literal["waiting", "running", "done", "delayed"]
    text_key: str
    at: datetime | None = None


class ApplicationTimelineOut(Camel):
    application_id: UUID
    version: int
    last_event_id: int = Field(
        description="Последнее событие этой заявки; не глобальный курсор SSE"
    )
    steps: list[TimelineStepOut]
    checks: list[TimelineCheckOut]
    note_key: Literal["withdrawn", "expired", "sourceDelayed"] | None


ORDER: tuple[StepKey, ...] = ("submitted", "checking", "evaluating", "decision", "signing", "money")
# Третий элемент — завершить ленту на решении (отказ).
POSITIONS: dict[Status, tuple[StepKey, StepState, bool] | None] = {
    Status.DRAFT: None,
    Status.SUBMITTED: ("submitted", "running", False),
    Status.CHECKING: ("checking", "running", False),
    Status.NEEDS_INFO: ("needsHelp", "running", False),
    Status.MANUAL_REVIEW: ("evaluating", "running", False),
    Status.APPROVED: ("decision", "done", False),
    Status.COUNTER_OFFER: ("decision", "done", False),
    Status.REJECTED: ("decision", "done", True),
    Status.OFFER_ACCEPTED: ("signing", "running", False),
    Status.SIGNED: ("signing", "done", False),
    Status.DISBURSING: ("money", "running", False),
    Status.DISBURSED: ("money", "done", False),
    Status.WITHDRAWN: None,
    Status.EXPIRED: None,
}
CHECKS: tuple[tuple[CheckKey, str, str], ...] = (
    ("registry", "SOURCES", "registry:"),
    ("taxes", "SOURCES", "tax:"),
    ("creditHistory", "BUREAU", "credit_bureau:"),
    ("turnover", "SOURCES", "bank_core:turnover"),
)


def _current_run(events: Sequence[ApplicationEvent]) -> list[ApplicationEvent]:
    # Новый ответ клиента / перепроверка сбрасывает галочки прежнего запуска сразу,
    # ещё до получения новых источников. Старые причины и сбои также не наследуются.
    start = max(
        (
            e.id
            for e in events
            if e.to_status == Status.CHECKING or e.step_code == "RECHECK_REQUESTED"
        ),
        default=0,
    )
    return [e for e in events if e.id >= start]


def _checks(events: Sequence[ApplicationEvent], status: Status) -> list[TimelineCheckOut]:
    latest = {e.step_code: e for e in events if e.kind == "STEP"}
    out: list[TimelineCheckOut] = []
    for key, stage, prefix in CHECKS:
        event = latest.get(stage)
        state: Literal["waiting", "running", "done", "delayed"] = "waiting"
        if event is not None:
            unavailable = event.payload.get("unavailable") or []
            state = "delayed" if any(str(x).startswith(prefix) for x in unavailable) else "done"
            if stage == "BUREAU" and event.payload.get("noConsent") and state != "delayed":
                state = "waiting"
        elif status == Status.CHECKING and (stage == "SOURCES" or "SOURCES" in latest):
            state = "running"
        out.append(
            TimelineCheckOut(
                key=key, state=state, text_key=f"checks.{key}", at=event.at if event else None
            )
        )
    return out


def _step_of(status: str | None) -> StepKey | None:
    position = POSITIONS[Status(status)] if status else None
    return position[0] if position else None


def project_timeline(
    application_id: UUID,
    status: Status,
    version: int,
    submitted_at: datetime | None,
    events: Sequence[ApplicationEvent],
) -> ApplicationTimelineOut:
    current_run = _current_run(events)
    checks = _checks(current_run, status)
    note: Literal["withdrawn", "expired", "sourceDelayed"] | None = None
    if status == Status.WITHDRAWN:
        note = "withdrawn"
    elif status == Status.EXPIRED:
        note = "expired"
    elif status == Status.MANUAL_REVIEW and any(
        e.kind == "STEP" and e.payload.get("unavailable") for e in current_run
    ):
        note = "sourceDelayed"
    steps: list[TimelineStepOut] = []
    position = POSITIONS[status]
    if position is not None:
        active, active_state, hide_waiting = position
        keys = list(ORDER)
        if active == "needsHelp":
            keys.insert(2, "needsHelp")
        current = keys.index(active)
        if hide_waiting:
            keys = keys[: current + 1]
        for index, key in enumerate(keys):
            state: StepState = (
                "done" if index < current else active_state if index == current else "waiting"
            )
            entered = [e for e in events if _step_of(e.to_status) == key]
            at = entered[-1].at if entered else submitted_at if key == "submitted" else None
            text_key = f"{key}.{state}"
            if (
                key == "checking"
                and state != "waiting"
                and any(c.state == "delayed" for c in checks)
            ):
                text_key = "checking.delayed"
            params: dict[str, str | int] = {}
            if at is not None:
                params["date"] = at.isoformat()
            if key == "decision" and state == "done":
                decided = entered[-1].to_status if entered else status
                text_key = "decision." + (
                    "rejected"
                    if decided == Status.REJECTED
                    else "counter"
                    if decided == Status.COUNTER_OFFER
                    else "approved"
                )
            steps.append(
                TimelineStepOut(key=key, state=state, text_key=text_key, params=params, at=at)
            )
    return ApplicationTimelineOut(
        application_id=application_id,
        version=version,
        last_event_id=max((e.id for e in events), default=0),
        steps=steps,
        checks=checks,
        note_key=note,
    )


def client_timeline(
    session: Session, principal: auth.Principal, application_id: UUID
) -> ApplicationTimelineOut:
    principal = service.company_principal(session, principal)
    service.get_for(session, principal, application_id)
    # Один SQL-снимок: статус, версия и журнал не расходятся при завершении конвейера.
    rows = session.execute(
        select(Application.status, Application.version, Application.submitted_at, ApplicationEvent)
        .outerjoin(ApplicationEvent, ApplicationEvent.application_id == Application.id)
        .where(Application.id == application_id)
        .order_by(ApplicationEvent.id)
    ).all()
    if not rows:
        raise not_found("Заявка")
    status, version, submitted, _ = rows[0]
    return project_timeline(
        application_id, Status(status), version, submitted, [r[3] for r in rows if r[3] is not None]
    )
