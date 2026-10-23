"""Единственное место чтения чужих таблиц бэк-офисом (исключение R5, 50-04).

Только статические Core-проекции метаданных; ни импорта внутренних ORM-моделей, ни записи.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, case, func, or_, select, text, tuple_
from sqlalchemy.orm import Session

from app.shared.db import Base


def queue_rows(
    session: Session,
    *,
    status: str,
    product_code: str | None,
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> list[dict[str, Any]]:
    applications = Base.metadata.tables["applications"]
    companies = Base.metadata.tables["companies"]
    decisions = Base.metadata.tables["decisions"]
    events = Base.metadata.tables["application_events"]
    versions = Base.metadata.tables["application_versions"]
    latest_engine_id = (
        select(decisions.c.id)
        .where(decisions.c.application_id == applications.c.id, decisions.c.source == "ENGINE")
        .order_by(decisions.c.created_at.desc(), decisions.c.id.desc())
        .limit(1)
        .correlate(applications)
        .scalar_subquery()
    )
    entered_status = (
        select(func.max(events.c.at))
        .where(
            events.c.application_id == applications.c.id,
            events.c.kind == "TRANSITION",
            events.c.to_status == applications.c.status,
        )
        .correlate(applications)
        .scalar_subquery()
    )
    was_manual = (
        select(events.c.id)
        .where(
            events.c.application_id == applications.c.id,
            events.c.kind == "TRANSITION",
            events.c.to_status == "MANUAL_REVIEW",
        )
        .correlate(applications)
        .exists()
    )
    latest_manual_reason = (
        select(events.c.reason_code)
        .where(
            events.c.application_id == applications.c.id,
            events.c.kind == "TRANSITION",
            events.c.to_status == "MANUAL_REVIEW",
        )
        .order_by(events.c.id.desc())
        .limit(1)
        .correlate(applications)
        .scalar_subquery()
    )
    since = func.coalesce(entered_status, applications.c.submitted_at, applications.c.created_at)
    query = (
        select(
            applications.c.id,
            applications.c.number,
            applications.c.status,
            applications.c.version,
            applications.c.product_code,
            applications.c.amount_rub,
            applications.c.term_months,
            applications.c.flags,
            companies.c.id.label("company_id"),
            companies.c.name.label("company_name"),
            companies.c.inn,
            func.coalesce(
                companies.c.is_bank_customer,
                decisions.c.features["is_bank_customer"].as_boolean(),
            ).label("is_bank_customer"),
            decisions.c.explain,
            decisions.c.required_level,
            versions.c.reason.label("version_reason"),
            latest_manual_reason.label("manual_event_reason"),
            since.label("waiting_since"),
        )
        .select_from(
            applications.join(companies, companies.c.id == applications.c.company_id)
            .outerjoin(decisions, decisions.c.id == latest_engine_id)
            .outerjoin(versions, versions.c.id == applications.c.current_version_id)
        )
        .where(
            applications.c.status == status,
            or_(applications.c.status == "MANUAL_REVIEW", was_manual),
            # Даже при ошибочном статусе стоп-отказ автомата человеку не переопределять (D-034).
            ~and_(
                func.coalesce(decisions.c.route, "") == "AUTO",
                func.coalesce(decisions.c.outcome, "").in_(["REJECTED", "NOT_ELIGIBLE"]),
            ),
        )
        .order_by(since, applications.c.id)
        .limit(limit)
    )
    if product_code is not None:
        query = query.where(applications.c.product_code == product_code)
    if after is not None:
        query = query.where(tuple_(since, applications.c.id) > after)
    return [dict(row) for row in session.execute(query).mappings()]


def card_rows(session: Session, application_id: UUID) -> dict[str, Any] | None:
    """Одна версия данных даже при параллельном изменении статуса другим сотрудником."""
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    tables = Base.metadata.tables
    applications, companies, users = tables["applications"], tables["companies"], tables["users"]
    members, decisions, policies = (
        tables["company_members"],
        tables["decisions"],
        tables["policy_versions"],
    )
    events, snapshots = tables["application_events"], tables["source_snapshots"]
    submitted_role = (
        select(members.c.role)
        .where(
            members.c.company_id == applications.c.company_id,
            members.c.user_id == applications.c.created_by,
        )
        .correlate(applications)
        .scalar_subquery()
    )
    application = (
        session.execute(
            select(
                applications,
                companies.c.name.label("company_name"),
                companies.c.inn,
                companies.c.registered_on,
                companies.c.status.label("company_status"),
                companies.c.okved,
                companies.c.is_bank_customer,
                users.c.display_name.label("submitted_name"),
                submitted_role.label("submitted_role"),
            )
            .select_from(
                applications.join(companies, companies.c.id == applications.c.company_id).join(
                    users, users.c.id == applications.c.created_by
                )
            )
            .where(applications.c.id == application_id)
        )
        .mappings()
        .first()
    )
    if application is None:
        return None
    decision_rows = (
        session.execute(
            select(
                decisions,
                policies.c.version.label("policy_number"),
                policies.c.content_hash.label("policy_hash"),
                policies.c.content.label("policy_content"),
            )
            .select_from(decisions.join(policies, policies.c.id == decisions.c.policy_version_id))
            .where(decisions.c.application_id == application_id)
            .order_by(decisions.c.created_at.desc(), decisions.c.id.desc())
        )
        .mappings()
        .all()
    )
    source_rows = (
        session.execute(
            select(snapshots)
            .where(snapshots.c.application_id == application_id)
            .order_by(snapshots.c.retrieved_at.desc(), snapshots.c.id.desc())
        )
        .mappings()
        .all()
    )
    history = (
        session.execute(
            select(events, users.c.display_name.label("actor_name"))
            .select_from(events.outerjoin(users, users.c.id == events.c.actor_id))
            .where(events.c.application_id == application_id)
            .order_by(events.c.id)
        )
        .mappings()
        .all()
    )
    return {
        "application": dict(application),
        "decisions": [dict(x) for x in decision_rows],
        "snapshots": [dict(x) for x in source_rows],
        "history": [dict(x) for x in history],
        "client_tasks": client_task_rows(session, application_id),
    }


def client_task_rows(session: Session, application_id: UUID) -> list[dict[str, Any]]:
    """Банк не получает черновики ответов даже в промежуточной проекции (20-03)."""
    tasks = Base.metadata.tables["tasks"]
    rows = session.execute(
        select(
            tasks.c.id,
            tasks.c.round,
            tasks.c.kind,
            tasks.c.title,
            tasks.c.why_text,
            tasks.c.details,
            tasks.c.status,
            tasks.c.expires_at,
            tasks.c.assignee_user_id,
            tasks.c.assignee_person_inn,
            case((tasks.c.status == "ANSWERED", tasks.c.answer), else_=None).label("answer"),
            case((tasks.c.status == "ANSWERED", tasks.c.answered_by), else_=None).label(
                "answered_by"
            ),
            case((tasks.c.status == "ANSWERED", tasks.c.answered_at), else_=None).label(
                "answered_at"
            ),
            tasks.c.created_at,
        )
        .where(tasks.c.application_id == application_id)
        .order_by(tasks.c.round, tasks.c.created_at, tasks.c.id)
    ).mappings()
    return [dict(row) for row in rows]


def outbox_reference(session: Session, message_id: int) -> dict[str, Any] | None:
    messages, applications = Base.metadata.tables["outbox"], Base.metadata.tables["applications"]
    row = (
        session.execute(
            select(
                messages.c.id, applications.c.id.label("application_id"), applications.c.company_id
            )
            .select_from(
                messages.outerjoin(
                    applications, messages.c.aggregate_id == applications.c.id.cast(String)
                )
            )
            .where(messages.c.id == message_id)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def outbox_failed(
    session: Session, application_id: UUID | None, after_id: int, limit: int
) -> list[dict[str, Any]]:
    messages, applications = Base.metadata.tables["outbox"], Base.metadata.tables["applications"]
    query = (
        select(messages, applications.c.id.label("application_id"))
        .select_from(
            messages.outerjoin(
                applications, messages.c.aggregate_id == applications.c.id.cast(String)
            )
        )
        .where(messages.c.status == "FAILED", messages.c.id > after_id)
        .order_by(messages.c.id)
        .limit(limit)
    )
    if application_id is not None:
        query = query.where(applications.c.id == application_id)
    return [dict(row) for row in session.execute(query).mappings()]


def outbox_for_retry(session: Session, message_id: int) -> dict[str, Any] | None:
    messages = Base.metadata.tables["outbox"]
    row = (
        session.execute(select(messages).where(messages.c.id == message_id).with_for_update())
        .mappings()
        .first()
    )
    return dict(row) if row else None
