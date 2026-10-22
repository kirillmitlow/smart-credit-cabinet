"""Ручки предложения, договора и подписи (T-340, T-341, T-263, 50-07). Роутер тонкий (R6)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.modules.offers import service, signing, views
from app.modules.offers.schemas import (
    AcceptedOut,
    AcceptIn,
    ContractOut,
    DeclinedOut,
    OfferOut,
    PassedOut,
    SignChallengeOut,
    SignConfirmIn,
    ContractSignedOut,
    SignStartIn,
)
from app.shared import db
from app.shared.errors import AppError
from app.shared.settings import get_settings

router = APIRouter(tags=["предложение и договор"])


# ---------------------------------------------------------------- предложение


def _get_offer(principal: auth.Principal, application_id: UUID) -> OfferOut:
    with db.transaction() as session:
        offer, _ = service.current_for(session, principal, application_id)
        return views.offer_out(session, offer)


@router.get(
    "/applications/{application_id}/offer",
    operation_id="getApplicationOffer",
    summary="Предложение банка по заявке: варианты, платёж, переплата, срок действия",
    response_model=OfferOut,
    response_model_by_alias=True,
)
async def get_offer(application_id: UUID, principal: auth.ClientPrincipal) -> OfferOut:
    return await run_in_threadpool(_get_offer, principal, application_id)


def _accept(principal: auth.Principal, offer_id: UUID, body: AcceptIn) -> AcceptedOut:
    with db.transaction() as session:
        offer, application, contract = service.accept(session, principal, offer_id, body.variant_id)
        return AcceptedOut(
            application_status=application.status,
            offer=views.offer_out(session, offer),
            contract=views.contract_out(session, principal, contract, application),
        )


@router.post(
    "/offers/{offer_id}/accept",
    operation_id="acceptOffer",
    summary="Принять предложение (выбранный вариант): заявка → OFFER_ACCEPTED, готовится договор",
    response_model=AcceptedOut,
    response_model_by_alias=True,
)
async def accept_offer(
    offer_id: UUID, principal: auth.ClientPrincipal, body: AcceptIn | None = None
) -> AcceptedOut:
    return await run_in_threadpool(_accept, principal, offer_id, body or AcceptIn())


def _decline(principal: auth.Principal, offer_id: UUID) -> DeclinedOut:
    with db.transaction() as session:
        offer, application = service.decline(session, principal, offer_id)
        return DeclinedOut(
            application_status=application.status, offer=views.offer_out(session, offer)
        )


@router.post(
    "/offers/{offer_id}/decline",
    operation_id="declineOffer",
    summary="Отказаться от предложения: заявка → WITHDRAWN",
    response_model=DeclinedOut,
    response_model_by_alias=True,
)
async def decline_offer(offer_id: UUID, principal: auth.ClientPrincipal) -> DeclinedOut:
    return await run_in_threadpool(_decline, principal, offer_id)


# ---------------------------------------------------------------- договор


def _get_contract(principal: auth.Principal, contract_id: UUID) -> ContractOut:
    with db.transaction() as session:
        contract, application = signing.contract_for(session, principal, contract_id)
        return views.contract_out(session, principal, contract, application)


@router.get(
    "/contracts/{contract_id}",
    operation_id="getContract",
    summary="Договор: номер, УИд, хеш документа, кто подписал и сколько подписей нужно",
    response_model=ContractOut,
    response_model_by_alias=True,
)
async def get_contract(contract_id: UUID, principal: auth.ClientPrincipal) -> ContractOut:
    return await run_in_threadpool(_get_contract, principal, contract_id)


def _document(principal: auth.Principal, contract_id: UUID) -> Response:
    with db.transaction() as session:
        contract, _ = signing.contract_for(session, principal, contract_id)
        return Response(
            content=contract.body.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={
                "X-Content-SHA256": contract.content_hash,
                "Content-Disposition": f'inline; filename="contract-{contract.contract_uid}.json"',
            },
        )


@router.get(
    "/contracts/{contract_id}/document",
    operation_id="getContractDocument",
    summary="Сохранённый текст договора (подписывается именно он); хеш — в X-Content-SHA256",
)
async def get_contract_document(contract_id: UUID, principal: auth.ClientPrincipal) -> Response:
    return await run_in_threadpool(_document, principal, contract_id)


def _pass(principal: auth.Principal, contract_id: UUID) -> PassedOut:
    with db.transaction() as session:
        contract, at, repeated = signing.pass_to_director(session, principal, contract_id)
        return PassedOut(contract_id=contract.id, requested_at=at, repeated=repeated)


@router.post(
    "/contracts/{contract_id}/request-signature",
    operation_id="requestContractSignature",
    summary="Передать руководителю на подпись (сотрудник; D-014)",
    response_model=PassedOut,
    response_model_by_alias=True,
)
async def request_signature(contract_id: UUID, principal: auth.ClientPrincipal) -> PassedOut:
    return await run_in_threadpool(_pass, principal, contract_id)


def _start(principal: auth.Principal, contract_id: UUID, body: SignStartIn) -> SignChallengeOut:
    if not body.agree:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Нужна галочка «Ознакомлен, согласен»",
            errors=[{"loc": ["body", "agree"], "msg": "Must be true"}],
        )
    with db.transaction() as session:
        challenge = signing.request_code(
            session, principal, contract_id, accept_pep_rules=body.accept_pep_rules
        )
    return SignChallengeOut(
        request_id=challenge.request_id,
        expires_in_seconds=challenge.expires_in,
        demo_code=challenge.code if get_settings().demo_mode else None,
    )


@router.post(
    "/contracts/{contract_id}/sign/request",
    operation_id="requestContractSigningCode",
    summary="Галочка поставлена: выпустить код подписи договора (только руководитель)",
    response_model=SignChallengeOut,
    response_model_by_alias=True,
)
async def request_signing_code(
    contract_id: UUID, body: SignStartIn, principal: auth.ClientPrincipal
) -> SignChallengeOut:
    return await run_in_threadpool(_start, principal, contract_id, body)


def _sign(principal: auth.Principal, contract_id: UUID, body: SignConfirmIn) -> ContractSignedOut:
    with db.transaction() as session:
        contract, application, just_signed = signing.sign(
            session, principal, contract_id, body.request_id, body.code
        )
        return ContractSignedOut(
            contract=views.contract_out(session, principal, contract, application),
            just_signed=just_signed,
        )


@router.post(
    "/contracts/{contract_id}/sign",
    operation_id="signContract",
    summary="Ввести код: договор подписан; когда подписи собраны, заявка → SIGNED и стартует выдача",
    response_model=ContractSignedOut,
    response_model_by_alias=True,
)
async def sign_contract(
    contract_id: UUID, body: SignConfirmIn, principal: auth.ClientPrincipal
) -> ContractSignedOut:
    return await run_in_threadpool(_sign, principal, contract_id, body)
