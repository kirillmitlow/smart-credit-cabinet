"""T-371/T-370: `POST /demo/reset` — гейт DEMO_MODE, шаги и повтор, защита от параллельного вызова.

Настоящие Postgres и Valkey; сервис сценариев заменён заглушкой (его сброс проверяют тесты моков).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
import redis
from sqlalchemy import select, text

from app.main import create_app
from app.modules import audit, auth, pipeline
from app.modules.applications import Application, ApplicationEvent, ApplicationVersion
from app.modules.companies.models import Company, CompanyMember
from app.modules.disbursement.models import Disbursement
from app.modules.integrations import scenarios
from app.modules.integrations.models import IntegrationCall
from app.modules.loans import Loan, PaymentScheduleRow
from app.modules.offers.models import Signature
from app.modules.pipeline.models import Decision, DecisionReason, PipelineRun, SourceSnapshot
from app.shared import cache, clock, db, outbox, resets, tasks
from app.shared.models import IdempotencyKey, OutboxMessage
from app.shared.settings import Settings, get_settings
from app.shared.tables import TABLE_OWNERS
from tests.fixtures.signed_contract import add_signed_contract
from tests.integration.support import grant_company_bki

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 21)
INN = "001234567887"
SCENARIO_VIEW: dict[str, Any] = {
    "code": "sokolova",
    "title": "ИП Соколова",
    "inn": INN,
    "users": [{"login": "sokolova", "role": "DIRECTOR", "personRef": "self", "inn": INN}],
    "expanded": {
        "identity": {
            "inn": INN,
            "form": "IP",
            "shortName": "ИП Соколова Анна Сергеевна",
            "status": "ACTIVE",
            "persons": [
                {"ref": "self", "refs": ["self"], "inn": INN, "fullName": "Соколова Анна Сергеевна"}
            ],
        }
    },
}
KEEP_TABLES = {"policy_versions"}


class FakeScenarios:
    """Сервис сценариев: считает вызовы сброса, может упасть или подождать."""

    def __init__(self) -> None:
        self.reset_calls: list[str] = []
        self.fail_next = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def reset_all(self, mode: str = "KEEP_CUSTOM") -> dict[str, Any]:
        self.reset_calls.append(mode)
        if self.block:
            self.entered.set()
            assert self.release.wait(10), "тест не отпустил сброс"
        if self.fail_next:
            self.fail_next = False
            raise scenarios.ScenariosUnavailableError("HTTP 502: TAX: PUT /admin/chaos")
        return {"mode": mode, "scenarios": [{"code": "sokolova"}]}


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: None)
    fake = FakeScenarios()
    monkeypatch.setattr(scenarios, "reset_all", fake.reset_all)
    monkeypatch.setattr(
        scenarios, "list_scenarios", lambda: [{"code": "sokolova", "status": "APPLIED"}]
    )
    monkeypatch.setattr(scenarios, "get_scenario", lambda code: SCENARIO_VIEW)
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url, app_today=TODAY))
    database = db.get_database()
    db.migrate(database.engine)
    clock.set_clock(clock.Clock(TODAY))
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    client.flushdb()
    with database.transaction() as s:
        policy = pipeline.register_current(s)
        resets.run_all_resets(s)
        policy_id = policy.id
    fill(policy_id)
    client.set("scc:session:CLIENT:abc", "{}")
    client.set("scc:otp:otp_1", "{}")
    client.set("lookup:registry:company:001234567887", "{}")
    client.set(cache.WORKER_HEARTBEAT_KEY, "2026-10-21T10:00:00+00:00")
    yield {"app": app, "fake": fake, "redis": client, "policy_id": policy_id}
    client.flushdb()
    clock.set_clock(clock.Clock())
    database.dispose()


def fill(policy_id: Any) -> None:
    """Заявка, решение, договор, выдача, кредит, согласие, аудит, outbox и прочие журналы."""
    with db.transaction() as s:
        company = Company(inn=INN, kind="IP", name="Старая запись", status="ACTIVE")
        s.add(company)
        user = auth.upsert_client(
            s, login_ref="t:old", display_name="Старый", person_inn=INN, scenario_code=None
        )
        s.flush()
        s.add(
            CompanyMember(company_id=company.id, user_id=user.id, role="DIRECTOR", status="ACTIVE")
        )
        application = Application(
            number="АЗ-2026-000001", company_id=company.id, created_by=user.id, status="DISBURSED",
            version=3, product_code="EXPRESS", amount_rub=500_000, term_months=12, draft={}, flags=[],
        )  # fmt: skip
        s.add(application)
        s.flush()
        s.add(
            ApplicationEvent(
                application_id=application.id, kind="NOTE", actor_type="SYSTEM", payload={}
            )
        )
        version = ApplicationVersion(
            application_id=application.id, number=1, reason="SUBMIT", data={}, data_hash="h"
        )
        s.add(version)
        s.flush()
        run = PipelineRun(
            application_id=application.id, version_id=version.id, run_key="run-1",
            trigger="SUBMIT", status="DONE", policy_version_id=policy_id,
        )  # fmt: skip
        s.add(run)
        s.flush()
        s.add(
            SourceSnapshot(
                run_id=run.id, application_id=application.id, system="REGISTRY",
                resource="company", subject_inn=INN, status="OK", payload={}, payload_hash="h",
                retrieved_at=clock.now(),
            )
        )  # fmt: skip
        decision = Decision(
            application_id=application.id, run_id=run.id, source="ENGINE", outcome="APPROVED",
            route="AUTO", required_level="L1", policy_version_id=policy_id, engine_version="t",
            inputs={}, inputs_hash="h", explain={}, snapshot_ids=[], rate_percent=24,
            payment_rub=47_000,
        )  # fmt: skip
        s.add(decision)
        s.flush()
        s.add(DecisionReason(decision_id=decision.id, position=1, code="OK", kind="INFO"))
        contract = add_signed_contract(s, application)
        s.add(
            Signature(
                contract_id=contract.id, signer_user_id=user.id, signer_role="DIRECTOR",
                proof="p", method="SIMPLE_ESIGN", attempt_id="att-1",
                consent_text_version="pep-rules-v1", content_hash="h",
            )
        )  # fmt: skip
        disbursement = Disbursement(
            application_id=application.id, company_id=company.id, application_ref="A-1",
            customer_inn=INN, contract_number=contract.number, contract_uid=contract.contract_uid,
            signed_at=clock.now(), product_code="EXPRESS", kind="LOAN", repayment_type="ANNUITY",
            amount_rub=500_000, term_months=12, rate_percent=Decimal(24), status="CONFIRMED",
            idempotency_key="k1",
        )  # fmt: skip
        s.add(disbursement)
        s.flush()
        loan = Loan(
            company_id=company.id, application_id=application.id, disbursement_id=disbursement.id,
            bank_core_loan_id="loan_1", contract_number=contract.number,
            contract_uid=contract.contract_uid, product_code="EXPRESS", kind="LOAN",
            repayment_type="ANNUITY", principal_rub=500_000, outstanding_rub=500_000,
            rate_percent=Decimal(24), term_months=12, loan_account="45506810000000000001",
            settlement_account="40802810800000001234", opened_on=TODAY,
        )  # fmt: skip
        s.add(loan)
        s.flush()
        s.add(
            PaymentScheduleRow(
                loan_id=loan.id, seq=1, due_date=TODAY, principal_rub=1, interest_rub=1, total_rub=2
            )
        )
        s.add(
            OutboxMessage(
                aggregate_id="a1", event_type="E", target_system="BKI", payload={},
                idempotency_key="outbox-1",
            )
        )  # fmt: skip
        s.add(
            IdempotencyKey(
                scope="u:POST:/x", key="k", request_hash="h", expires_at=clock.now(),
            )
        )  # fmt: skip
        s.add(
            IntegrationCall(
                system="REGISTRY", method="GET", path="/x", duration_ms=1, attempt=1,
            )
        )  # fmt: skip
        audit.record(s, "LOGIN", actor_id=user.id)
        application_id = application.id
    grant_company_bki(str(application_id))


def counts() -> dict[str, int]:
    with db.transaction() as s:
        return {t: s.scalar(text(f"SELECT count(*) FROM {t}")) or 0 for t in TABLE_OWNERS}  # noqa: S608


async def post_reset(stand: dict[str, Any]) -> httpx.Response:
    transport = httpx.ASGITransport(app=stand["app"])
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        return await client.post("/demo/reset")


def test_fixture_filled_every_journal(stand: dict[str, Any]) -> None:
    before = counts()
    empty = sorted(t for t, n in before.items() if n == 0)
    # Подпись и снимок источников требуют длинной цепочки; остальные таблицы заполнены
    assert empty == []


async def test_reset_clears_modules_keeps_policy_and_restores_companies(
    stand: dict[str, Any],
) -> None:
    before = counts()
    response = await post_reset(stand)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "DONE"
    assert [(s["step"], s["title"]) for s in body["steps"]] == [
        ("MOCKS", "моки"),
        ("DATABASE", "база"),
        ("SESSIONS", "сессии"),
    ]
    assert stand["fake"].reset_calls == ["KEEP_CUSTOM"]
    after = counts()
    assert after["policy_versions"] == before["policy_versions"] >= 1
    assert after["audit_log"] == 1  # DEMO_RESET — первая запись нового журнала
    # Компании подтянуты из сценариев заново: без этого вход по ИНН не сработает
    assert (after["companies"], after["company_members"], after["users"]) == (1, 1, 1)
    emptied = {t for t in TABLE_OWNERS if t not in KEEP_TABLES | {"audit_log"}}
    emptied -= {"companies", "company_members", "users"}
    assert {t: after[t] for t in emptied} == dict.fromkeys(emptied, 0)
    with db.transaction() as s:
        company = s.scalars(select(Company)).one()
        assert company.name == "ИП Соколова Анна Сергеевна"  # а не «Старая запись»
        record = s.scalars(select(audit.AuditRecord)).one()
        assert record.action == "DEMO_RESET"
        assert record.actor_id is None
        triggers = s.scalar(
            text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE '%\\_immutable'")
        )
        assert (triggers or 0) >= 7  # журналы по-прежнему защищены от UPDATE/DELETE
    keys = set(stand["redis"].keys("*"))
    assert keys == {cache.WORKER_HEARTBEAT_KEY}


async def test_journals_stay_immutable_after_reset(stand: dict[str, Any]) -> None:
    assert (await post_reset(stand)).status_code == 200
    with db.transaction() as s:
        application = Application(
            number="АЗ-2026-000009", company_id=s.scalars(select(Company.id)).one(),
            created_by=s.scalars(select(auth.User.id)).one(), status="DRAFT", version=1,
            product_code="EXPRESS", amount_rub=1, term_months=1, draft={}, flags=[],
        )  # fmt: skip
        s.add(application)
        s.flush()
        s.add(
            ApplicationEvent(
                application_id=application.id, kind="NOTE", actor_type="SYSTEM", payload={}
            )
        )
    with pytest.raises(Exception, match="неизменяем"), db.transaction() as s:
        s.execute(text("DELETE FROM application_events"))


async def test_mocks_failure_names_step_keeps_data_and_retry_completes(
    stand: dict[str, Any],
) -> None:
    before = counts()
    stand["fake"].fail_next = True
    failed = await post_reset(stand)
    assert failed.status_code == 502, failed.text
    problem = failed.json()
    assert problem["code"] == "DEMO_RESET_FAILED"
    assert problem["errors"][0]["step"] == "MOCKS"
    assert problem["errors"][0]["title"] == "моки"
    assert "Сброс остановился на шаге «моки»" in problem["detail"]
    # База не тронута: мок отказал до неё. Только неотправленный outbox снят заранее (quiesce),
    # чтобы сообщение в пути не долетело в мок после очистки
    assert {**counts(), "outbox": 0} == {**before, "outbox": 0}
    assert stand["redis"].get("scc:session:CLIENT:abc") == "{}"
    done = await post_reset(stand)
    assert done.status_code == 200, done.text
    assert counts()["applications"] == 0


async def test_busy_outbox_does_not_wipe_mocks_or_database_and_can_retry(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    before = counts()
    quiet = outbox.quiesce
    monkeypatch.setattr(outbox, "quiesce", lambda: outbox.Quiesced(dropped=0, in_flight=1))
    response = await post_reset(stand)
    assert response.status_code == 502
    assert response.json()["code"] == "DEMO_RESET_FAILED"
    assert response.json()["errors"][0]["step"] == "MOCKS"
    assert stand["fake"].reset_calls == []
    assert counts() == before
    assert stand["redis"].get("scc:session:CLIENT:abc") == "{}"

    monkeypatch.setattr(outbox, "quiesce", quiet)
    retried = await post_reset(stand)
    assert retried.status_code == 200
    assert counts()["applications"] == 0


async def test_database_failure_names_step_and_retry_completes(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = resets.run_all_resets
    calls: list[int] = []

    def flaky(session: Any) -> list[str]:
        calls.append(1)
        if len(calls) == 1:
            real(session)  # часть работы сделана, затем сбой: транзакция откатится целиком
            raise RuntimeError("обрыв соединения")
        return real(session)

    monkeypatch.setattr(resets, "run_all_resets", flaky)
    failed = await post_reset(stand)
    assert failed.status_code == 502, failed.text
    assert failed.json()["errors"][0]["step"] == "DATABASE"
    assert counts()["applications"] == 1  # откат: половинчатого состояния нет
    assert stand["redis"].get("scc:session:CLIENT:abc") == "{}"
    done = await post_reset(stand)
    assert done.status_code == 200, done.text
    assert counts()["applications"] == 0
    assert stand["fake"].reset_calls == ["KEEP_CUSTOM", "KEEP_CUSTOM"]


async def test_sessions_failure_names_step_and_retry_completes(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = cache.delete_prefixes
    state = {"fail": True}

    def flaky(prefixes: list[str]) -> int:
        if state["fail"]:
            state["fail"] = False
            raise redis.ConnectionError("Valkey недоступен")
        return real(prefixes)

    monkeypatch.setattr(cache, "delete_prefixes", flaky)
    failed = await post_reset(stand)
    assert failed.status_code == 502, failed.text
    assert failed.json()["errors"][0]["step"] == "SESSIONS"
    assert counts()["applications"] == 0  # база уже очищена, сессии остались
    assert stand["redis"].get("scc:session:CLIENT:abc") == "{}"
    done = await post_reset(stand)
    assert done.status_code == 200, done.text
    assert set(stand["redis"].keys("*")) == {cache.WORKER_HEARTBEAT_KEY}


async def test_outside_demo_mode_every_demo_route_is_403(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    before = counts()
    response = await post_reset(stand)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "DEMO_MODE_DISABLED"
    assert stand["fake"].reset_calls == []
    assert counts() == before
    assert stand["redis"].get("scc:session:CLIENT:abc") == "{}"
    for method, path in (("GET", "/demo/personas"), ("PUT", "/demo/chaos/bki")):
        transport = httpx.ASGITransport(app=stand["app"])
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            other = await client.request(method, path)
        assert other.status_code in (403, 404, 405), (path, other.status_code)


async def test_parallel_call_gets_409_and_first_completes(stand: dict[str, Any]) -> None:
    fake: FakeScenarios = stand["fake"]
    fake.block = True
    first = asyncio.create_task(post_reset(stand))
    try:
        assert await asyncio.to_thread(fake.entered.wait, 10)
        second = await post_reset(stand)
        assert second.status_code == 409, second.text
        assert second.json()["code"] == "DEMO_RESET_IN_PROGRESS"
        assert fake.reset_calls == ["KEEP_CUSTOM"]  # второй прогон шагов не начинал
    finally:
        fake.release.set()
    done = await first
    assert done.status_code == 200, done.text
    third = await post_reset(stand)  # блокировка отпущена
    assert third.status_code == 200, third.text


def test_scenarios_adapter_posts_reset_with_admin_key_and_maps_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(200, json={"scenarios": []})
        return httpx.Response(
            502, json={"code": "RESET_FAILED", "detail": "Очистка моков не удалась: BKI"}
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        scenarios.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    assert scenarios.reset_all("BUILTIN_ONLY") == {"scenarios": []}
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/api/v1/scenarios/reset")
    assert request.headers["X-Admin-Key"] == get_settings().mock_admin_key
    assert request.content == b'{"mode":"BUILTIN_ONLY"}'
    with pytest.raises(scenarios.ScenariosUnavailableError, match="HTTP 502.*BKI"):
        scenarios.reset_all()
