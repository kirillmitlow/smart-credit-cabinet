"""T-342/T-343: ветки таблицы ответов АБС (20-05) на Postgres с заглушками портов."""

# ruff: noqa: PT018
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.modules import auth, disbursement, offers, pipeline
from app.modules.applications import Application
from app.modules.companies.models import Company
from app.modules.disbursement.models import Disbursement
from app.modules.integrations import (
    BankAccount,
    Customer,
    Disbursed,
    Integrations,
    Ok,
    OurLoan,
    Reason,
    SnapshotMeta,
    SourceUnavailable,
    System,
    set_integrations,
)
from app.modules.loans import Loan, PaymentScheduleRow
from app.modules.pipeline.models import Decision
from app.shared import clock, db, outbox, tasks
from app.shared.models import OutboxMessage
from tests.fixtures.signed_contract import add_signed_contract

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 21)
INN = "001234567887"
META = SnapshotMeta(System.BANK_CORE, None, None, clock.system_now())


def rejected(code: str, status: int = 409) -> SourceUnavailable:
    return SourceUnavailable(System.BANK_CORE, Reason.REJECTED, status, code)


@dataclass
class FakeBank:
    accounts: list[BankAccount] = field(default_factory=list)
    loans: list[OurLoan] = field(default_factory=list)
    disburse_answers: list[Any] = field(default_factory=list)
    disburse_calls: int = 0

    # чтение
    def get_customer(self, inn: str, *, application_id: UUID | None = None) -> Any:
        return Ok(Customer("c1", inn, "IE", "ИП", TODAY, tuple(self.accounts)), META)

    def get_loans(self, inn: str, *, application_id: UUID | None = None) -> Any:
        return Ok(tuple(self.loans), META)

    # запись
    def disburse(self, request: Any, *, idempotency_key: str, application_id: Any = None) -> Any:
        self.disburse_calls += 1
        return self.disburse_answers.pop(0)


def account(status: str = "OPEN") -> BankAccount:
    return BankAccount("40802810800000001234", "SETTLEMENT", "RUB", status, TODAY, 0)


class FakeBureau:
    def submit_event(self, event: Any, **kw: Any) -> Any:
        return Ok(None, META)


@pytest.fixture
def world(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[dict[str, Any]]:
    monkeypatch.setattr(tasks, "send_now", lambda name, **kw: None)
    database = db.configure(postgres_url)
    db.migrate(database.engine)
    clock.set_clock(clock.Clock(TODAY))
    with database.transaction() as s:
        s.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))
        policy = pipeline.register_current(s)
        company = Company(inn=INN, kind="IP", name="ИП Соколова", status="ACTIVE")
        s.add(company)
        user = auth.upsert_client(
            s, login_ref="t:x", display_name="К", person_inn=None, scenario_code=None
        )
        s.flush()
        application = Application(
            number="АЗ-2026-000001", company_id=company.id, created_by=user.id, status="SIGNED",
            version=3, product_code="EXPRESS", amount_rub=500_000, term_months=12, draft={}, flags=[],
        )  # fmt: skip
        s.add(application)
        s.flush()
        s.add(
            Decision(
                application_id=application.id, source="ENGINE", outcome="APPROVED", route="AUTO",
                required_level="L1", policy_version_id=policy.id, engine_version="t", inputs={},
                inputs_hash="h", explain={}, snapshot_ids=[], rate_percent=24, payment_rub=47_000,
            )
        )  # fmt: skip
        contract = add_signed_contract(
            s, application, product_code=getattr(request, "param", "EXPRESS")
        )
        contract_number, contract_uid = contract.number, contract.contract_uid
        application_id = application.id
    bank = FakeBank()
    integrations = Integrations(
        registry=None, tax=None, bank_core=bank, credit_bureau=FakeBureau(), client=SimpleNamespace(close=lambda: None),  # type: ignore[arg-type]
        bank_core_write=bank,  # type: ignore[arg-type]
    )  # fmt: skip
    set_integrations(integrations)
    from app.wiring import wire_modules

    wire_modules()
    outbox.clear_handlers()
    disbursement.register()
    yield {
        "bank": bank,
        "application_id": application_id,
        "contract_number": contract_number,
        "contract_uid": contract_uid,
    }
    set_integrations(None)
    outbox.clear_handlers()
    clock.set_clock(clock.Clock())
    with database.transaction() as s:
        s.execute(text("TRUNCATE applications, companies, users, outbox CASCADE"))
    database.dispose()


