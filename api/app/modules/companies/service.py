"""Компании для входа и доступа: кто работает от компании, членства пользователя (R11)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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


SIGN_COMPANY_CONSENTS = "SIGN_COMPANY_CONSENTS"


@dataclass(frozen=True, slots=True)
class Person:
    """Человек компании для согласий: роль, личный ИНН, срок и полномочия доверенности."""

    user_id: UUID
    display_name: str
    person_inn: str | None
    role: str  # DIRECTOR | ACCOUNTANT | GUARANTOR
    poa_permissions: frozenset[str]
    poa_valid_until: date | None


def people(session: Session, company_id: UUID) -> list[Person]:
    return [
        Person(
            user_id=u.id,
            display_name=u.display_name,
            person_inn=u.person_inn,
            role=m.role,
            poa_permissions=frozenset(m.poa_permissions),
            poa_valid_until=m.poa_valid_until,
        )
        for m, u in members(session, company_id)
    ]


def can_sign_company_consents(person: Person, on: date) -> bool:
    """Руководитель — всегда; сотрудник — при действующей доверенности с полномочием (D-091)."""
    if person.role == "DIRECTOR":
        return True
    if person.role != "ACCOUNTANT" or SIGN_COMPANY_CONSENTS not in person.poa_permissions:
        return False
    return person.poa_valid_until is None or person.poa_valid_until >= on
