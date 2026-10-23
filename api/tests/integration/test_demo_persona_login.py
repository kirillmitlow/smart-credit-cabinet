"""Служебный вход: настоящие сессии/БД, явная учётка, отзыв прав, откат аудита и независимый банк."""

import copy
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import event, select

from app.main import create_app
from app.modules import audit, auth, companies
from app.modules.companies import CompanyMember
from app.shared import cache, db, operations, resets
from app.shared.settings import Settings

pytestmark = pytest.mark.integration
CODE = "login-persona"
VIEW = {
    "code": CODE,
    "title": "Тестовая компания",
    "inn": "0012345673",
    "expanded": {
        "identity": {
            "form": "LLC",
            "inn": "0012345673",
            "status": "ACTIVE",
            "shortName": "Тестовая компания",
            "persons": [
                {"ref": "director", "inn": "001234567887", "fullName": "Тестовый директор"},
                {"ref": "owner", "inn": "001310000115", "fullName": "Тестовый поручитель"},
            ],
        }
    },
    "users": [
        {"login": "director", "role": "DIRECTOR", "personRef": "director"},
        {
            "login": "accountant",
            "role": "ACCOUNTANT",
            "fullName": "Тестовый бухгалтер",
            "inn": "001310000299",
            "powerOfAttorney": True,
        },
        {"login": "guarantor", "role": "GUARANTOR", "personRef": "owner"},
    ],
}


@pytest.fixture
async def stand(postgres_url, redis_url, monkeypatch) -> AsyncIterator[tuple]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, demo_mode=True))
    db.migrate(db.get_database().engine)
    cache.get_redis().flushdb()
    with db.transaction() as s:
        resets.run_all_resets(s)
        company = companies.apply_scenario(s, VIEW)
        company_id = company.id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        yield app, c, company_id
    cache.get_redis().flushdb()
    db.get_database().dispose()


async def login(client, account="director", code=CODE, **extra):
    return await client.post(f"/demo/personas/{code}/login", json={"login": account, **extra})


def helper_audit(action="LOGIN"):
    with db.transaction() as s:
        return [
            r
            for r in s.scalars(select(audit.AuditRecord).where(audit.AuditRecord.action == action))
            if r.details.get("demoHelper")
        ]


@pytest.mark.anyio
async def test_explicit_account_cookie_rotation_and_independent_bank(stand):
    _, client, company_id = stand
    bank = await client.post("/auth/bank-demo-login", json={"role": "UNDERWRITER"})
    assert bank.status_code == 200
    bank_sid = client.cookies["sid_bank"]
    first = await login(client)
    assert first.status_code == 200
    assert first.json()["companyId"] == str(company_id)
    assert first.json()["role"] == "CLIENT"
    assert first.json()["membershipRole"] == "DIRECTOR"
    cookies = first.headers.get_list("set-cookie")
    assert len(cookies) == 1
    assert "sid_client=" in cookies[0]
    assert "HttpOnly" in cookies[0]
    assert "SameSite=lax" in cookies[0]
    assert "sid_bank" not in cookies[0]
    assert "sid" not in first.json()
    old = client.cookies["sid_client"]
    second = await login(client, "accountant")
    assert second.status_code == 200
    assert second.json()["membershipRole"] == "ACCOUNTANT"
    assert client.cookies["sid_client"] != old
    assert auth.sessions.load(auth.Zone.CLIENT, old) is None
    assert client.cookies["sid_bank"] == bank_sid
    assert (await client.get("/auth/bank-me")).json()["userId"] == bank.json()["userId"]
    me = (await client.get("/me")).json()
    assert me["activeCompanyId"] == str(company_id)
    assert me["companies"][0]["role"] == "ACCOUNTANT"
    principal = auth.sessions.load(auth.Zone.CLIENT, client.cookies["sid_client"])
    assert "SIGN_COMPANY_CONSENTS" in principal.membership(company_id).permissions
    assert len(helper_audit()) == 2


@pytest.mark.anyio
async def test_guarantor_can_only_get_client_membership(stand):
    _, client, company_id = stand
    r = await login(client, "guarantor")
    assert r.status_code == 200
    assert r.json()["role"] == "CLIENT"
    assert r.json()["membershipRole"] == "GUARANTOR"
    assert (await client.get("/auth/bank-me")).status_code == 401
    principal = auth.sessions.load(auth.Zone.CLIENT, client.cookies["sid_client"])
    assert principal.membership(company_id).permissions == frozenset()


@pytest.mark.anyio
async def test_no_implicit_account_or_role_injection(stand):
    _, client, _ = stand
    assert (await client.post(f"/demo/personas/{CODE}/login")).status_code == 422
    assert (await login(client, role="ADMIN")).status_code == 422
    assert (await login(client, "unknown")).status_code == 404
    assert (await login(client, code="unknown")).status_code == 404
    assert "sid_client" not in client.cookies
    assert helper_audit() == []
    assert len(helper_audit("LOGIN_FAILED")) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("revocation", ["user", "membership", "bank-role"])
