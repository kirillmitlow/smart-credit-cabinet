"""Единственное место чтения чужих таблиц бэк-офисом (исключение R5, 50-04).

Только статические Core-проекции метаданных; ни импорта внутренних ORM-моделей, ни записи.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, tuple_
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
            companies.c.is_bank_customer,
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
