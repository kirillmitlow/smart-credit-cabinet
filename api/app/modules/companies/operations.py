"""Поколение компании для ограждения фоновых задач и запросов (T-372)."""

from uuid import UUID

from app.modules.companies.models import Company
from app.shared import db, operations


def scope(company_id: UUID) -> operations.Scope | None:
    with db.transaction() as session:
        row = session.get(Company, company_id)
        return (
            operations.Scope(row.id, row.demo_generation, row.demo_resetting)
            if row is not None
            else None
        )