def disbursed(loan_id: str = "loan_000001", amount: int = 500_000) -> Ok[Disbursed]:
    return Ok(
        Disbursed("dsb_1", loan_id, "45406810000000000001", account().number, amount, TODAY, 0),
        META,
    )


def status_of(application_id: UUID) -> str:
    with db.transaction() as s:
        return s.get(Application, application_id).status  # type: ignore[union-attr]


def test_blocked_account_stops_in_disbursing_without_auto_retries(world: dict[str, Any]) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account("BLOCKED")]
    assert disbursement.run(world["application_id"]) == "STARTED"
    stats = outbox.relay(budget_s=5)
    assert stats.failed == 1
    assert status_of(world["application_id"]) == "DISBURSING"
    with db.transaction() as s:
        row = s.scalars(select(Disbursement)).one()
        assert row.status == "FAILED" and row.last_error == "ACCOUNT_BLOCKED"
        assert s.scalars(select(OutboxMessage.status)).all() == ["FAILED"]
    assert bank.disburse_calls == 0
    assert outbox.relay(budget_s=2).handled == 0  # автоповторов нет


def test_account_not_owned_is_a_stop(world: dict[str, Any]) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [rejected("ACCOUNT_NOT_OWNED")]
    disbursement.run(world["application_id"])
    assert outbox.relay(budget_s=5).failed == 1
    assert status_of(world["application_id"]) == "DISBURSING"


def test_already_disbursed_with_other_key_reconciles_by_application_ref(
    world: dict[str, Any],
) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [rejected("ALREADY_DISBURSED")]
    bank.loans = [
        OurLoan("loan_000009", "АЗ-2026-000001", world["contract_number"], world["contract_uid"],
                "EXPRESS", "LOAN", 500_000, None,
                500_000, 12, 24.0, "ANNUITY", "45406810000000000009", account().number, "ACTIVE",
                TODAY)
    ]  # fmt: skip
    disbursement.run(world["application_id"])
    outbox.relay(budget_s=5)
    assert status_of(world["application_id"]) == "DISBURSED"
    with db.transaction() as s:
        assert s.scalars(select(Loan.bank_core_loan_id)).all() == ["loan_000009"]


def test_already_disbursed_with_different_amount_raises_alarm(world: dict[str, Any]) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [rejected("ALREADY_DISBURSED")]
    bank.loans = [
        OurLoan("loan_000009", "АЗ-2026-000001", "КД", "uid", "EXPRESS", "LOAN", 400_000, None,
                400_000, 12, 24.0, "ANNUITY", "45406810000000000009", account().number, "ACTIVE",
                TODAY)
    ]  # fmt: skip
    disbursement.run(world["application_id"])
    assert outbox.relay(budget_s=5).failed == 1
    assert status_of(world["application_id"]) == "DISBURSING"
    with db.transaction() as s:
        assert s.scalars(select(Disbursement.last_error)).one() == "ALREADY_DISBURSED_MISMATCH"
        assert s.scalar(select(text("count(*) from loans"))) == 0


def test_bank_unavailable_retries_with_same_body_and_cannot_be_withdrawn(
    world: dict[str, Any],
) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [
        SourceUnavailable(System.BANK_CORE, Reason.HTTP_5XX, 503),
        disbursed(),
    ]
    disbursement.run(world["application_id"])
    outbox.relay(budget_s=5)
    assert status_of(world["application_id"]) == "DISBURSING"
    with db.transaction() as s:
        message = s.scalars(select(OutboxMessage)).one()
        assert message.status == "PENDING" and message.attempts == 1
        message.next_attempt_at = clock.system_now()
    outbox.relay(budget_s=5)
    assert status_of(world["application_id"]) == "DISBURSED"
    assert bank.disburse_calls == 2


def test_missing_customer_rechecks_account_before_retry(world: dict[str, Any]) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [rejected("CUSTOMER_NOT_FOUND", 404), disbursed()]
    disbursement.run(world["application_id"])
    assert outbox.relay(budget_s=5).retried == 1
    with db.transaction() as s:
        assert s.scalars(select(Disbursement.account_number)).one() is None
        s.scalars(select(OutboxMessage)).one().next_attempt_at = clock.system_now()
    outbox.relay(budget_s=5)
    assert status_of(world["application_id"]) == "DISBURSED"


@pytest.mark.parametrize("world", ["CREDIT_LINE"], indirect=True)
def test_limit_product_opens_only_limit_without_schedule(world: dict[str, Any]) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [disbursed(amount=0)]
    disbursement.run(world["application_id"])
    outbox.relay(budget_s=5)
    with db.transaction() as s:
        loan = s.scalars(select(Loan)).one()
        assert loan.kind == "CREDIT_LINE" and loan.limit_rub == 500_000
        assert loan.principal_rub == 0 and loan.payment_rub is None
        assert s.scalar(select(text("count(*) from payment_schedule"))) == 0


