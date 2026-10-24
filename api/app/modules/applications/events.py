"""Small SSE projections from the existing journal. Same ACL for replay and live delivery."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, and_, cast, exists, false, or_, select
from sqlalchemy.orm import Session

from app.modules import auth
from app.modules.applications.models import Application, ApplicationEvent, Task


@dataclass(frozen=True)
class EventNotice:
    id: int
    kind: str
    data: dict[str, str]


def _visible(principal: auth.Principal) -> Any:
    if principal.zone is auth.Zone.BANK:
        return principal.role in {"UNDERWRITER", "ADMIN"} and principal.level in {"L1", "L2"}
    regular = [m.company_id for m in principal.memberships if m.role != "GUARANTOR"]
    guarantor = [m.company_id for m in principal.memberships if m.role == "GUARANTOR"]
    own_task = exists().where(
        Task.application_id == Application.id,
        cast(Task.id, String) == ApplicationEvent.payload["taskId"].astext,
        or_(
            Task.assignee_user_id == principal.user_id,
            Task.assignee_person_inn == principal.person_inn if principal.person_inn else false(),
        ),
    )
    return or_(
        Application.company_id.in_(regular),
        and_(Application.company_id.in_(guarantor), ApplicationEvent.kind == "TASK", own_task),
    )


def _query(principal: auth.Principal) -> Any:
    return select(ApplicationEvent).join(Application).where(_visible(principal))


def event_ids(session: Session, principal: auth.Principal, after: int) -> list[int]:
    """101st visible event requests resync; foreign rows never affect that decision."""
    rows = session.scalars(
        _query(principal)
        .where(ApplicationEvent.id > after)
        .order_by(ApplicationEvent.id)
        .limit(101)
    )
    return [row.id for row in rows]


def event_notice(session: Session, principal: auth.Principal, event_id: int) -> EventNotice | None:
    row = session.scalar(_query(principal).where(ApplicationEvent.id == event_id))
    if row is None:
        return None
    kind = (
        "status_changed"
        if row.kind == "TRANSITION"
        else "task_created"
        if row.step_code == "TASK_CREATED"
        else "step_done"
    )
    data = {"applicationId": str(row.application_id)}
    if row.to_status:
        data["status"] = row.to_status
    if row.step_code:
        data["clientStep"] = row.step_code
    return EventNotice(row.id, kind, data)
