"""Общие помощники интеграционных тестов: компании с людьми, вошедшие клиенты, выдача согласий."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.main import create_app
from app.modules import auth
from app.modules.companies.models import Company, CompanyMember
from app.shared import db, tasks
from app.shared.settings import Settings

TODAY = date(2026, 10, 21)


@dataclass
class Member:
    login: str
    name: str
    role: str  # DIRECTOR | ACCOUNTANT | GUARANTOR
    person_inn: str | None
    permissions: tuple[str, ...] = ()
    poa_valid_until: date | None = None


@dataclass
class Firm:
    key: str
    inn: str
    name: str
    kind: str = "LEGAL"
    registered_on: date | None = date(2017, 3, 14)
    is_bank_customer: bool | None = False
    profile: dict[str, Any] | None = None
    members: list[Member] = field(default_factory=list)


@contextmanager
def make_stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch, firms: list[Firm]
) -> Iterator[dict[str, Any]]:
    """Приложение, пустая база с заданными компаниями и принципалы всех участников."""
    monkeypatch.setenv("REDIS_URL", redis_url)
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: sent.append((name, kw)))
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, app_today=TODAY))
    database = db.get_database()
    db.migrate(database.engine)
    with database.transaction() as s:
        s.execute(text("TRUNCATE applications, company_members, companies, users CASCADE"))
    principals: dict[str, auth.Principal] = {}
    companies: dict[str, UUID] = {}
    with database.transaction() as s:
        for firm in firms:
            company = Company(
                inn=firm.inn,
                kind=firm.kind,
                name=firm.name,
                status="ACTIVE",
                registered_on=firm.registered_on,
                is_bank_customer=firm.is_bank_customer,
                profile=firm.profile,
            )
            s.add(company)
            s.flush()
            companies[firm.key] = company.id
            for member in firm.members:
                user = auth.upsert_client(
                    s,
                    login_ref=f"t:{firm.key}:{member.login}",
                    display_name=member.name,
                    person_inn=member.person_inn,
                    scenario_code=None,
                )
                s.add(
                    CompanyMember(
                        company_id=company.id,
                        user_id=user.id,
                        role=member.role,
                        can_sign=member.role == "DIRECTOR",
                        poa_permissions=list(member.permissions),
                        poa_valid_until=member.poa_valid_until,
                        status="ACTIVE",
                    )
                )
                principals[f"{firm.key}:{member.login}"] = auth.Principal(
                    user_id=user.id,
                    role="CLIENT",
                    zone=auth.Zone.CLIENT,
                    display_name=member.name,
                    person_inn=member.person_inn,
                    memberships=(
                        auth.Membership(company.id, member.role, frozenset(member.permissions)),
                    ),
                    active_company_id=company.id,
                )
    yield {"app": app, "principals": principals, "companies": companies, "sent": sent}
    database.dispose()


def client_for(stand: dict[str, Any], who: str) -> httpx.AsyncClient:
    """Клиент, вошедший как `firm:login`."""
    sid = auth.sessions.create(stand["principals"][who])
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stand["app"]),
        base_url="http://api",
        cookies={"sid_client": sid},
    )


def grant_company_bki(application_id: str) -> None:
    """Для тестов заявки, которым согласия не интересны: подписанное БКИ компании напрямую в базе."""
    with db.transaction() as s:
        row = s.execute(
            text(
                "SELECT a.id, a.created_by, c.inn FROM applications a "
                "JOIN companies c ON c.id = a.company_id WHERE a.id = :i"
            ),
            {"i": application_id},
        ).one()
        exists = s.execute(
            text("SELECT 1 FROM consents WHERE application_id = :i AND kind = 'BKI'"),
            {"i": application_id},
        ).first()
        if exists:
            return
        s.execute(
            text(
                "INSERT INTO consents (id, application_id, bundle_id, subject_inn, subject_type, "
                "role, kind, purpose, text_version, text_hash, signed_at, valid_until, "
                "signer_user_id, sign_method, proof) VALUES (gen_random_uuid(), :a, "
                "gen_random_uuid(), :inn, 'COMPANY', 'COMPANY', 'BKI', 'LOAN_APPLICATION', "
                "'bki-consent-v1', repeat('0', 64), now(), now()::date + 180, :u, 'SIMPLE_ESIGN', "
                "repeat('0', 64))"
            ),
            {"a": row.id, "inn": row.inn, "u": row.created_by},
        )
