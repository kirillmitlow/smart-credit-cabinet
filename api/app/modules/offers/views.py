"""Сборка клиентских моделей предложения и договора из строк базы."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth
from app.modules.applications import Application
from app.modules.offers import contracts, signing, terms
from app.modules.offers.models import Contract, Offer, OfferVariant
from app.modules.offers.schemas import (
    ContractOut,
    OfferOut,
    ProgressOut,
    ScheduleRowOut,
    SignerOut,
    VariantOut,
)
from app.modules.offers.service import variants_of
from app.shared.errors import not_found


def variant_out(variant: OfferVariant) -> VariantOut:
    rate = Decimal(variant.rate_percent) / 100
    card = terms.loan_terms(variant.product_code, variant.amount_rub, rate, variant.term_months)
    return VariantOut(
        id=variant.id,
        kind=variant.kind,
        label=variant.label,
        product_code=variant.product_code,
        product_title=terms.product_title(variant.product_code),
        amount_rub=variant.amount_rub,
        term_months=variant.term_months,
        rate_percent=Decimal(variant.rate_percent).normalize(),
        payment_rub=variant.payment_rub,
        last_payment_rub=variant.last_payment_rub,
        overpayment_rub=variant.overpayment_rub,
        collateral_required=variant.collateral_required,
        recommended=variant.recommended,
        what_changed=variant.what_changed,
        note=variant.note,
        schedule_preview=[
            ScheduleRowOut(
                number=row.number,
                payment_rub=row.payment,
                principal_rub=row.principal,
                interest_rub=row.interest,
                balance_rub=row.balance,
            )
            for row in terms.preview(card.schedule)
        ],
    )


def offer_out(session: Session, offer: Offer) -> OfferOut:
    contract = session.scalars(
        select(Contract.id).where(Contract.offer_id == offer.id, Contract.status != "CANCELLED")
    ).first()
    return OfferOut(
        id=offer.id,
        application_id=offer.application_id,
        kind=offer.kind,
        status=offer.status,
        variants_status=offer.variants_status,
        expires_at=offer.expires_at,
        accepted_variant_id=offer.accepted_variant_id,
        contract_id=contract,
        variants=[variant_out(v) for v in variants_of(session, offer.id)],
    )


def contract_out(
    session: Session, principal: auth.Principal, contract: Contract, application: Application
) -> ContractOut:
    variant = session.get(OfferVariant, contract.variant_id)
    if variant is None:
        raise not_found("Вариант")
    contracts.verify_integrity(contract)
    contracts.verify_variant(contract, variant)
    required = signing.signers(session, contract, application)
    member = principal.membership(application.company_id)
    open_for_signing = contract.status == "READY" and application.status == "OFFER_ACCEPTED"
    return ContractOut(
        id=contract.id,
        application_id=application.id,
        application_status=application.status,
        contract_uid=contract.contract_uid,
        number=contract.number,
        status=contract.status,
        content_hash=contracts.signing_hash(session, contract),
        template_version=contract.template_version,
        created_at=contract.created_at,
        signed_at=contract.signed_at,
        product_code=variant.product_code,
        amount_rub=variant.amount_rub,
        term_months=variant.term_months,
        rate_percent=Decimal(variant.rate_percent).normalize(),
        payment_rub=variant.payment_rub,
        signers=[
            SignerOut(
                role=s.role,
                name=s.name,
                signed=s.signature is not None,
                signed_at=s.signature.signed_at if s.signature else None,
            )
            for s in required
        ],
        progress=ProgressOut(
            signed=len([s for s in required if s.signature is not None]), required=len(required)
        ),
        can_sign=open_for_signing and signing.can_sign(principal, application, required),
        can_pass_to_director=open_for_signing
        and member is not None
        and member.role not in ("DIRECTOR", "GUARANTOR"),
    )
