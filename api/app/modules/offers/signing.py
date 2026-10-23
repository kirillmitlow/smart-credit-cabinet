"""Подписание договора простой подписью и «передать руководителю» (T-263, 20-04, D-014, D-091, D-092).

Механика та же, что у согласий: галочка → шестизначный код (`auth.codes`) → HMAC-доказательство
(`applications.proof_for`, ничего не дублируем). Код привязан к человеку и к хешу документа.
Подписывает только руководитель: бухгалтер, даже с доверенностью на согласия, получает
`ROLE_CANNOT_SIGN`. Порядок подписей любой; когда собраны все обязательные, система переводит
`OFFER_ACCEPTED → SIGNED` ровно один раз и после коммита ставит задачу выдачи по имени (R10).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth, companies
from app.modules.applications import (
    SIGN_METHOD,
    Actor,
    Application,
    ApplicationEvent,
    Status,
    ensure_pep_rules,
    pep_rules_version,
    proof_for,
    record_event,
    signer_identity,
    transition,
)
from app.modules.offers import contracts
from app.modules.offers.models import Contract, Offer, Signature
from app.modules.offers.service import application_for
from app.shared import clock
from app.shared.errors import AppError, not_found
from app.shared.tasks import enqueue

SIGN_PURPOSE = "SIGN_CONTRACT"
CONTRACT_KIND = "CONTRACT"
DISBURSEMENT_TASK = "disbursement.run"
SIGNATURE_REQUESTED = "SIGNATURE_REQUESTED"


@dataclass(frozen=True, slots=True)
class Signer:
    """Обязательный подписант договора и его подпись, если уже есть."""

    role: str
    user_id: UUID
    name: str
    person_inn: str | None
    signature: Signature | None


@dataclass(frozen=True, slots=True)
class Challenge:
    request_id: str
    expires_in: int
    code: str


def contract_for(
    session: Session, principal: auth.Principal, contract_id: UUID, *, lock: bool = False
) -> tuple[Contract, Application]:
    """Договор клиента; чужой, несуществующий и «не для поручителя» неразличимы: 404 (R11)."""
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise not_found("Договор")
    try:
        application = application_for(session, principal, contract.application_id, lock=lock)
    except AppError as exc:
        raise not_found("Договор") from exc
    if lock:
        session.refresh(contract, with_for_update=True)
    return contract, application


def _offer_of(session: Session, contract: Contract) -> Offer:
    offer = session.get(Offer, contract.offer_id)
    if offer is None:
        raise not_found("Предложение")
    return offer


def signers(session: Session, contract: Contract, application: Application) -> list[Signer]:
    """Кто обязан подписать. Сейчас один подписант — руководитель компании (D-014).

    Поручитель и заявление на счёт (D-093) появятся с T-257 и документами T-336; таблица подписей
    и подсчёт `SIGNED` уже рассчитаны на несколько подписантов в любом порядке (D-092).
    """
    signed = {
        s.signer_user_id: s
        for s in session.scalars(select(Signature).where(Signature.contract_id == contract.id))
    }
    director = next(
        (p for p in companies.people(session, application.company_id) if p.role == "DIRECTOR"), None
    )
    if director is None:
        return []
    return [
        Signer(
            "DIRECTOR",
            director.user_id,
            director.display_name,
            director.person_inn,
            signed.get(director.user_id),
        )
    ]


def can_sign(principal: auth.Principal, application: Application, required: list[Signer]) -> bool:
    member = principal.membership(application.company_id)
    return (
        member is not None
        and member.role == "DIRECTOR"
        and any(s.user_id == principal.user_id and s.signature is None for s in required)
    )


def _authorize(
    principal: auth.Principal, application: Application, required: list[Signer]
) -> Signer:
    member = principal.membership(application.company_id)
    if member is None or member.role != "DIRECTOR":
        raise AppError(403, "ROLE_CANNOT_SIGN", "Договор подписывает только руководитель компании")
    mine = next((s for s in required if s.user_id == principal.user_id), None)
    if mine is None:
        raise AppError(403, "SIGNER_MISMATCH", "Вы не числитесь руководителем этой компании")
    return mine


def _ensure_signable(
    session: Session, contract: Contract, application: Application, offer: Offer
) -> None:
    if contract.status != "READY" or Status(application.status) is not Status.OFFER_ACCEPTED:
        raise AppError(
            409,
            "INVALID_TRANSITION",
            "Договор уже нельзя подписать",
            errors=[{"currentStatus": application.status, "contractStatus": contract.status}],
        )
    if clock.now() > offer.expires_at:
        raise AppError(409, "OFFER_EXPIRED", "Срок предложения истёк")
    contracts.verify_integrity(contract)
    contracts.signing_hash(session, contract)


def _fingerprint(session: Session, contract: Contract) -> str:
    """Предмет кода: тот же код не подпишет другой договор или другой файл."""
    digest = contracts.signing_hash(session, contract)
    if contract.document_id is None:
        return hashlib.sha256(f"{contract.id}:{contract.content_hash}".encode()).hexdigest()
    return hashlib.sha256(f"{contract.id}:{contract.content_hash}:{digest}".encode()).hexdigest()


def request_code(
    session: Session,
    principal: auth.Principal,
    contract_id: UUID,
    *,
    accept_pep_rules: bool,
) -> Challenge:
    """Шаг 1: «Подписать» нажато → проверить полномочия, принять правила подписи, выпустить код."""
    contract, application = contract_for(session, principal, contract_id)
    required = signers(session, contract, application)
    mine = _authorize(principal, application, required)
    if mine.signature is not None:
        raise AppError(409, "CONTRACT_ALREADY_SIGNED", "Вы уже подписали этот договор")
    offer = _offer_of(session, contract)
    _ensure_signable(session, contract, application, offer)
    ensure_pep_rules(session, principal, application, accepted=accept_pep_rules)
    issued = auth.codes.issue(
        signer_identity(principal),
        SIGN_PURPOSE,
        _fingerprint(session, contract),
        company_id=application.company_id,
    )
    return Challenge(issued.request_id, issued.expires_in, issued.code)


def sign(
    session: Session,
    principal: auth.Principal,
    contract_id: UUID,
    request_id: str,
    code: str,
) -> tuple[Contract, Application, bool]:
    """Шаг 2: верный код подписывает договор. Возвращает (договор, заявка, подписано ли только что).

    Двойное «Подписать» (тот же запрос или новая попытка после подписи) возвращает прежнюю
    подпись: второй записи и второго перехода не будет. Строки заявки и договора блокируются на
    время сценария, поэтому два параллельных запроса выстраиваются в очередь.
    """
    contract, application = contract_for(session, principal, contract_id, lock=True)
    required = signers(session, contract, application)
    mine = _authorize(principal, application, required)
    if mine.signature is not None:
        return contract, application, False
    offer = _offer_of(session, contract)
    _ensure_signable(session, contract, application, offer)

    verified = auth.codes.verify(request_id, code, purpose=SIGN_PURPOSE)
    if verified.person_inn != signer_identity(principal) or verified.subject != _fingerprint(
        session, contract
    ):
        raise AppError(403, "SIGNER_MISMATCH", "Код выдан другому человеку или на другой документ")
    company = companies.by_id(session, application.company_id)
    if company is None:
        raise not_found("Компания")
    now = clock.now()
    digest = contracts.signing_hash(session, contract)
    session.add(
        Signature(
            contract_id=contract.id,
            signer_user_id=principal.user_id,
            signer_person_inn=principal.person_inn,
            signer_role=mine.role,
            proof=proof_for(
                code=code,
                text_hash=digest,
                signer_inn=signer_identity(principal),
                attempt_id=request_id,
                subject_inn=company.inn,
                kind=CONTRACT_KIND,
            ),
            method=SIGN_METHOD,
            attempt_id=request_id,
            consent_text_version=pep_rules_version(),
            content_hash=digest,
            signed_at=now,
        )
    )
    session.flush()
    signed_now = len(
        [s for s in required if s.signature is not None or s.user_id == principal.user_id]
    )
    record_event(
        session,
        application,
        "STEP",
        actor_type=Actor.CLIENT,
        actor_id=principal.user_id,
        step_code="CONTRACT_SIGNED_BY",
        payload={
            "contractId": str(contract.id),
            "role": mine.role,
            "signed": signed_now,
            "required": len(required),
        },
    )
    if signed_now >= len(required):
        _complete(session, contract, application, now)
    return contract, application, True


def _complete(
    session: Session, contract: Contract, application: Application, now: datetime
) -> None:
    """Все обязательные подписи собраны: `OFFER_ACCEPTED → SIGNED` и передача выдаче после коммита."""
    contract.status = "SIGNED"
    contract.signed_at = now
    session.flush()
    transition(
        session,
        application,
        Status.SIGNED,
        actor=Actor.SYSTEM,
        payload={"contractId": str(contract.id), "contractUid": contract.contract_uid},
    )
    enqueue(session, DISBURSEMENT_TASK, application_id=str(application.id))


def pass_to_director(
    session: Session, principal: auth.Principal, contract_id: UUID
) -> tuple[Contract, datetime, bool]:
    """«Передать руководителю на подпись» (D-014): запись в журнал заявки. Возвращает (договор, когда, повтор).

    Отдельной таблицы задач пока нет (модуль задач — T-25x), поэтому «задача» — событие `TASK`
    в журнале заявки; повторное нажатие ничего не добавляет.
    """
    contract, application = contract_for(session, principal, contract_id, lock=True)
    member = principal.membership(application.company_id)
    if member is None:
        raise not_found("Договор")
    if member.role == "DIRECTOR":
        raise AppError(409, "CAN_SIGN_YOURSELF", "Вы руководитель: подпишите договор сами")
    offer = _offer_of(session, contract)
    _ensure_signable(session, contract, application, offer)
    existing = session.scalars(
        select(ApplicationEvent).where(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.kind == "TASK",
            ApplicationEvent.step_code == SIGNATURE_REQUESTED,
            ApplicationEvent.payload["contractId"].as_string() == str(contract.id),
        )
    ).first()
    if existing is not None:
        return contract, existing.at, True
    event = record_event(
        session,
        application,
        "TASK",
        actor_type=Actor.CLIENT,
        actor_id=principal.user_id,
        step_code=SIGNATURE_REQUESTED,
        payload={"contractId": str(contract.id), "fromRole": member.role},
    )
    return contract, event.at, False
