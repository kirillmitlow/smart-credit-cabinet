"""Пользователи: создание и обновление из сценариев, поиск по личному ИНН."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.auth.models import User

BankRole = Literal["UNDERWRITER", "ADMIN"]


def demo_bank_user(session: Session, role: BankRole) -> User:
    """Две фиксированные демо-учётки; повторный вход не возвращает отозванные права."""
    login_ref = {"UNDERWRITER": "demo-bank:underwriter", "ADMIN": "demo-bank:admin"}[role]
    session.execute(
        insert(User)
        .values(
            login_ref=login_ref,
            display_name="Андеррайтер" if role == "UNDERWRITER" else "Администратор демо",
            role=role,
            level="L2",
            status="ACTIVE",
        )
        .on_conflict_do_nothing(index_elements=[User.login_ref])
    )
    return session.scalars(select(User).where(User.login_ref == login_ref)).one()


def upsert_client(
    session: Session,
    *,
    login_ref: str,
    display_name: str,
    person_inn: str | None,
    scenario_code: str | None,
) -> User:
    user = session.scalar(select(User).where(User.login_ref == login_ref))
    if user is None:
        user = User(login_ref=login_ref, role="CLIENT", status="ACTIVE")
        session.add(user)
    user.display_name = display_name
    user.person_inn = person_inn
    user.scenario_code = scenario_code
    session.flush()
    return user


def get(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def by_person_inn(session: Session, person_inn: str) -> list[User]:
    return list(session.scalars(select(User).where(User.person_inn == person_inn)))
