"""Учётки и участники компаний из сервиса сценариев (T-221, Q-023).

Блок users сценария → пользователи кабинета; люди из identity → ФИО и личные ИНН. Повторная
синхронизация обновляет записи и не плодит дубли (ключ — login сценария).
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth
from app.modules.companies.models import Company, CompanyMember
from app.modules.integrations import scenarios

log = structlog.get_logger("app.companies.sync")

_KIND = {"IP": "IP", "LLC": "LEGAL", "JSC": "LEGAL", "SELF_EMPLOYED": "SELF_EMPLOYED"}
SIGN_COMPANY_CONSENTS = "SIGN_COMPANY_CONSENTS"


def _person_by_ref(identity: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    for person in identity.get("persons") or []:
        if ref == person.get("ref") or ref in (person.get("refs") or []):
            return dict(person)
    return None


def apply_scenario(session: Session, view: dict[str, Any]) -> Company | None:
    """Записать компанию и её учётки из представления сценария (GET /scenarios/{code})."""
    expanded = view.get("expanded") or {}
    identity = expanded.get("identity") or {}
    inn = identity.get("inn") or view.get("inn")
    if not inn:
        return None
    company = session.scalar(select(Company).where(Company.inn == inn))
    if company is None:
        company = Company(inn=inn)
        session.add(company)
    company.kind = _KIND.get(identity.get("form", ""), "LEGAL")
    company.name = identity.get("shortName") or view.get("title") or inn
    company.status = identity.get("status")
    company.okved = identity.get("okved")
    company.scenario_code = view.get("code")
    session.flush()

    for user in view.get("users") or []:
        person = _person_by_ref(identity, user.get("personRef")) or {}
        person_inn = user.get("inn") or person.get("inn")
        name = user.get("fullName") or person.get("fullName") or user["login"]
        account = auth.upsert_client(
            session,
            login_ref=f"{view['code']}:{user['login']}",
            display_name=name,
            person_inn=person_inn,
            scenario_code=view.get("code"),
        )
        member = session.scalar(
            select(CompanyMember).where(
                CompanyMember.company_id == company.id, CompanyMember.user_id == account.id
            )
        )
        if member is None:
            member = CompanyMember(company_id=company.id, user_id=account.id)
            session.add(member)
        member.role = user.get("role", "ACCOUNTANT")
        member.can_sign = member.role == "DIRECTOR"
        member.poa_permissions = [SIGN_COMPANY_CONSENTS] if user.get("powerOfAttorney") else []
        member.status = "ACTIVE"
    session.flush()
    return company


def sync_all(session: Session) -> int:
    """Полная сверка со сценариями; возвращает число компаний. Сбой сервиса — исключение."""
    count = 0
    for item in scenarios.list_scenarios():
        if item.get("status") not in ("APPLIED", "PARTIAL"):
            continue
        view = scenarios.get_scenario(item["code"])
        if apply_scenario(session, view) is not None:
            count += 1
    log.info("companies_synced", companies=count)
    return count
