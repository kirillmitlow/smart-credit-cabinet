"""Ручки согласий заявки (T-260, T-261, 50-07): список с текстами, галочки → код, код → подпись."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from app.modules import audit, auth
from app.modules.applications import consent_texts as texts
from app.modules.applications import consents, service
from app.modules.applications.models import Application, Consent
from app.shared import db
from app.shared.settings import get_settings

router = APIRouter(prefix="/applications", tags=["согласия"])

Kind = Literal["BKI", "TURNOVER", "PERSONAL_DATA"]
Inn = Annotated[str, Field(pattern=r"^\d{10}$|^\d{12}$")]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ConsentRef(Camel):
    kind: Kind
    subject_inn: Inn


class ConsentItemOut(Camel):
    kind: str
    subject_inn: str
    subject_name: str
    subject_type: str
    role: str
    status: Literal["PENDING", "SIGNED", "EXPIRED"]
    can_sign: bool
    text_version: str
    text_hash: str
    text: str
    signed_at: datetime | None
    valid_until: date | None
    consent_id: str | None


class PepRulesOut(Camel):
    version: str
    text_hash: str
    text: str
    accepted: bool


class ConsentsOut(Camel):
    application_id: UUID
    pep_rules: PepRulesOut
    items: list[ConsentItemOut]
    all_signed: bool


class SignRequest(Camel):
    items: list[ConsentRef] = Field(min_length=1, max_length=20)
    accept_pep_rules: bool = Field(
        default=False, description="Галочка «Принимаю правила простой подписи»; нужна один раз"
    )


class SignChallenge(Camel):
    request_id: str
    expires_in_seconds: int
    demo_code: str | None = Field(default=None, description="Только в демо-режиме: код вместо SMS")
    items: list[ConsentRef]


class SignConfirm(Camel):
    request_id: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^\d{6}$")
    items: list[ConsentRef] = Field(min_length=1, max_length=20)


class SignedOut(Camel):
    application_id: UUID
    signed: list[ConsentItemOut]
    all_signed: bool


def _item(
    application: Application, state: consents.ItemState, override: Consent | None = None
) -> ConsentItemOut:
    required = state.required
    consent = override or state.consent
    text = (
        texts.available().get(consent.text_version) if consent is not None else None
    ) or texts.current_for_kind(required.kind)
    return ConsentItemOut(
        kind=required.kind,
        subject_inn=required.subject_inn,
        subject_name=required.name,
        subject_type=required.subject_type,
        role=required.role,
        status="SIGNED" if override is not None else state.status,
        can_sign=state.can_sign,
        text_version=text.key,
        text_hash=text.sha256,
        text=consents.render_text(application, required, text),
        signed_at=consent.signed_at if consent else None,
        valid_until=consent.valid_until if consent else None,
        consent_id=consents.consent_id_of(consent) if consent else None,
    )


def _view(principal: auth.Principal, application_id: UUID) -> ConsentsOut:
    with db.transaction() as session:
        application = service.get_for(session, principal, application_id)
        states = [
            s
            for s in consents.item_states(session, principal, application)
            if consents.visible_to(principal, application, s)
        ]
        rules = texts.pep_rules()
        return ConsentsOut(
            application_id=application.id,
            pep_rules=PepRulesOut(
                version=rules.key,
                text_hash=rules.sha256,
                text=rules.render(bank_name=consents.BANK_NAME),
                accepted=audit.exists(session, consents.PEP_ACCEPTED, actor_id=principal.user_id),
            ),
            items=[_item(application, s) for s in states],
            all_signed=all(s.status == "SIGNED" for s in states),
        )


@router.get(
    "/{application_id}/consents",
    operation_id="listApplicationConsents",
    summary="Какие согласия нужны, их тексты, кто может подписать и что уже подписано",
    response_model=ConsentsOut,
    response_model_by_alias=True,
)
async def list_consents(application_id: UUID, principal: auth.ClientPrincipal) -> ConsentsOut:
    return await run_in_threadpool(_view, principal, application_id)


def _request(principal: auth.Principal, application_id: UUID, body: SignRequest) -> SignChallenge:
    with db.transaction() as session:
        application = service.get_for(session, principal, application_id)
        challenge = consents.request_signing(
            session,
            principal,
            application,
            [(i.kind, i.subject_inn) for i in body.items],
            accept_pep_rules=body.accept_pep_rules,
        )
    return SignChallenge(
        request_id=challenge.request_id,
        expires_in_seconds=challenge.expires_in,
        demo_code=challenge.code if get_settings().demo_mode else None,
        items=[ConsentRef(kind=r.kind, subject_inn=r.subject_inn) for r in challenge.items],
    )


@router.post(
    "/{application_id}/consents",
    operation_id="requestConsentSigning",
    summary="Галочки поставлены: проверить полномочия и выпустить один код на пакет согласий",
    response_model=SignChallenge,
    response_model_by_alias=True,
)
async def request_signing(
    application_id: UUID, body: SignRequest, principal: auth.ClientPrincipal
) -> SignChallenge:
    return await run_in_threadpool(_request, principal, application_id, body)


def _confirm(principal: auth.Principal, application_id: UUID, body: SignConfirm) -> SignedOut:
    with db.transaction() as session:
        application = service.get_for(session, principal, application_id)
        rows = consents.sign_bundle(
            session,
            principal,
            application,
            body.request_id,
            body.code,
            [(i.kind, i.subject_inn) for i in body.items],
        )
        by_key = {(c.kind, c.subject_inn): c for c in rows}
        states = [
            s
            for s in consents.item_states(session, principal, application)
            if consents.visible_to(principal, application, s)
        ]
        return SignedOut(
            application_id=application.id,
            signed=[
                _item(application, s, by_key[s.required.key])
                for s in states
                if s.required.key in by_key
            ],
            all_signed=all(s.status == "SIGNED" for s in states),
        )


@router.post(
    "/{application_id}/consents/sign",
    operation_id="signConsentBundle",
    summary="Ввести код: весь пакет согласий человека подписан",
    response_model=SignedOut,
    response_model_by_alias=True,
)
async def sign(
    application_id: UUID, body: SignConfirm, principal: auth.ClientPrincipal
) -> SignedOut:
    return await run_in_threadpool(_confirm, principal, application_id, body)
