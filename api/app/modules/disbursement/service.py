"""Запуск выдачи: `SIGNED → DISBURSING`, строка `disbursements` и сообщение в outbox — одна транзакция.

Дальше работает ретранслятор outbox (`delivery.py`). Повторная доставка задачи и параллельные
подписи безопасны: заявку блокирует `SELECT … FOR UPDATE`, переход «сравнить и поменять», а
`disbursements.application_id` и ключ outbox уникальны (INV-83).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import companies
from app.modules.applications import Actor, Application, Status, record_event, transition
from app.modules.disbursement import keys
from app.modules.disbursement.models import Disbursement
from app.modules.disbursement.terms import agreed_terms, shape_of
from app.shared import clock
from app.shared.outbox import enqueue_outbox

log = structlog.get_logger("app.disbursement")


class StartResult(StrEnum):
    STARTED = "STARTED"  # перевели в DISBURSING и записали выдачу
    ALREADY = "ALREADY"  # выдача уже идёт или закончена: повторная доставка задачи
    SKIPPED = "SKIPPED"  # заявка в статусе, из которого выдавать нельзя
    NO_TERMS = "NO_TERMS"  # нет условий кредита: дефект, остановка


def _enqueue_bank_message(session: Session, disbursement: Disbursement) -> None:
    enqueue_outbox(
        session,
        aggregate_id=str(disbursement.application_id),
        event_type=keys.DISBURSEMENT_EVENT,
        target="BANK_CORE",
        payload={"disbursementId": str(disbursement.id)},
        idempotency_key=disbursement.idempotency_key,
    )


def start(session: Session, application_id: UUID) -> StartResult:
    """Шаги 1–3 из 20-05 без сети: проверка, переход статуса, запись выдачи и сообщения."""
    application = session.scalars(
        select(Application).where(Application.id == application_id).with_for_update()
    ).first()
    if application is None:
        log.error("disbursement_application_missing", application=str(application_id))
        return StartResult.SKIPPED
    status = Status(application.status)
    existing = session.scalars(
        select(Disbursement).where(Disbursement.application_id == application_id)
    ).first()
    if status in (Status.DISBURSING, Status.DISBURSED):
        if existing is not None and status is Status.DISBURSING:
            _enqueue_bank_message(session, existing)  # на случай потерянной записи: ключ уникален
        return StartResult.ALREADY
    if status is not Status.SIGNED:
        log.warning("disbursement_wrong_status", application=str(application_id), status=status)
        return StartResult.SKIPPED
    if existing is not None:  # выдача записана, а статус не сменился: достраиваем
        _enqueue_bank_message(session, existing)
        transition(session, application, Status.DISBURSING, actor=Actor.SYSTEM)
        return StartResult.STARTED
    terms = agreed_terms(session, application_id)
    company = companies.by_id(session, application.company_id)
    if terms is None or company is None:
        log.error("disbursement_no_terms", application=str(application_id))
        return StartResult.NO_TERMS
    shape = shape_of(terms.product_code)
    number = terms.contract_number or "КД-" + application.number.split("-", 1)[-1]
    disbursement = Disbursement(
        application_id=application_id,
        company_id=application.company_id,
        application_ref=application.number,
        customer_inn=company.inn,
        contract_number=number,
        contract_uid=terms.contract_uid or keys.contract_uid(application_id),
        signed_at=terms.signed_at or clock.now(),
        product_code=terms.product_code,
        kind=shape.kind,
        repayment_type=shape.repayment_type,
        # Линия и овердрафт: открывается лимит, денег не выдаём, транша нет (D-093)
        amount_rub=0 if shape.is_limit else terms.amount_rub,
        limit_rub=terms.amount_rub if shape.is_limit else None,
        term_months=terms.term_months,
        rate_percent=terms.rate_percent,
        status="PENDING",
        idempotency_key=keys.disbursement_key(application_id),
    )
    session.add(disbursement)
    session.flush()
    transition(session, application, Status.DISBURSING, actor=Actor.SYSTEM)
    record_event(
        session,
        application,
        "STEP",
        actor_type=Actor.SYSTEM,
        step_code="DISBURSEMENT_STARTED",
        payload={"disbursementId": str(disbursement.id)},
    )
    _enqueue_bank_message(session, disbursement)
    return StartResult.STARTED
