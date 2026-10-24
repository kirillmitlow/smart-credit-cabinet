"""T-342…T-344: выдача «ровно один раз» на живых моках и Postgres (Sokolova, 30-17).

Заявка `SIGNED` собирается прямо в базе. Задача `disbursement.run` и ретранслятор outbox работают
по-настоящему, АБС и БКИ — живые моки. `LOST_RESPONSE` вешается заголовком `X-Mock-Scenario` на
первый `POST /disbursements`: мок выдаёт деньги и обрывает связь.
"""

# ruff: noqa: PT018
from __future__ import annotations

import random
import threading
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select, text, update

from app.modules import disbursement, pipeline
from app.modules.applications import Application
from app.modules.disbursement import delivery
from app.modules.integrations import IntegrationClient, build_integrations, set_integrations
from app.modules.loans import Loan, PaymentScheduleRow
from app.modules.pipeline.models import Decision
from app.shared import clock, db, outbox
from app.shared.models import OutboxMessage
from tests.contract.conftest import HOST, PORTS, ListJournal, make_settings
from tests.fixtures.signed_contract import add_signed_contract
from tests.integration.conftest import postgres_url, redis_url  # noqa: F401 — фикстуры Testcontainers
from tests.integration.support import TODAY, Firm, Member, client_for, make_stand

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SOKOLOVA_INN = "001234567887"
OTHER_INN = "0010000000"


class FirstPostScenario(httpx.BaseTransport):
    """`X-Mock-Scenario` только на первый `POST /disbursements`; остальные запросы идут как есть."""

    def __init__(self, scenario: str | None) -> None:
        self._inner = httpx.HTTPTransport()
        self._scenario = scenario
        self._used = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._scenario and not self._used and request.url.path.endswith("/disbursements"):
            self._used = True
            request.headers["X-Mock-Scenario"] = self._scenario
        return self._inner.handle_request(request)


@pytest.fixture
def stand(
    postgres_url: str,  # noqa: F811
    redis_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    mocks_stack: None,
    persona: Any,
) -> Iterator[dict[str, Any]]:
    persona("sokolova")  # применяет сценарий: Sokolova — клиент банка со счётом
    garipov = persona("garipov")  # не клиент банка: счёт откроется автоматически (D-093)
    firms = [
        Firm("sokolova", SOKOLOVA_INN, "ИП Соколова", kind="IP", is_bank_customer=True,
             members=[Member("owner", "Соколова", "DIRECTOR", SOKOLOVA_INN)]),
        Firm("garipov", garipov.inn, "ИП Гарипов", kind="IP", is_bank_customer=False,
             members=[Member("owner", "Гарипов", "DIRECTOR", garipov.inn)]),
        Firm("other", OTHER_INN, "ООО Чужая", is_bank_customer=False,
             members=[Member("boss", "Чужой", "DIRECTOR", "001000000099")]),
    ]  # fmt: skip
    with make_stand(postgres_url, redis_url, monkeypatch, firms) as s:
        with db.transaction() as session:
            session.execute(text("TRUNCATE outbox"))
        outbox.clear_handlers()
        disbursement.register()
        yield s
        outbox.clear_handlers()
        set_integrations(None)


def use_live(scenario: str | None) -> ListJournal:
    journal = ListJournal()
    client = IntegrationClient(
        make_settings(), journal=journal, transport=FirstPostScenario(scenario)
    )
    set_integrations(build_integrations(client))
    return journal