def test_disbursement_uses_signed_terms_instead_of_application_or_latest_decision(
    world: dict[str, Any],
) -> None:
    with db.transaction() as s:
        application = s.get(Application, world["application_id"])
        application.amount_rub, application.term_months = 900_000, 36
        old = s.scalars(select(Decision)).one()
        s.add(
            Decision(
                application_id=application.id,
                source="ENGINE",
                outcome="APPROVED",
                route="AUTO",
                required_level="L1",
                policy_version_id=old.policy_version_id,
                engine_version="new",
                inputs={},
                inputs_hash="new",
                explain={},
                snapshot_ids=[],
                rate_percent=30,
                created_at=clock.now() + timedelta(seconds=1),
            )
        )
    assert disbursement.run(world["application_id"]) == "STARTED"
    with db.transaction() as s:
        row = s.scalars(select(Disbursement)).one()
        assert (row.amount_rub, row.term_months, row.rate_percent) == (500_000, 12, 24)
        assert (row.contract_number, row.contract_uid) == (
            world["contract_number"],
            world["contract_uid"],
        )


def test_signed_application_without_signed_contract_does_not_issue(world: dict[str, Any]) -> None:
    with db.transaction() as s:
        s.scalars(select(offers.Contract)).one().status = "READY"
    assert disbursement.run(world["application_id"]) == "NO_TERMS"
    assert status_of(world["application_id"]) == "SIGNED"
    assert world["bank"].disburse_calls == 0


@pytest.mark.parametrize(
    ("field", "value"), [("amount_rub", 400_000), ("settlement_account", "other")]
)
def test_wrong_success_response_does_not_confirm(
    world: dict[str, Any], field: str, value: Any
) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [Ok(replace(disbursed().data, **{field: value}), META)]
    disbursement.run(world["application_id"])
    assert outbox.relay(budget_s=5).failed == 1
    with db.transaction() as s:
        assert s.scalar(select(Loan.id)) is None
        assert s.scalars(select(Disbursement.last_error)).one() == "DISBURSEMENT_RESPONSE_MISMATCH"
        assert s.scalars(select(OutboxMessage.event_type)).all() == ["DISBURSEMENT"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_uid", "other"),
        ("contract_number", "other"),
        ("product_code", "INVESTMENT"),
        ("term_months", 36),
        ("rate_percent", 30.0),
        ("repayment_type", "BULLET"),
        ("settlement_account", "other"),
        ("kind", "CREDIT_LINE"),
    ],
)
def test_reconciliation_rejects_different_contract_terms(
    world: dict[str, Any], field: str, value: Any
) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [rejected("ALREADY_DISBURSED")]
    loan = OurLoan(
        "loan_000009",
        "АЗ-2026-000001",
        world["contract_number"],
        world["contract_uid"],
        "EXPRESS",
        "LOAN",
        500_000,
        None,
        500_000,
        12,
        24.0,
        "ANNUITY",
        "45406810000000000009",
        account().number,
        "ACTIVE",
        TODAY,
    )
    bank.loans = [replace(loan, **{field: value})]
    disbursement.run(world["application_id"])
    assert outbox.relay(budget_s=5).failed == 1
    assert status_of(world["application_id"]) == "DISBURSING"
    with db.transaction() as s:
        assert s.scalar(select(Loan.id)) is None
        assert s.scalars(select(Disbursement.last_error)).one() == "ALREADY_DISBURSED_MISMATCH"


def test_confirmation_next_day_keeps_bank_value_date(world: dict[str, Any]) -> None:
    bank: FakeBank = world["bank"]
    bank.accounts = [account()]
    bank.disburse_answers = [disbursed()]
    disbursement.run(world["application_id"])
    clock.get_clock().advance(timedelta(days=1))
    outbox.relay(budget_s=5)
    with db.transaction() as s:
        assert s.scalars(select(Loan.opened_on)).one() == TODAY
        first = s.scalars(select(PaymentScheduleRow).order_by(PaymentScheduleRow.seq)).first()
        assert first.due_date == date(2026, 11, 23)
        payload = s.scalars(
            select(OutboxMessage.payload).where(OutboxMessage.event_type == "OBLIGATION_OPENED")
        ).one()
        assert payload["obligation"]["openedAt"] == TODAY.isoformat()
