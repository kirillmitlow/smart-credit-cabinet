"""T-370: служебный вход интеграционных тестов. Пользовательский UI/e2e входят по ИНН+коду."""

from contextlib import suppress
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field
from sqlalchemy.orm import Session

from app.modules import audit, auth, companies
from app.modules.demo.catalog import Camel
from app.shared import db, operations
from app.shared.errors import AppError, not_found


class LoginInput(Camel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")


class LoginResult(Camel):
    user_id: UUID
    company_id: UUID
    display_name: str
    role: Literal["CLIENT"] = "CLIENT"
    membership_role: Literal["DIRECTOR", "ACCOUNTANT", "GUARANTOR"]


@dataclass(frozen=True)
class LoggedIn:
    sid: str
    result: LoginResult


def _principal(
    session: Session, company_id: UUID, code: str, login: str
) -> tuple[auth.Principal, str]:
    # Только публичные порты владельцев. Не пересинхронизируем роли: это вернуло бы отозванное членство.
    for person in companies.people(session, company_id):
        user = auth.get(session, person.user_id)
        if user is None or user.login_ref != f"{code}:{login}" or user.scenario_code != code:
            continue
        if user.status != "ACTIVE" or user.role != "CLIENT":
            raise AppError(403, "FORBIDDEN")
        memberships = tuple(
            auth.Membership(m.company_id, m.role, frozenset(m.poa_permissions))
            for m, _ in companies.memberships_of(session, user.id)
        )
        return auth.Principal(
            user_id=user.id,
            role="CLIENT",
            zone=auth.Zone.CLIENT,
            display_name=user.display_name,
            person_inn=user.person_inn,
            memberships=memberships,
            active_company_id=company_id,
        ), person.role
    raise not_found("Учётная запись персоны")


def _login(company_id: UUID, code: str, login: str, old_sid: str | None) -> LoggedIn:
    sid = None
    try:
        with db.transaction() as session:
            principal, member_role = _principal(session, company_id, code, login)
            result = LoginResult(
                user_id=principal.user_id,
                company_id=company_id,
                display_name=principal.display_name,
                membership_role=member_role,
            )
            audit.record(
                session,
                "LOGIN",
                actor_id=principal.user_id,
                actor_role="CLIENT",
                company_id=company_id,
                details={"zone": "client", "demoHelper": True},
            )
            session.flush()
            # Старую сессию удаляем только после успешной записи новой и аудита.
            sid = auth.sessions.create(principal)
        if old_sid:
            auth.sessions.destroy(auth.Zone.CLIENT, old_sid)
        return LoggedIn(sid, result)
    except BaseException:
        if sid:
            with suppress(AppError):
                auth.sessions.destroy(auth.Zone.CLIENT, sid)
        raise


def login(code: str, account: str, old_sid: str | None) -> LoggedIn:
    with operations.hold(lambda: companies.for_scenario(code)) as scope:
        try:
            if scope is None:
                raise not_found("Персона")
            return _login(scope.company_id, code, account, old_sid)
        except AppError as exc:
            with db.transaction() as session:
                audit.record(
                    session,
                    "LOGIN_FAILED",
                    company_id=scope.company_id if scope else None,
                    details={"code": exc.code, "zone": "client", "demoHelper": True},
                )
            raise