def signed_application(stand: dict[str, Any], who: str = "sokolova") -> UUID:
    """SIGNED-заявка Соколовой на 500 000 ₽, 12 мес., EXPRESS, и решение ядра со ставкой 24 %."""
    number = (
        f"АЗ-2026-{random.randint(100000, 999999)}"  # номер уникален: мок помнит прошлые выдачи
    )
    with db.transaction() as s:
        company_id = stand["companies"][who]
        user_id = stand["principals"][f"{who}:owner"].user_id
        policy = pipeline.register_current(s)
        application = Application(
            number=number, company_id=company_id, created_by=user_id, status="SIGNED", version=7,
            product_code="EXPRESS", amount_rub=500_000, term_months=12, draft={}, flags=[],
        )  # fmt: skip
        s.add(application)
        s.flush()
        s.add(
            Decision(
                application_id=application.id, source="ENGINE", outcome="APPROVED", route="AUTO",
                required_level="L1", policy_version_id=policy.id, engine_version="test",
                inputs={}, inputs_hash="h", explain={}, snapshot_ids=[],
                rate_percent=24, payment_rub=47_000, max_amount_rub=600_000,
            )
        )  # fmt: skip
        add_signed_contract(s, application)
        return application.id


def make_all_due() -> None:
    with db.transaction() as s:
        s.execute(update(OutboxMessage).values(next_attempt_at=clock.system_now()))


def drain() -> None:
    for _ in range(4):
        make_all_due()
        outbox.relay(budget_s=20)


def bank_loans(inn: str) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{HOST}:{PORTS['bank_core']}/api/v1/customers/{inn}/loans",
        headers={"X-Api-Key": "dev-bank-core-key"},
    )
    response.raise_for_status()
    loans: list[dict[str, Any]] = response.json()["loans"]
    return loans


def our_loans(application_ref: str) -> list[dict[str, Any]]:
    return [x for x in bank_loans(SOKOLOVA_INN) if x["applicationRef"] == application_ref]


def application_number(application_id: UUID) -> str:
    with db.transaction() as s:
        return s.get(Application, application_id).number  # type: ignore[union-attr]


def expected_first_payment(opened_on: date) -> date:
    """The live bank may use today's date while the API test clock is fixed.

    Independently verify the date rule against the actual value date returned by the bank;
    never copy the production schedule calculator into the expected value.
    """
    year = opened_on.year + (opened_on.month == 12)
    month = opened_on.month % 12 + 1
    due = date(year, month, min(opened_on.day, 28, monthrange(year, month)[1]))
    while due.weekday() >= 5:
        due += timedelta(days=1)
    return due


def test_sokolova_signed_to_disbursed_with_schedule(stand: dict[str, Any]) -> None:
    journal = use_live(None)
    application_id = signed_application(stand)
    assert disbursement.run(application_id) == "STARTED"
    drain()

    with db.transaction() as s:
        application = s.get(Application, application_id)
        assert application is not None and application.status == "DISBURSED"
        loans = list(s.scalars(select(Loan)))
        assert len(loans) == 1 and loans[0].principal_rub == 500_000
        assert loans[0].outstanding_rub == 500_000 and loans[0].kind == "LOAN"
        rows = list(s.scalars(select(PaymentScheduleRow).order_by(PaymentScheduleRow.seq)))
        assert len(rows) == 12
        assert sum(r.principal_rub for r in rows) == 500_000
        assert rows[0].due_date == expected_first_payment(loans[0].opened_on)
        sent = s.scalars(select(OutboxMessage.event_type).where(OutboxMessage.status == "SENT"))
        assert sorted(sent) == ["DISBURSEMENT", "OBLIGATION_OPENED"]
    mine = our_loans(application_number(application_id))
    assert len(mine) == 1 and mine[0]["outstandingRub"] == 500_000
    assert not [r for r in journal.records if r.idempotent_replayed]


