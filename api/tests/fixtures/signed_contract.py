"""Подписанный договор для проверок выдачи, которые не тестируют вход и одноразовый код."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import offers
from app.modules.applications import Application
from app.modules.offers.contracts import create_contract
from app.modules.pipeline.models import Decision
from app.shared import clock


def add_signed_contract(
    session: Session,
    application: Application,
    *,
    amount_rub: int = 500_000,
    term_months: int = 12,
    rate_percent: Decimal = Decimal("24"),
    product_code: str = "EXPRESS",
) -> offers.Contract:
    session.flush()
    decision_id = session.scalars(
        select(Decision.id).where(Decision.application_id == application.id)
    ).one()
    offer = offers.create_offer(
        session,
        application,
        decision_id=decision_id,
        kind="AS_REQUESTED",
        variants=[
            offers.VariantDraft(
                kind="AS_REQUESTED",
                label="Согласованные условия",
                product_code=product_code,
                amount_rub=amount_rub,
                term_months=term_months,
                annual_rate=rate_percent / 100,
            )
        ],
    )
    variant = session.scalars(
        select(offers.OfferVariant).where(offers.OfferVariant.offer_id == offer.id)
    ).one()
    offer.status = "ACCEPTED"
    offer.accepted_variant_id = variant.id
    contract = create_contract(session, application, offer, variant)
    contract.status = "SIGNED"
    contract.signed_at = clock.now()
    session.flush()
    return contract
