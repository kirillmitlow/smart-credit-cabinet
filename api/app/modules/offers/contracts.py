"""Договор по принятому варианту: `contract_uid`, номер, тело и его SHA-256 (T-341, 20-04, 50-12).

Тело JSON сохраняет неизменные расчётные условия и свой SHA-256. Для новых договоров
сохраняются PDF договора и графика; подпись привязана к исходному PDF. Старые подписанные
JSON остаются доступны без пересоздания. Проверяются и условия, и байты файла.
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

from app.modules import companies, documents
from app.modules.applications import BANK_NAME, Actor, Application, record_event
from app.modules.offers import terms
from app.modules.offers.models import Contract, Offer, OfferVariant, Signature
from app.shared import clock
from app.shared.errors import AppError, not_found

TEMPLATE_VERSION = "credit-agreement-pdf-v1"
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
    context = documents.UploadContext(application.company_id, application.id)
    # Accepting and persisting the two originals is atomic. A failed render rolls back acceptance.
    for kind, suffix, schedule_only in (
        ("CREDIT_AGREEMENT", "agreement", False),
        ("PAYMENT_SCHEDULE", "schedule", True),
    ):
        document = documents.store_generated(
            session,
            context,
            application.created_by,
            content=documents.render_credit(body, schedule_only=schedule_only),
            kind=kind,
            filename=f"{contract.number}-{suffix}.pdf",
            template_version=TEMPLATE_VERSION,
        )
        if kind == "CREDIT_AGREEMENT":
            contract.document_id = document.id
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


def _verify_signed_hash(session: Session, contract: Contract, digest: str) -> None:
    if contract.status != "SIGNED":
        return
    signatures = list(
        session.scalars(select(Signature).where(Signature.contract_id == contract.id))
    )
    if not any(signature.signer_role == "DIRECTOR" for signature in signatures) or any(
        signature.content_hash != digest for signature in signatures
    ):
        raise AppError(409, "CONTRACT_TAMPERED", "Файл не соответствует сохранённой подписи")


def verify_variant(contract: Contract, variant: OfferVariant) -> None:
    """Mutable links must not change the conditions contained in the signed original."""
    try:
        body = json.loads(contract.body)
        matching = (
            body["product"]["code"] == variant.product_code
            and body["amountRub"] == variant.amount_rub
            and body["termMonths"] == variant.term_months
            and Decimal(body["ratePercent"]) == variant.rate_percent
            and body["contractUid"] == contract.contract_uid
            and body["number"] == contract.number
        )
    except (ValueError, KeyError, TypeError):
        matching = False
    if not matching:
        raise AppError(409, "CONTRACT_TAMPERED", "Условия не соответствуют сохранённому договору")


def document_content(session: Session, contract: Contract) -> tuple[bytes, str, str]:
    """Keep legacy signed JSON readable; new contracts sign the saved PDF original."""
    verify_integrity(contract)
    if contract.document_id is None:
        if contract.template_version == TEMPLATE_VERSION:
            raise AppError(409, "DOCUMENT_NOT_READY", "Документ ещё не готов для подписи")
        _verify_signed_hash(session, contract, contract.content_hash)
        return contract.body.encode("utf-8"), "application/json", contract.content_hash
    application = session.get(Application, contract.application_id)
    if application is None:
        raise not_found("Заявка")
    row, content = documents.verified_content(
        session,
        documents.Access(application.created_by, (application.company_id,)),
        contract.document_id,
    )
    if (
        row.application_id != application.id
        or row.kind != "CREDIT_AGREEMENT"
        or row.origin != "SYSTEM_GENERATED"
        or row.template_version != contract.template_version
        or documents.credit_source_hash(content) != contract.content_hash
    ):
        raise AppError(409, "CONTRACT_TAMPERED", "Файл не соответствует договору")
    _verify_signed_hash(session, contract, row.sha256)
    return content, row.mime, row.sha256


def signing_hash(session: Session, contract: Contract) -> str:
    return document_content(session, contract)[2]


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
            Offer.application_id == Contract.application_id,
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
    signing_hash(session, contract)
    verify_variant(contract, variant)
    return SignedTerms(
        product_code=variant.product_code,
        amount_rub=variant.amount_rub,
        term_months=variant.term_months,
        rate_percent=variant.rate_percent,
        contract_number=contract.number,
        contract_uid=contract.contract_uid,
        signed_at=contract.signed_at,
    )
