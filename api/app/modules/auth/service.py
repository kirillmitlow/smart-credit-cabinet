"""Пользователи: создание и обновление из сценариев, поиск по личному ИНН."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import User


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