async def test_revoked_rights_are_not_recreated_by_demo_login(stand, revocation):
    _, client, company_id = stand
    with db.transaction() as s:
        person = next(p for p in companies.people(s, company_id) if p.role == "DIRECTOR")
        user = auth.get(s, person.user_id)
        if revocation == "user":
            user.status = "SUSPENDED"
        elif revocation == "bank-role":
            user.role = "UNDERWRITER"
            user.level = "L2"
        else:
            member = s.scalar(
                select(CompanyMember).where(
                    CompanyMember.user_id == user.id, CompanyMember.company_id == company_id
                )
            )
            member.status = "SUSPENDED"
    r = await login(client)
    assert r.status_code == (404 if revocation == "membership" else 403)
    assert "sid_client" not in client.cookies
    assert helper_audit() == []
    assert len(helper_audit("LOGIN_FAILED")) == 1


@pytest.mark.anyio
async def test_technical_scenario_without_accounts_cannot_login(stand):
    _, client, _ = stand
    view = copy.deepcopy(VIEW)
    view.update(code="t-no-users", inn="0011112220", users=[])
    view["expanded"]["identity"]["inn"] = "0011112220"
    with db.transaction() as s:
        companies.apply_scenario(s, view)
    assert (await login(client, code="t-no-users")).status_code == 404
    assert helper_audit() == []


@pytest.mark.anyio
async def test_user_from_another_scenario_is_not_selected(stand):
    _, client, company_id = stand
    other = copy.deepcopy(VIEW)
    other["code"] = "other"
    other["inn"] = "0011112220"
    other["expanded"]["identity"]["inn"] = "0011112220"
    with db.transaction() as s:
        co = companies.apply_scenario(s, other)
        person = next(p for p in companies.people(s, co.id) if p.role == "DIRECTOR")
        # Даже ошибочно выданное членство не превращает чужую учётку в учётку указанного сценария.
        s.add(
            CompanyMember(
                company_id=company_id, user_id=person.user_id, role="DIRECTOR", status="ACTIVE"
            )
        )
        user = auth.get(s, person.user_id)
        user.login_ref = "other:only-other"
    assert (await login(client, "only-other")).status_code == 404
    assert helper_audit() == []


@pytest.mark.anyio
async def test_demo_disabled_or_persona_reset_does_not_open_session(stand):
    app, client, _ = stand
    scope = companies.for_scenario(CODE)
    with operations.hold(lambda: scope, exclusive=True):
        r = await login(client)
        assert r.status_code == 409
    app.state.settings = app.state.settings.model_copy(update={"demo_mode": False})
    assert (await login(client)).status_code == 403
    assert "sid_client" not in client.cookies
    assert helper_audit() == []


@pytest.mark.anyio
async def test_audit_commit_failure_keeps_old_session_and_removes_new(stand, monkeypatch):
    _, client, _ = stand
    assert (await login(client)).status_code == 200
    old = client.cookies["sid_client"]
    original_record = audit.record
    original_create = auth.sessions.create
    created = []

    def fail_commit(session, action, **kwargs):
        original_record(session, action, **kwargs)
        if action == "LOGIN":

            def broken(session):
                raise RuntimeError("commit failed")

            event.listen(session, "before_commit", broken, once=True)

    def capture(principal, **kwargs):
        sid = original_create(principal, **kwargs)
        created.append(sid)
        return sid

    monkeypatch.setattr(audit, "record", fail_commit)
    monkeypatch.setattr(auth.sessions, "create", capture)
    r = await login(client, "accountant")
    assert r.status_code == 500
    assert client.cookies["sid_client"] == old
    assert auth.sessions.load(auth.Zone.CLIENT, old) is not None
    assert len(created) == 1
    assert auth.sessions.load(auth.Zone.CLIENT, created[0]) is None
    assert len(helper_audit()) == 1


@pytest.mark.anyio
async def test_cloud_helper_needs_no_stand_code_but_has_rate_limit_and_secure_cookie(stand):
    from app.shared.settings import AppEnv

    app, client, _ = stand
    app.state.settings = app.state.settings.model_copy(
        update={
            "app_env": AppEnv.CLOUD,
            "demo_controls_per_minute": 1,
            "cookie_secure": True,
        }
    )
    r = await login(client)
    assert r.status_code == 200
    assert "Secure" in r.headers["set-cookie"]
    limited = await login(client)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert len(helper_audit()) == 1


@pytest.mark.anyio
async def test_session_store_failure_does_not_discard_previous_client_session(stand, monkeypatch):
    from app.shared.errors import AppError

    _, client, _ = stand
    assert (await login(client)).status_code == 200
    old = client.cookies["sid_client"]

    def unavailable(*args, **kwargs):
        raise AppError(503, "SESSION_STORE_UNAVAILABLE")

    monkeypatch.setattr(auth.sessions, "create", unavailable)
    result = await login(client, "accountant")
    assert result.status_code == 503
    assert client.cookies["sid_client"] == old
    assert auth.sessions.load(auth.Zone.CLIENT, old) is not None
    assert len(helper_audit()) == 1
    assert len(helper_audit("LOGIN_FAILED")) == 1
