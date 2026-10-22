"""Поколение компании для ограждения фоновых задач и запросов (T-372)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.shared import db, operations
from app.shared.errors import not_found


def scope(company_id: UUID) -> operations.Scope | None:
    with db.transaction() as session:
        row = session.get(Company, company_id)
        return (
            operations.Scope(row.id, row.demo_generation, row.demo_resetting)
            if row is not None
            else None
        )


def for_scenario(code: str) -> operations.Scope | None:
    with db.transaction() as session:
        row = session.scalar(select(Company).where(Company.scenario_code == code))
        return operations.Scope(row.id, row.demo_generation, row.demo_resetting) if row else None


def begin_reset(session: Session, company_id: UUID) -> tuple[str, int]:
    row = session.get(Company, company_id)
    if row is None:
        raise not_found()
    row.demo_generation += 1
    row.demo_resetting = True
    session.flush()
    return row.inn, row.demo_generation


def finish_reset(session: Session, company_id: UUID) -> None:
    row = session.get(Company, company_id)
    if row is None:
        raise not_found()
    row.demo_resetting = False