def test_lost_response_and_duplicate_task_give_exactly_one_disbursement(
    stand: dict[str, Any],
) -> None:
    journal = use_live("LOST_RESPONSE")
    application_id = signed_application(stand)
    # Задача доставлена дважды, одновременно из двух потоков
    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(disbursement.run(application_id)))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ALREADY", "STARTED"]
    assert disbursement.run(application_id) == "ALREADY"

    outbox.relay(budget_s=20)  # первая попытка: мок выдал деньги и оборвал связь
    with db.transaction() as s:
        assert s.get(Application, application_id).status == "DISBURSING"  # type: ignore[union-attr]
        assert s.scalar(select(func.count()).select_from(Loan)) == 0
        message = s.scalars(
            select(OutboxMessage).where(OutboxMessage.event_type == "DISBURSEMENT")
        ).one()
        assert message.status == "PENDING" and message.attempts == 1
    assert len(our_loans(application_number(application_id))) == 1  # деньги уже выданы

    drain()  # повтор с тем же ключом получает сохранённый ответ
    with db.transaction() as s:
        assert s.get(Application, application_id).status == "DISBURSED"  # type: ignore[union-attr]
        assert s.scalar(select(func.count()).select_from(Loan)) == 1
        assert s.scalar(select(func.count()).select_from(PaymentScheduleRow)) == 12
    assert len(our_loans(application_number(application_id))) == 1  # у АБС по-прежнему одна выдача
    assert [
        r.idempotent_replayed for r in journal.records if r.path.endswith("/disbursements")
    ] == [
        False,
        True,
    ]


def test_my_loans_api_shows_loan_to_owner_and_404_to_foreign(stand: dict[str, Any]) -> None:
    use_live(None)
    application_id = signed_application(stand)
    disbursement.run(application_id)
    drain()
    with db.transaction() as s:
        loan = s.scalars(select(Loan)).one()
        loan_id = loan.id
        expected_due = expected_first_payment(loan.opened_on).isoformat()

    async def check() -> None:
        async with client_for(stand, "sokolova:owner") as owner:
            assert (await owner.get("/loans", params={"cursor": "bad"})).status_code == 422
            listing = (await owner.get("/loans")).json()
            assert [i["id"] for i in listing["items"]] == [str(loan_id)]
            detail = (await owner.get(f"/loans/{loan_id}")).json()
            assert len(detail["schedule"]) == 12 and detail["amountRub"] == 500_000
            assert detail["nextPayment"]["dueDate"] == expected_due
            assert detail["nextPayment"]["totalRub"] == detail["schedule"][0]["totalRub"]
            assert (await owner.get(f"/loans/{loan_id}/schedule")).status_code == 200
        async with client_for(stand, "other:boss") as stranger:
            assert (await stranger.get("/loans")).json()["items"] == []
            assert (await stranger.get(f"/loans/{loan_id}")).status_code == 404
            assert (await stranger.get(f"/loans/{loan_id}/schedule")).status_code == 404

    import asyncio

    asyncio.run(check())
    assert TODAY + timedelta(days=0) == clock.today()


def test_garipov_gets_settlement_account_then_loan(stand: dict[str, Any]) -> None:
    use_live(None)
    application_id = signed_application(stand, "garipov")
    disbursement.run(application_id)
    drain()
    with db.transaction() as s:
        application = s.get(Application, application_id)
        assert application is not None and application.status == "DISBURSED"
        loan = s.scalars(select(Loan)).one()
        assert len(loan.settlement_account) == 20


def test_confirmation_transaction_crash_recovers_without_second_bank_loan(
    stand: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    use_live(None)
    application_id = signed_application(stand)
    disbursement.run(application_id)
    original = delivery.open_loan

    def crash_after_insert(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise RuntimeError("worker lost before confirmation commit")

    monkeypatch.setattr(delivery, "open_loan", crash_after_insert)
    assert outbox.relay(budget_s=5).retried == 1
    assert len(our_loans(application_number(application_id))) == 1
    with db.transaction() as s:
        assert s.scalar(select(Loan.id)) is None
        assert s.get(Application, application_id).status == "DISBURSING"
        assert s.scalars(select(OutboxMessage.event_type)).all() == ["DISBURSEMENT"]

    monkeypatch.setattr(delivery, "open_loan", original)
    drain()
    assert len(our_loans(application_number(application_id))) == 1
    with db.transaction() as s:
        assert s.get(Application, application_id).status == "DISBURSED"
        assert s.scalar(select(func.count()).select_from(Loan)) == 1
        assert s.scalar(select(func.count()).select_from(PaymentScheduleRow)) == 12
        assert sorted(s.scalars(select(OutboxMessage.event_type))) == [
            "DISBURSEMENT",
            "OBLIGATION_OPENED",
        ]
