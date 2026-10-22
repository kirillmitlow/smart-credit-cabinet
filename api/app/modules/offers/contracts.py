"""Договор по принятому варианту: `contract_uid`, номер, тело и его SHA-256 (T-341, 20-04, 50-12).

PDF не делаем (T-336): тело — детерминированный JSON, поэтому одно и то же предложение даёт
побайтно одинаковый документ и один и тот же хеш. Подписывается именно сохранённое тело, а не
пересозданное; при проверке подписи хеш пересчитывается (`verify_integrity`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import companies
from app.modules.applications import BANK_NAME, Actor, Application, record_event
from app.modules.offers import terms
from app.modules.offers.models import Contract, Offer, OfferVariant
from app.shared import clock
from app.shared.errors import AppError, not_found

TEMPLATE_VERSION = "credit-agreement-v1"
DEMO_NOTICE = "ДЕМО. Синтетический документ, юридической силы не имеет"
_UID_NAMESPACE = uuid.UUID("0b0f6a52-7f3f-4c55-8f55-3a6c5ab1c0de")


def contract_uid(application_id: UUID, revision: int) -> str:
    """УИд в формате БКИ: UUID v1 + контрольный символ (758-П, п. 5 приложения 2; как в моках).

    Детерминирован: повтор задачи не меняет идентификатор. `contractUid` в АБС = `uid` в БКИ.
    """
    digest = hashlib.sha256(f"{_UID_NAMESPACE}:{application_id}:{revision}".encode()).digest()[:16]
    uid = uuid.UUID(bytes=digest, version=1)
    check = sum(int(char, 16) * (index % 10 + 1) for index, char in enumerate(uid.hex)) % 16
    return f"{uid}-{check:x}"


def contract_number(application_number: str, revision: int) -> str:
    """`АЗ-2026-000001` → `КД-2026-000001`; правка условий даёт суффикс `/2`."""
    base = "КД-" + application_number.removeprefix("АЗ-")
    return base if revision == 1 else f"{base}/{revision}"


def _canonical(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash_of(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_body(
    session: Session,
    application: Application,
    variant: OfferVariant,
    *,
    uid: str,
    number: str,
) -> str:
    company = companies.by_id(session, application.company_id)
    if company is None:
        raise not_found("Компания")
    rate = Decimal(variant.rate_percent) / 100
    card = terms.loan_terms(variant.product_code, variant.amount_rub, rate, variant.term_months)
    body: dict[str, Any] = {
        "notice": DEMO_NOTICE,
        "template": TEMPLATE_VERSION,
        "contractUid": uid,
        "number": number,
        "applicationNumber": application.number,
        "bank": BANK_NAME,
        "borrower": {"inn": company.inn, "name": company.name, "kind": company.kind},
        "product": {
            "code": variant.product_code,
            "title": terms.product_title(variant.product_code),
        },
        "amountRub": variant.amount_rub,
        "termMonths": variant.term_months,
        "ratePercent": format(Decimal(variant.rate_percent).normalize(), "f"),
        "paymentRub": card.payment_rub,
        "lastPaymentRub": card.last_payment_rub,
        "overpaymentRub": card.overpayment_rub,
        "schedule": [
            {
                "number": row.number,
                "paymentRub": row.payment,
                "principalRub": row.principal,
                "interestRub": row.interest,
                "balanceRub": row.balance,
            }
            for row in card.schedule
        ],
    }
    return _canonical(body)


def live_contract(session: Session, application_id: UUID) -> Contract:
    contract = session.scalars(
        select(Contract).where(
            Contract.application_id == application_id, Contract.status != "CANCELLED"
        )
    ).first()
    if contract is None:
        raise not_found("Договор")
    return contract


def cancel_live(session: Session, application_id: UUID) -> None:
    for contract in session.scalars(
        select(Contract).where(
            Contract.application_id == application_id, Contract.status == "READY"
        )
    ):
        contract.status = "CANCELLED"
    session.flush()


def create_contract(
    session: Session, application: Application, offer: Offer, variant: OfferVariant
) -> Contract:
    """Договор по варианту; прежний готовый договор заявки отменяется (правка условий = новый)."""
    live = session.scalars(
        select(Contract).where(
            Contract.application_id == application.id, Contract.status != "CANCELLED"
        )
    ).first()
    if live is not None and live.variant_id == variant.id:
        return live  # повтор: тот же договор, тот же uid
    if live is not None:
        if live.status != "READY":
            raise AppError(409, "CONTRACT_SIGNED", "Договор уже подписан, условия менять нельзя")
        live.status = "CANCELLED"
        session.flush()
    revision = (
        session.scalar(
            select(Contract.revision)
            .where(Contract.application_id == application.id)
            .order_by(Contract.revision.desc())
            .limit(1)
        )
        or 0
    ) + 1
    uid = contract_uid(application.id, revision)
    number = contract_number(application.number, revision)
    body = build_body(session, application, variant, uid=uid, number=number)
    contract = Contract(
        application_id=application.id,
        offer_id=offer.id,
        variant_id=variant.id,
        revision=revision,
        contract_uid=uid,
        number=number,
        template_version=TEMPLATE_VERSION,
        body=body,
        content_hash=content_hash_of(body),
        status="READY",
        created_at=clock.now(),
    )
    session.add(contract)
    session.flush()
    record_event(
        session,
        application,
        "STEP",
        actor_type=Actor.SYSTEM,
        step_code="CONTRACT_CREATED",
        payload={
            "contractId": str(contract.id),
            "contractUid": uid,
            "revision": revision,
            "contentHash": contract.content_hash,
        },
    )
    return contract


def verify_integrity(contract: Contract) -> None:
    """Подписывается сохранённое тело: хеш обязан совпасть, иначе подпись не принимается."""
    if content_hash_of(contract.body) != contract.content_hash:
        raise AppError(
            409, "CONTRACT_TAMPERED", "Документ изменён: хеш не совпал, подпись не принята"
        )


@dataclass(frozen=True, slots=True)
class SignedTerms:
    product_code: str
    amount_rub: int
    term_months: int
    rate_percent: Decimal
    contract_number: str
    contract_uid: str
    signed_at: datetime


def signed_terms(session: Session, application_id: UUID) -> SignedTerms | None:
    """Выдача берёт условия только из подписанного договора принятого варианта."""
    row = session.execute(
        select(Contract, OfferVariant)
        .join(OfferVariant, OfferVariant.id == Contract.variant_id)
        .join(Offer, Offer.id == Contract.offer_id)
        .where(
            Contract.application_id == application_id,
            Contract.status == "SIGNED",
            Offer.status == "ACCEPTED",
            Offer.accepted_variant_id == OfferVariant.id,
            OfferVariant.offer_id == Offer.id,
        )
    ).one_or_none()
    if row is None:
        return None
    contract, variant = row
    if contract.signed_at is None:
        return None
    verify_integrity(contract)
    return SignedTerms(
        product_code=variant.product_code,
        amount_rub=variant.amount_rub,
        term_months=variant.term_months,
        rate_percent=variant.rate_percent,
        contract_number=contract.number,
        contract_uid=contract.contract_uid,
        signed_at=contract.signed_at,
    )
