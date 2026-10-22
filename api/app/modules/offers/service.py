"""Предложение банка: создание по решению, принятие и отказ (T-340, 20-04, 20-02, D-072).

Транзакцию держит вызывающий (R7). Предложение создаёт конвейер в той же транзакции, что и
решение (50-05, шаг 6): сюда приходят уже готовые варианты, модуль `pipeline` ему не нужен.
Принятие и отказ идемпотентны: повтор того же действия возвращает прежний результат и не
создаёт второго перехода (двойной клик).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth, catalog
from app.modules.applications import Actor, Application, Status, get_for, record_event, transition
from app.modules.offers import contracts, terms
from app.modules.offers.models import Contract, Offer, OfferVariant
from app.shared import clock
from app.shared.errors import AppError, not_found

AS_REQUESTED_LABEL = "Как вы просили"


@dataclass(frozen=True, slots=True)
class VariantDraft:
    """Вариант до записи. `annual_rate` — доля (0,215); платёж и переплату считает `terms`."""

    kind: str
    label: str
    product_code: str
    amount_rub: int
    term_months: int
    annual_rate: Decimal
    collateral_required: bool = False
    recommended: bool = False
    what_changed: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def create_offer(
    session: Session,
    application: Application,
    *,
    decision_id: UUID,
    kind: str,
    variants: list[VariantDraft],
    variants_status: str = "READY",
) -> Offer:
    """Предложение по решению с вариантами (до трёх). Повтор для того же решения ничего не создаёт."""
    existing = session.scalars(select(Offer).where(Offer.decision_id == decision_id)).first()
    if existing is not None:
        return existing
    now = clock.now()
    # Новое предложение заменяет прежнее открытое (решение пересмотрели)
    for old in session.scalars(
        select(Offer).where(Offer.application_id == application.id, Offer.status == "OPEN")
    ):
        old.status = "EXPIRED"
        old.closed_at = now
    days = catalog.get_policy().timing.offer_valid_days.value
    offer = Offer(
        application_id=application.id,
        decision_id=decision_id,
        kind=kind,
        status="OPEN",
        variants_status=variants_status,
        expires_at=now + timedelta(days=days),
    )
    session.add(offer)
    session.flush()
    for position, draft in enumerate(variants[:3]):
        card = terms.loan_terms(
            draft.product_code, draft.amount_rub, draft.annual_rate, draft.term_months
        )
        session.add(
            OfferVariant(
                offer_id=offer.id,
                position=position,
                kind=draft.kind,
                label=draft.label,
                product_code=draft.product_code,
                amount_rub=draft.amount_rub,
                term_months=draft.term_months,
                rate_percent=draft.annual_rate * 100,
                payment_rub=card.payment_rub,
                last_payment_rub=card.last_payment_rub,
                overpayment_rub=card.overpayment_rub,
                collateral_required=draft.collateral_required,
                recommended=draft.recommended,
                what_changed=draft.what_changed,
                note=draft.note,
            )
        )
    session.flush()
    record_event(
        session,
        application,
        "STEP",
        actor_type=Actor.SYSTEM,
        step_code="OFFER_CREATED",
        payload={
            "offerId": str(offer.id),
            "kind": kind,
            "variants": len(variants[:3]),
            "variantsStatus": variants_status,
        },
    )
    return offer


# ---------------------------------------------------------------- чтение


def variants_of(session: Session, offer_id: UUID) -> list[OfferVariant]:
    return list(
        session.scalars(
            select(OfferVariant)
            .where(OfferVariant.offer_id == offer_id)
            .order_by(OfferVariant.position)
        )
    )


def current_offer(session: Session, application_id: UUID) -> Offer | None:
    """Последнее предложение заявки."""
    return session.scalars(
        select(Offer)
        .where(Offer.application_id == application_id)
        .order_by(Offer.created_at.desc(), Offer.id.desc())
        .limit(1)
    ).first()


def _can_view(principal: auth.Principal, application: Application) -> bool:
    member = principal.membership(application.company_id)
    return member is not None and member.role != "GUARANTOR"


def application_for(
    session: Session, principal: auth.Principal, application_id: UUID, *, lock: bool = False
) -> Application:
    """Заявка клиента; чужая, несуществующая и «не для поручителя» неразличимы: 404 (R11)."""
    application = get_for(session, principal, application_id)
    if not _can_view(principal, application):
        raise not_found("Заявка")
    if lock:
        session.refresh(application, with_for_update=True)
    return application


def offer_for(
    session: Session, principal: auth.Principal, offer_id: UUID, *, lock: bool = False
) -> tuple[Offer, Application]:
    offer = session.get(Offer, offer_id)
    if offer is None:
        raise not_found("Предложение")
    try:
        application = application_for(session, principal, offer.application_id, lock=lock)
    except AppError as exc:
        raise not_found("Предложение") from exc
    if lock:
        session.refresh(offer, with_for_update=True)
    return offer, application


def current_for(
    session: Session, principal: auth.Principal, application_id: UUID
) -> tuple[Offer, Application]:
    application = application_for(session, principal, application_id)
    offer = current_offer(session, application.id)
    if offer is None:
        raise not_found("Предложение")
    return offer, application


# ---------------------------------------------------------------- принятие и отказ


def _pick_variant(
    offer: Offer, variants: list[OfferVariant], variant_id: UUID | None
) -> OfferVariant:
    if offer.variants_status == "PENDING" or not variants:
        raise AppError(
            409,
            "OFFER_VARIANTS_PENDING",
            "Варианты встречного предложения ещё готовятся",
        )
    if variant_id is None:
        if len(variants) == 1:
            return variants[0]
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Выберите вариант",
            errors=[{"loc": ["body", "variantId"], "msg": "Field required"}],
        )
    chosen = next((v for v in variants if v.id == variant_id), None)
    if chosen is None:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Такого варианта в предложении нет",
            errors=[{"loc": ["body", "variantId"], "msg": "Unknown variant"}],
        )
    return chosen


def accept(
    session: Session,
    principal: auth.Principal,
    offer_id: UUID,
    variant_id: UUID | None,
) -> tuple[Offer, Application, Contract]:
    """`APPROVED | COUNTER_OFFER → OFFER_ACCEPTED` и договор по выбранному варианту."""
    offer, application = offer_for(session, principal, offer_id, lock=True)
    variants = variants_of(session, offer.id)
    if offer.status == "ACCEPTED":  # двойной клик: тот же результат без второго перехода
        chosen = _pick_variant(offer, variants, variant_id or offer.accepted_variant_id)
        if chosen.id != offer.accepted_variant_id:
            raise AppError(
                409, "OFFER_ALREADY_ACCEPTED", "Предложение уже принято с другим вариантом"
            )
        return offer, application, contracts.live_contract(session, application.id)
    if offer.status != "OPEN":
        raise AppError(
            409, "OFFER_NOT_OPEN", "Предложение закрыто", errors=[{"status": offer.status}]
        )
    if clock.now() > offer.expires_at:
        raise AppError(409, "OFFER_EXPIRED", "Срок предложения истёк")
    chosen = _pick_variant(offer, variants, variant_id)
    if chosen.collateral_required:
        # Обеспечение (залог, поручитель) ещё не оформляется в заявке (T-257): принять такой вариант
        # нельзя, пока клиент его не добавил; после T-257 здесь будет COUNTER_OFFER → CHECKING
        raise AppError(
            409,
            "SECURITY_REQUIRED",
            "Для этого варианта нужен залог или поручитель",
            errors=[{"variantId": str(chosen.id)}],
        )
    transition(
        session,
        application,
        Status.OFFER_ACCEPTED,
        actor=Actor.CLIENT,
        actor_id=principal.user_id,
        payload={"offerId": str(offer.id), "variantId": str(chosen.id)},
    )
    now = clock.now()
    offer.status = "ACCEPTED"
    offer.accepted_variant_id = chosen.id
    offer.accepted_by = principal.user_id
    offer.accepted_at = now
    offer.closed_at = now
    session.flush()
    contract = contracts.create_contract(session, application, offer, chosen)
    return offer, application, contract


def decline(
    session: Session, principal: auth.Principal, offer_id: UUID
) -> tuple[Offer, Application]:
    """Отказ от предложения: заявка закрывается как отозванная (`WITHDRAWN`)."""
    offer, application = offer_for(session, principal, offer_id, lock=True)
    if offer.status == "DECLINED":
        return offer, application
    if offer.status == "EXPIRED":
        raise AppError(
            409, "OFFER_NOT_OPEN", "Предложение закрыто", errors=[{"status": offer.status}]
        )
    transition(
        session,
        application,
        Status.WITHDRAWN,
        actor=Actor.CLIENT,
        actor_id=principal.user_id,
        reason_code="OFFER_DECLINED",
        payload={"offerId": str(offer.id)},
    )
    if offer.status == "ACCEPTED":  # отказ после принятия, до подписи: договор не нужен
        contracts.cancel_live(session, application.id)
    offer.status = "DECLINED"
    offer.closed_at = clock.now()
    session.flush()
    return offer, application
