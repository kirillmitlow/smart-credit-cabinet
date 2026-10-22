"""Решение для клиента простым языком (T-259, 30-12, 60-03, 50-07).

Клиент видит исход, условия, причины и «что можно сделать». Баллов, грейда, PD, DSCR, снимков
источников и внутренних кодов в ответе нет. Тексты причин не пересобираются: берутся из снимка
решения (`decisions.explain`), поэтому через месяц клиент видит то же самое (Q-113). Причина
`AML_LIST` наружу не раскрывается ни кодом, ни текстом.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.modules import auth, offers
from app.modules.applications import get_for
from app.modules.pipeline.models import Decision
from app.shared import db
from app.shared.errors import not_found

HEADLINES = {
    "APPROVED": "Одобрено на запрошенных условиях",
    "COUNTER_OFFER": "Так, как вы просили, не получится. Вот что мы можем",
    "NEEDS_INFO": "Нужна дополнительная информация",
    "MANUAL_REVIEW": "Заявку смотрит специалист. Обычно до 1 рабочего дня",
    "REJECTED": "Сейчас одобрить не можем",
}
# Код причины, который клиенту не раскрываем; вместо него общий (30-12: AML_LIST)
HIDDEN_CODES = frozenset({"AML_LIST"})
GENERIC_CODE = "BANK_POLICY"
_PERCENT = Decimal(100)

router = APIRouter(prefix="/applications", tags=["решение"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DecisionReasonOut(Camel):
    code: str
    text: str
    action: str


class RatePartOut(Camel):
    label: str
    percent: offers.Percent


class ClientDecisionOut(Camel):
    """Клиентская модель. Полная модель для андеррайтера — отдельная (бэк-офис)."""

    application_id: UUID
    application_status: str
    decision_id: UUID
    outcome: str
    headline: str
    decided_at: datetime
    terms: offers.VariantOut | None = Field(
        description="Условия при одобрении «как просили»: сумма, срок, ставка, платёж, переплата"
    )
    rate_breakdown: list[RatePartOut] = Field(
        description="Из чего складывается ставка; пусто, если ставки нет"
    )
    reasons: list[DecisionReasonOut]
    next_steps: list[str] = Field(description="Что можно сделать, без повторов")
    what_helped: list[str] = Field(description="До двух сильных сторон при одобрении")
    what_affected: list[str] = Field(description="До трёх слабых мест при отказе и встречном")
    offer: offers.OfferOut | None = Field(
        description="Предложение банка (`APPROVED`, `COUNTER_OFFER`); у встречного без вариантов "
        "`variantsStatus = PENDING`"
    )


def _percent(value: Any) -> Decimal:
    return Decimal(str(value)) * _PERCENT


def _rate_breakdown(explain: dict[str, Any]) -> list[RatePartOut]:
    parts = (explain.get("numbers") or {}).get("rate_breakdown")
    if not parts:
        return []
    key, spread = _percent(parts["key_rate"]), _percent(parts["spread"])
    risk = _percent(parts["expected_loss"])
    costs = _percent(parts["expenses"]) + _percent(parts["capital_charge"])
    rounding = _percent(parts["rate"]) - _percent(parts["raw_rate"])
    lines = [
        ("Ключевая ставка Банка России", key),
        ("Базовая маржа банка", spread),
        ("Надбавка за риск", risk),
        ("Расходы банка и резерв капитала", costs),
        ("Округление", rounding),
    ]
    return [RatePartOut(label=label, percent=value.normalize()) for label, value in lines if value]


def _reasons(explain: dict[str, Any]) -> list[DecisionReasonOut]:
    out: list[DecisionReasonOut] = []
    for item in explain.get("explanations") or []:
        if not item.get("client"):  # служебные коды (например, потолок грейда) клиенту не нужны
            continue
        code = GENERIC_CODE if item["code"] in HIDDEN_CODES else item["code"]
        out.append(DecisionReasonOut(code=code, text=item["client"], action=item.get("action") or ""))
    return out


def latest_decision(session: Session, application_id: UUID) -> Decision | None:
    return session.scalars(
        select(Decision)
        .where(Decision.application_id == application_id)
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(1)
    ).first()


def client_decision(
    session: Session, principal: auth.Principal, application_id: UUID
) -> ClientDecisionOut:
    application = get_for(session, principal, application_id)
    member = principal.membership(application.company_id)
    if member is None or member.role == "GUARANTOR":  # поручитель решения по компании не видит
        raise not_found("Заявка")
    decision = latest_decision(session, application.id)
    if decision is None:
        raise not_found("Решение")
    explain = decision.explain
    reasons = _reasons(explain)
    factors = explain.get("clientFactors") or {}
    offer_row = offers.current_offer(session, application.id)
    offer = (
        offers.offer_out(session, offer_row)
        if offer_row is not None and offer_row.decision_id == decision.id
        else None
    )
    terms = (
        offer.variants[0]
        if offer is not None and decision.outcome == "APPROVED" and offer.variants
        else None
    )
    steps: list[str] = []
    for reason in reasons:
        if reason.action and reason.action not in steps:
            steps.append(reason.action)
    return ClientDecisionOut(
        application_id=application.id,
        application_status=application.status,
        decision_id=decision.id,
        outcome=decision.outcome,
        headline=HEADLINES[decision.outcome],
        decided_at=decision.created_at,
        terms=terms,
        rate_breakdown=_rate_breakdown(explain) if terms is not None else [],
        reasons=reasons,
        next_steps=steps,
        what_helped=list(factors.get("whatHelped", [])) if decision.outcome == "APPROVED" else [],
        what_affected=list(factors.get("whatAffected", []))
        if decision.outcome in ("REJECTED", "COUNTER_OFFER", "NEEDS_INFO")
        else [],
        offer=offer,
    )


def _get(principal: auth.Principal, application_id: UUID) -> ClientDecisionOut:
    with db.transaction() as session:
        return client_decision(session, principal, application_id)


@router.get(
    "/{application_id}/decision",
    operation_id="getApplicationDecision",
    summary="Решение простым языком: исход, условия, причины и что можно сделать",
    response_model=ClientDecisionOut,
    response_model_by_alias=True,
)
async def get_decision(application_id: UUID, principal: auth.ClientPrincipal) -> ClientDecisionOut:
    return await run_in_threadpool(_get, principal, application_id)
