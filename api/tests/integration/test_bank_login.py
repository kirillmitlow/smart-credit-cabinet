"""T-213: банк L2, независимые сессии, актуальные полномочия и аудит."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.modules import audit, auth, companies
from app.shared import db
from app.shared.cache import get_redis
from app.shared.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def bank_client(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, demo_mode=True))
    db.migrate(db.get_database().engine)
    get_redis().flushdb()
    with db.transaction() as session:
        session.execute(
            delete(auth.User).where(
                auth.User.login_ref.in_(["demo-bank:underwriter", "demo-bank:admin"])
            )
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        yield client
    db.get_database().dispose()


@pytest.fixture
def bank_l1(bank_client: httpx.AsyncClient) -> auth.Principal:
    """L1 создаётся только фикстурой; пользовательский вход всегда открывает L2."""
    with db.transaction() as session:
        user = auth.User(
            login_ref=f"test-bank-l1:{uuid4()}",
            display_name="Тестовый андеррайтер L1",
            role="UNDERWRITER",
            status="ACTIVE",
            level="L1",
        )
        session.add(user)
        session.flush()
        return auth.Principal(
            user_id=user.id,
            role=user.role,
            zone=auth.Zone.BANK,
            display_name=user.display_name,
            level=user.level,
        )


async def _client_login(client: httpx.AsyncClient) -> str:
    with db.transaction() as session:
        user = auth.upsert_client(
            session,
            login_ref=f"test-client:{uuid4()}",
            display_name="Тестовый клиент",
            person_inn=None,
            scenario_code=None,
        )
        user_id = str(user.id)
        assert user.level is None
    issued = (await client.post("/auth/request-code", json={"userId": user_id})).json()
    verified = await client.post(
        "/auth/verify-code", json={"requestId": issued["requestId"], "code": issued["demoCode"]}
    )
    assert verified.status_code == 200
    return verified.cookies["sid_client"]


async def test_default_login_is_underwriter_l2_and_cookie_is_protected(
    bank_client: httpx.AsyncClient,
) -> None:
    response = await bank_client.post("/auth/bank-demo-login")
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "UNDERWRITER"
    assert body["level"] == "L2"
    assert set(body) == {"userId", "displayName", "role", "level"}
    cookie = response.headers["set-cookie"].lower()
    assert "sid_bank=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "sid_client" not in response.cookies
    assert (await bank_client.get("/auth/bank-me")).json() == body
    with db.transaction() as session:
        user = auth.get(session, UUID(body["userId"]))
        assert user is not None
        assert user.level == "L2"


async def test_admin_is_a_separate_fixed_bank_account(bank_client: httpx.AsyncClient) -> None:
    underwriter = (await bank_client.post("/auth/bank-demo-login")).json()
    admin = await bank_client.post("/auth/bank-demo-login", json={"role": "ADMIN"})
    assert admin.status_code == 200
    assert admin.json()["role"] == "ADMIN"
    assert admin.json()["level"] == "L2"
    assert admin.json()["userId"] != underwriter["userId"]
    assert (await bank_client.get("/me")).status_code == 401


@pytest.mark.parametrize(
    "body", [{"role": "CLIENT"}, {"role": "SUPERADMIN"}, {"level": "L1"}, {"userId": str(uuid4())}]
)
async def test_login_cannot_choose_a_user_or_arbitrary_permissions(
    bank_client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    response = await bank_client.post("/auth/bank-demo-login", json=body)
    assert response.status_code == 422
    assert "sid_bank" not in response.cookies


@pytest.mark.parametrize("body", [None, {"role": "CLIENT"}, {"level": "L1"}])
async def test_login_is_disabled_outside_demo_mode(
    bank_client: httpx.AsyncClient,
    postgres_url: str,
    redis_url: str,
    body: dict[str, Any] | None,
) -> None:
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, demo_mode=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        response = await client.post("/auth/bank-demo-login", json=body)
    assert response.status_code == 403
    assert response.json()["code"] == "DEMO_MODE_DISABLED"
    assert "sid_bank" not in response.cookies
    with db.transaction() as session:
        assert (
            session.scalar(select(auth.User).where(auth.User.login_ref == "demo-bank:underwriter"))
            is None
        )


async def test_two_logins_rotate_bank_sid_and_revoke_the_previous_session(
    bank_client: httpx.AsyncClient,
) -> None:
    first = await bank_client.post("/auth/bank-demo-login")
    old_sid = first.cookies["sid_bank"]
    second = await bank_client.post("/auth/bank-demo-login")
    new_sid = second.cookies["sid_bank"]
    assert first.json()["userId"] == second.json()["userId"]
    assert new_sid != old_sid
    assert auth.sessions.load(auth.Zone.BANK, old_sid) is None
    assert auth.sessions.load(auth.Zone.BANK, new_sid) is not None


async def test_bank_login_and_logout_preserve_client_session(
    bank_client: httpx.AsyncClient,
) -> None:
    client_sid = await _client_login(bank_client)
    login = await bank_client.post("/auth/bank-demo-login")
    bank_sid = login.cookies["sid_bank"]
    assert bank_client.cookies["sid_client"] == client_sid
    assert (await bank_client.get("/me")).status_code == 200
    logout = await bank_client.post("/auth/bank-logout")
    assert logout.status_code == 204
    assert logout.content == b""
    assert "sid_bank" not in bank_client.cookies
    assert auth.sessions.load(auth.Zone.BANK, bank_sid) is None
    assert (await bank_client.get("/auth/bank-me")).status_code == 401
    assert bank_client.cookies["sid_client"] == client_sid
    assert (await bank_client.get("/me")).status_code == 200
    assert (await bank_client.post("/auth/bank-logout")).status_code == 204


async def test_client_login_and_logout_preserve_bank_session(
    bank_client: httpx.AsyncClient,
) -> None:
    bank_sid = (await bank_client.post("/auth/bank-demo-login")).cookies["sid_bank"]
    await _client_login(bank_client)
    assert bank_client.cookies["sid_bank"] == bank_sid
    assert (await bank_client.post("/auth/logout")).status_code == 204
    assert bank_client.cookies["sid_bank"] == bank_sid
    assert (await bank_client.get("/auth/bank-me")).status_code == 200
    assert (await bank_client.get("/me")).status_code == 401


async def test_bank_login_and_logout_ignore_active_client_company_reset(
    bank_client: httpx.AsyncClient,
) -> None:
    client_sid = await _client_login(bank_client)
    principal = auth.sessions.load(auth.Zone.CLIENT, client_sid)
    assert principal is not None
    with db.transaction() as session:
        company = companies.Company(
            inn=str(uuid4().int)[:12],
            kind="LEGAL",
            name="Компания со сбросом",
            demo_resetting=True,
        )
        session.add(company)
        session.flush()
        company_id = company.id
    auth.sessions.update(
        replace(
            principal,
            active_company_id=company_id,
            memberships=(auth.Membership(company_id, "DIRECTOR"),),
        )
    )
    # Клиентская запись действительно блокируется ограждением сброса.
    client_write = await bank_client.put("/me/active-company", json={"companyId": str(company_id)})
    assert client_write.status_code == 409
    assert (await bank_client.post("/auth/bank-demo-login")).status_code == 200
    assert (await bank_client.post("/auth/bank-logout")).status_code == 204
    assert bank_client.cookies["sid_client"] == client_sid


async def test_client_session_cannot_access_bank_or_be_reused_as_bank_cookie(
    bank_client: httpx.AsyncClient,
) -> None:
    client_sid = await _client_login(bank_client)
    assert (await bank_client.get("/auth/bank-me")).status_code == 401
    response = await bank_client.get("/auth/bank-me", headers={"Cookie": f"sid_bank={client_sid}"})
    assert response.status_code == 401


async def test_bank_session_cannot_access_client_or_be_reused_as_client_cookie(
    bank_client: httpx.AsyncClient,
) -> None:
    bank_sid = (await bank_client.post("/auth/bank-demo-login")).cookies["sid_bank"]
    assert (await bank_client.get("/me")).status_code == 401
    response = await bank_client.get("/me", headers={"Cookie": f"sid_client={bank_sid}"})
    assert response.status_code == 401


@pytest.mark.parametrize("zone", [auth.Zone.CLIENT, auth.Zone.BANK])
async def test_zone_guard_checks_role_in_stored_principal(
    bank_client: httpx.AsyncClient, bank_l1: auth.Principal, zone: auth.Zone
) -> None:
    wrong_role = "CLIENT" if zone is auth.Zone.BANK else "UNDERWRITER"
    principal = replace(bank_l1, role=wrong_role, zone=zone)
    sid = auth.sessions.create(principal)
    path = "/auth/bank-me" if zone is auth.Zone.BANK else "/me"
    response = await bank_client.get(
        path, headers={"Cookie": f"{auth.sessions.COOKIE[zone]}={sid}"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_l1_fixture_is_visible_and_level_change_is_immediate(
    bank_client: httpx.AsyncClient, bank_l1: auth.Principal
) -> None:
    sid = auth.sessions.create(bank_l1)
    headers = {"Cookie": f"sid_bank={sid}"}
    assert (await bank_client.get("/auth/bank-me", headers=headers)).json()["level"] == "L1"
    with db.transaction() as session:
        user = auth.get(session, bank_l1.user_id)
        assert user is not None
        user.level = "L2"
    assert (await bank_client.get("/auth/bank-me", headers=headers)).json()["level"] == "L2"
    with db.transaction() as session:
        user = auth.get(session, bank_l1.user_id)
        assert user is not None
        user.level = "L1"
    assert (await bank_client.get("/auth/bank-me", headers=headers)).json()["level"] == "L1"


@pytest.mark.parametrize("change", ["suspend", "client", "delete", "role"])
async def test_bank_permissions_are_rechecked_on_next_request(
    bank_client: httpx.AsyncClient, change: str
) -> None:
    logged_in = (await bank_client.post("/auth/bank-demo-login", json={"role": "ADMIN"})).json()
    with db.transaction() as session:
        user = auth.get(session, UUID(logged_in["userId"]))
        assert user is not None
        if change == "suspend":
            user.status = "SUSPENDED"
        elif change == "client":
            user.role, user.level = "CLIENT", None
        elif change == "delete":
            session.delete(user)
        else:
            user.role, user.level = "UNDERWRITER", "L1"
    response = await bank_client.get("/auth/bank-me")
    if change == "role":
        assert response.status_code == 200
        assert response.json()["role"] == "UNDERWRITER"
        assert response.json()["level"] == "L1"
    else:
        assert response.status_code == (403 if change == "client" else 401)


@pytest.mark.parametrize("change", ["suspend", "lower-level", "client"])
async def test_demo_login_does_not_restore_revoked_permissions(
    bank_client: httpx.AsyncClient, change: str
) -> None:
    user_id = UUID((await bank_client.post("/auth/bank-demo-login")).json()["userId"])
    with db.transaction() as session:
        user = auth.get(session, user_id)
        assert user is not None
        if change == "suspend":
            user.status = "SUSPENDED"
        elif change == "lower-level":
            user.level = "L1"
        else:
            user.role, user.level = "CLIENT", None
    assert (await bank_client.post("/auth/bank-demo-login")).status_code == 403


async def test_login_and_logout_are_audited_without_session_secrets(
    bank_client: httpx.AsyncClient,
) -> None:
    login = await bank_client.post("/auth/bank-demo-login", headers={"X-Request-Id": "bank-login"})
    user_id = UUID(login.json()["userId"])
    sid = login.cookies["sid_bank"]
    assert (
        await bank_client.post("/auth/bank-logout", headers={"X-Request-Id": "bank-logout"})
    ).status_code == 204
    with db.transaction() as session:
        records = session.scalars(
            select(audit.AuditRecord)
            .where(audit.AuditRecord.actor_id == user_id)
            .order_by(audit.AuditRecord.id)
        ).all()
        assert [r.action for r in records] == ["LOGIN", "LOGOUT"]
        assert [r.request_id for r in records] == ["bank-login", "bank-logout"]
        assert all(r.actor_role == "UNDERWRITER" and r.details["zone"] == "bank" for r in records)
        assert all(sid not in str(r.details) for r in records)


@pytest.mark.parametrize(
    ("role", "level"),
    [("CLIENT", "L1"), ("UNDERWRITER", None), ("UNDERWRITER", "L0"), ("ADMIN", "L3")],
)
def test_database_rejects_invalid_bank_levels(
    bank_client: httpx.AsyncClient, role: str, level: str | None
) -> None:
    user = auth.User(
        login_ref=f"test-invalid-level:{uuid4()}",
        display_name="Неверный уровень",
        role=role,
        level=level,
        status="ACTIVE",
    )

    def insert() -> None:
        with db.transaction() as session:
            session.add(user)
            session.flush()

    with pytest.raises(IntegrityError, match="ck_users_bank_level"):
        insert()


def test_level_migration_up_down_up_preserves_existing_users(
    bank_client: httpx.AsyncClient, postgres_url: str
) -> None:
    cfg = db.alembic_config(postgres_url)
    command.downgrade(cfg, "0009_persona_reset_generation")
    engine = db.get_database().engine
    assert "level" not in {column["name"] for column in inspect(engine).get_columns("users")}
    bank_id, client_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, display_name, role, status, login_ref, created_at, updated_at) "
                "VALUES (:id, 'До миграции', :role, 'ACTIVE', :login_ref, :at, :at)"
            ),
            [
                {
                    "id": bank_id,
                    "role": "UNDERWRITER",
                    "login_ref": str(bank_id),
                    "at": "2026-10-23",
                },
                {
                    "id": client_id,
                    "role": "CLIENT",
                    "login_ref": str(client_id),
                    "at": "2026-10-23",
                },
            ],
        )
    command.upgrade(cfg, "head")
    with db.transaction() as session:
        bank = session.get(auth.User, bank_id)
        client = session.get(auth.User, client_id)
        assert bank is not None
        assert bank.level == "L2"
        assert client is not None
        assert client.level is None
    command.downgrade(cfg, "0009_persona_reset_generation")
    command.upgrade(cfg, "head")
    assert db.schema_is_current(engine)
    with db.transaction() as session:
        bank = session.get(auth.User, bank_id)
        client = session.get(auth.User, client_id)
        assert bank is not None
        assert bank.level == "L2"
        assert client is not None
        assert client.level is None
