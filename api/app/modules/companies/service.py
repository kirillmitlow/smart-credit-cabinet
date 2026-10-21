"""Компании для входа и доступа: кто работает от компании, членства пользователя (R11)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth
from app.modules.companies.models import Company, CompanyMember

_INN10_W = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_W1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_W2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check(digits: str, weights: tuple[int, ...]) -> str:
    return str(sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11 % 10)


def inn_is_valid(inn: str) -> bool:
    if not inn.isdigit():
        return False
    if len(inn) == 10:
        return inn[9] == _check(inn[:9], _INN10_W)
    if len(inn) == 12:
        return inn[10] == _check(inn[:10], _INN12_W1) and inn[11] == _check(inn[:11], _INN12_W2)
    return False


def by_inn(session: Session, inn: str) -> Company | None:
    return session.scalar(select(Company).where(Company.inn == inn))


def by_id(session: Session, company_id: UUID) -> Company | None:
    return session.get(Company, company_id)


def members(session: Session, company_id: UUID) -> list[tuple[CompanyMember, auth.User]]:
    rows = session.execute(
        select(CompanyMember, auth.User)
        .join(auth.User, auth.User.id == CompanyMember.user_id)
        .where(CompanyMember.company_id == company_id, CompanyMember.status == "ACTIVE")
        .order_by(CompanyMember.role, auth.User.display_name)
    )
    return [(m, u) for m, u in rows.all()]


def memberships_of(session: Session, user_id: UUID) -> list[tuple[CompanyMember, Company]]:
    rows = session.execute(
        select(CompanyMember, Company)
        .join(Company, Company.id == CompanyMember.company_id)
        .where(CompanyMember.user_id == user_id, CompanyMember.status == "ACTIVE")
        .order_by(Company.name)
    )
    return [(m, c) for m, c in rows.all()]


def to_memberships(rows: list[tuple[CompanyMember, Company]]) -> tuple[auth.Membership, ...]:
    return tuple(
        auth.Membership(m.company_id, m.role, frozenset(m.poa_permissions)) for m, _ in rows
    )
