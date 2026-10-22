"""Обработчики outbox выдачи: АБС (счёт, деньги, кредит) и БКИ (`OBLIGATION_OPENED`). Документ: 20-05.

Обработчик АБС идемпотентен по шагам и безопасен при любом повторе:

1. счёт: берём открытый расчётный счёт клиента; нет — открываем (`acc:{заявка}`), `409 ACCOUNT_ALREADY_EXISTS`
   считаем успехом и читаем клиента;
2. выдача: `POST disbursements` с ключом `dsb:{заявка}` и тем же телом из `disbursements`;
3. подтверждение: кредит, график, `DISBURSING → DISBURSED` и сообщение в БКИ — одна транзакция.

Ответ на `LOST_RESPONSE` не приходит, но деньги выданы: следующая попытка с тем же ключом получает
сохранённый ответ (`Idempotent-Replayed`), второй выдачи нет. Завершает `DISBURSED` этот обработчик,
а не HTTP-ответ клиенту.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import audit, companies
from app.modules.applications import Actor, Application, Status, record_event, transition
from app.modules.decisioning import add_months
from app.modules.disbursement import bki_events, keys
from app.modules.disbursement.models import Disbursement
from app.modules.integrations import (
    Disbursed,
    DisbursementRequest,
    Failure,
    Ok,
    OpenedAccount,
    OurLoan,
    SourceUnavailable,
    classify_failure,
    get_integrations,
)
from app.modules.integrations.bank_core_write import (
    ACCOUNT_BLOCKED,
    ACCOUNT_NOT_OWNED,
    BankCoreWriteAdapter,
)
from app.modules.loans import NewLoan, open_loan
from app.shared import clock, db, outbox
from app.shared.outbox import Dead, Defer, Delivered, OutboxItem, Outcome, Retry

log = structlog.get_logger("app.disbursement.delivery")

BANK_CORE = "BANK_CORE"
BKI = "BKI"


@dataclass(frozen=True, slots=True)
class _Plan:
    """Снимок строки выдачи для работы вне транзакции."""

    id: UUID
    application_id: UUID
    status: str
    account_number: str | None
    customer_inn: str
    customer_name: str
    request: DisbursementRequest


def _write_port() -> BankCoreWriteAdapter:
    port = get_integrations().bank_core_write
    if port is None:
        raise RuntimeError("Порт записи в АБС не собран: нужен bank_core_write")
    return port


def _unavailable(failure: SourceUnavailable) -> Outcome:
    """Недоступность или отказ источника → решение для outbox."""
    kind = classify_failure(failure)
    label = failure.error_code or failure.reason.value
    if kind is Failure.DEFER:
        return Defer(error=label)
    if kind is Failure.RETRY:
        return Retry(label)
    return Dead(label)


def _load_plan(session: Session, application_id: UUID) -> _Plan | None:
    row = session.scalars(
        select(Disbursement).where(Disbursement.application_id == application_id)
    ).first()
    company = companies.by_id(session, row.company_id) if row else None
    if row is None or company is None:
        return None
    request = DisbursementRequest(
        application_ref=row.application_ref,
        customer_inn=row.customer_inn,
        contract_number=row.contract_number,
        contract_uid=row.contract_uid,
        contract_signed_at=row.signed_at,
        product_code=row.product_code,
        kind=row.kind,  # type: ignore[arg-type]
        amount_rub=row.amount_rub,
        limit_rub=row.limit_rub,
        term_months=row.term_months,
        rate_percent=float(row.rate_percent),
        repayment_type=row.repayment_type,  # type: ignore[arg-type]
        settlement_account=row.account_number or "",
    )
    return _Plan(
        row.id, row.application_id, row.status, row.account_number, row.customer_inn, company.name,
        request,
    )  # fmt: skip


# --- шаг 1: счёт ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Account:
    number: str
    opened_now: bool


def _settlement_account(plan: _Plan) -> _Account | Outcome:
    """Расчётный счёт клиента: открытый — берём, нет — открываем."""
    integrations = get_integrations()
    customer = integrations.bank_core.get_customer(
        plan.customer_inn, application_id=plan.application_id
    )
    if isinstance(customer, SourceUnavailable):
        return _unavailable(customer)
    accounts = [
        a for a in (customer.data.accounts if customer.data else ()) if a.type == "SETTLEMENT"
    ]
    opened = next((a for a in accounts if a.status == "OPEN"), None)
    if opened is not None:
        return _Account(opened.number, False)
    if accounts:  # счёт есть, но не открыт: открывать второй нельзя, решает человек
        return Dead(ACCOUNT_BLOCKED)
    result = _write_port().open_account(
        plan.customer_inn,
        "LEGAL_ENTITY" if len(plan.customer_inn) == 10 else "INDIVIDUAL_ENTREPRENEUR",
        plan.customer_name,
        idempotency_key=keys.account_key(plan.application_id),
        application_id=plan.application_id,
    )
    if isinstance(result, Ok):
        return _Account(_number(result.data), True)
    if classify_failure(result) is Failure.ACCOUNT_EXISTS:
        # Счёт появился между чтением и открытием (или прошлая попытка потеряла ответ): читаем клиента
        again = integrations.bank_core.get_customer(
            plan.customer_inn, application_id=plan.application_id
        )
        if isinstance(again, SourceUnavailable):
            return _unavailable(again)
        existing = next(
            (
                a
                for a in (again.data.accounts if again.data else ())
                if a.type == "SETTLEMENT" and a.status == "OPEN"
            ),
            None,
        )
        return _Account(existing.number, False) if existing else Dead(ACCOUNT_BLOCKED)
    return _unavailable(result)


def _number(opened: OpenedAccount) -> str:
    return opened.account.number


def _save_account(plan: _Plan, account: _Account) -> None:
    with db.transaction() as session:
        row = session.get(Disbursement, plan.id)
        application = session.get(Application, plan.application_id)
        if row is None or application is None:
            return
        if row.account_number is None:
            row.account_number = account.number
            if account.opened_now:
                record_event(
                    session,
                    application,
                    "STEP",
                    actor_type=Actor.SYSTEM,
                    step_code="ACCOUNT_OPENED",
                )


# --- шаг 2: выдача --------------------------------------------------------------------------------


def _mark_sent(plan: _Plan) -> None:
    with db.transaction() as session:
        row = session.get(Disbursement, plan.id)
        if row is not None and row.status in ("PENDING", "FAILED"):
            row.status, row.last_error = "SENT", None


def _stop(plan: _Plan, code: str, *, step: str = "DISBURSEMENT_STOPPED") -> Outcome:
    """Остановка до решения человека: заявка остаётся `DISBURSING`, автоповторов нет (20-05)."""
    with db.transaction() as session:
        row = session.get(Disbursement, plan.id)
        application = session.get(Application, plan.application_id)
        if row is not None and row.status != "CONFIRMED":
            row.status, row.last_error = "FAILED", code
        if application is not None:
            record_event(
                session,
                application,
                "STEP",
                actor_type=Actor.SYSTEM,
                step_code=step,
                reason_code=code,
            )
    return Dead(code)


def _reconcile(plan: _Plan) -> Disbursed | Outcome:
    """`409 ALREADY_DISBURSED`: сверяем договор, условия и счёт, а не только сумму."""
    loans = get_integrations().bank_core.get_loans(
        plan.customer_inn, application_id=plan.application_id
    )
    if isinstance(loans, SourceUnavailable):
        return _unavailable(loans)
    found: OurLoan | None = next(
        (x for x in (loans.data or ()) if x.application_ref == plan.request.application_ref), None
    )
    if found is None:
        return _stop(plan, "ALREADY_DISBURSED_NOT_FOUND")
    expected = plan.request
    if (
        found.amount_rub != expected.amount_rub
        or found.limit_rub != expected.limit_rub
        or found.contract_uid != expected.contract_uid
        or found.contract_number != expected.contract_number
        or found.product_code != expected.product_code
        or found.kind != expected.kind
        or found.term_months != expected.term_months
        or Decimal(str(found.rate_percent)) != Decimal(str(expected.rate_percent))
        or found.repayment_type != expected.repayment_type
        or found.settlement_account != expected.settlement_account
        or not found.loan_account
    ):
        log.error(
            "disbursement_amount_mismatch",
            application=str(plan.application_id),
            expected=expected.amount_rub,
            actual=found.amount_rub,
        )
        return _stop(plan, "ALREADY_DISBURSED_MISMATCH")
    return Disbursed(
        disbursement_id="reconciled",
        loan_id=found.loan_id,
        loan_account=found.loan_account,
        settlement_account=found.settlement_account,
        amount_rub=found.amount_rub or 0,
        value_date=found.disbursed_at,
        settlement_balance_rub=0,
    )


def deliver_bank_core(item: OutboxItem) -> Outcome:
    """Весь путь выдачи в АБС. Любой возврат безопасно повторить."""
    application_id = UUID(item.aggregate_id)
    with db.transaction() as session:
        plan = _load_plan(session, application_id)
    if plan is None:
        return Dead("DISBURSEMENT_NOT_FOUND")
    if plan.status == "CONFIRMED":
        return Delivered()

    account_number = plan.account_number
    if account_number is None:
        found = _settlement_account(plan)
        if not isinstance(found, _Account):
            return _stop_if_dead(plan, found)
        _save_account(plan, found)
        account_number = found.number
    request = replace(plan.request, settlement_account=account_number)
    plan = replace(plan, account_number=account_number, request=request)

    _mark_sent(plan)
    result = _write_port().disburse(
        request,
        idempotency_key=keys.disbursement_key(application_id),
        application_id=application_id,
    )
    disbursed: Disbursed
    if isinstance(result, Ok):
        disbursed = result.data
    else:
        failure = classify_failure(result)
        if failure is Failure.ALREADY_DISBURSED:
            reconciled = _reconcile(plan)
            if not isinstance(reconciled, Disbursed):
                return reconciled
            disbursed = reconciled
        elif failure is Failure.ACCOUNT_PROBLEM:
            return _stop(plan, result.error_code or ACCOUNT_NOT_OWNED)
        elif failure is Failure.CUSTOMER_NOT_FOUND:
            with db.transaction() as session:
                row = session.get(Disbursement, plan.id)
                if row is not None and row.status != "CONFIRMED":
                    row.account_number = None  # следующий запуск заново прочитает/откроет счёт
            return Retry(Failure.CUSTOMER_NOT_FOUND.value)  # счёт откроет следующая попытка
        else:
            return _stop_if_dead(plan, _unavailable(result))
    if (
        disbursed.amount_rub != request.amount_rub
        or disbursed.settlement_account != request.settlement_account
        or not disbursed.loan_account
    ):
        return _stop(plan, "DISBURSEMENT_RESPONSE_MISMATCH")
    _confirm(plan, disbursed)
    return Delivered()


def _stop_if_dead(plan: _Plan, outcome: Outcome) -> Outcome:
    """`Dead` фиксируем в выдаче и заявке; повторяемые сбои возвращаем как есть."""
    if isinstance(outcome, Dead):
        return _stop(plan, outcome.error)
    return outcome


# --- шаг 3: подтверждение -------------------------------------------------------------------------


def _confirm(plan: _Plan, done: Disbursed) -> None:
    """Выдача подтверждена: кредит, график, `DISBURSED`, сообщение в БКИ — одна транзакция."""
    with db.transaction() as session:
        application = session.scalars(
            select(Application).where(Application.id == plan.application_id).with_for_update()
        ).one()
        row = session.scalars(
            select(Disbursement).where(Disbursement.id == plan.id).with_for_update()
        ).one()
        if row.status == "CONFIRMED":
            return
        opened_on = done.value_date
        row.status, row.last_error = "CONFIRMED", None
        row.bank_core_ref = done.loan_id
        row.loan_account = done.loan_account
        row.value_date = done.value_date
        row.confirmed_at = clock.now()
        loan = open_loan(
            session,
            NewLoan(
                company_id=row.company_id,
                application_id=row.application_id,
                disbursement_id=row.id,
                bank_core_loan_id=done.loan_id,
                contract_number=row.contract_number,
                contract_uid=row.contract_uid,
                product_code=row.product_code,
                kind=row.kind,
                repayment_type=row.repayment_type,
                amount_rub=row.amount_rub,
                limit_rub=row.limit_rub,
                rate_percent=Decimal(row.rate_percent),
                term_months=row.term_months,
                loan_account=done.loan_account,
                settlement_account=done.settlement_account,
                opened_on=opened_on,
            ),
        )
        if application.status == Status.DISBURSING.value:
            transition(session, application, Status.DISBURSED, actor=Actor.SYSTEM)
        record_event(
            session,
            application,
            "STEP",
            actor_type=Actor.SYSTEM,
            step_code="DISBURSED",
            payload={"loanId": str(loan.id), "bankCoreLoanId": done.loan_id},
        )
        outbox.enqueue_outbox(
            session,
            aggregate_id=str(row.application_id),
            event_type=keys.OBLIGATION_EVENT,
            target=BKI,
            payload=bki_events.build_payload(
                row, loan.payment_rub, opened_on, _planned_close(opened_on, row.term_months)
            ),
            idempotency_key=keys.obligation_key(row.application_id),
        )


def _planned_close(opened_on: date, term_months: int) -> date:
    return add_months(opened_on, term_months)


# --- БКИ ------------------------------------------------------------------------------------------


def deliver_obligation(item: OutboxItem) -> Outcome:
    """`OBLIGATION_OPENED` в БКИ: повтор с тем же `eventId` и ключом возвращает исходный ответ."""
    event = bki_events.event_from_payload(item.payload)
    result = get_integrations().credit_bureau.submit_event(
        event, idempotency_key=item.idempotency_key, application_id=UUID(item.aggregate_id)
    )
    if isinstance(result, Ok):
        return Delivered()
    return _unavailable(result)


def audit_dead_letter(session: Session, item: OutboxItem, error: str) -> None:
    """Запись в аудит, когда сообщение ушло в `FAILED` (50-05): ручной разбор."""
    audit.record(
        session,
        "OUTBOX_FAILED",
        actor_role="SYSTEM",
        object_type="outbox",
        object_id=str(item.id),
        details={"type": item.event_type, "target": item.target_system, "error": error},
    )


def register() -> None:
    """Подключить обработчики к ретранслятору (воркер при старте, тесты)."""
    outbox.register_handler(BANK_CORE, keys.DISBURSEMENT_EVENT, deliver_bank_core)
    outbox.register_handler(BKI, keys.OBLIGATION_EVENT, deliver_obligation)
