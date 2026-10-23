"""Что делаем после сохранения решения (T-275): предложение, задачи клиенту, outbox.

Вызывается внутри транзакции шага 6. Предложение создаёт модуль `offers` (T-340); задачи клиенту
и outbox — точки подключения для других задач.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.modules import offers
from app.modules.applications import Application
from app.modules.decisioning import DecisionInput, DecisionResult, UnderwriterTerms
from app.modules.decisioning.types import Outcome, Variant
from app.modules.offers import VariantDraft
from app.modules.pipeline.models import Decision

log = structlog.get_logger("app.pipeline.hooks")

OFFER_OUTCOMES = frozenset({Outcome.APPROVED, Outcome.COUNTER_OFFER})
# Подписи карточек (30-10, вариант Г); по виду варианта из ядра
_OTHER = "Другой продукт или с залогом"
_LABELS = {
    "CONDITIONAL_SECURITY": "С поручительством владельца или залогом",
    "LONGER_TERM": "Ваша сумма, дольше срок",
    "OTHER_TERM": "Ваша сумма, другой срок",
    "LESS_AMOUNT": "Ваш срок, меньше сумма",
    "OTHER_PRODUCT": _OTHER,
    "WITH_SECURITY": _OTHER,
}


def _changes(inp: DecisionInput, variant: Variant) -> dict[str, Any]:
    """Чем вариант отличается от запроса клиента и что нужно от клиента (`requirements`)."""
    asked = inp.application
    changed: dict[str, Any] = {}
    if variant.product != asked.product:
        changed["productCode"] = {"from": asked.product.value, "to": variant.product.value}
    if variant.amount_rub != asked.amount_rub:
        changed["amountRub"] = {"from": asked.amount_rub, "to": variant.amount_rub}
    if variant.term_months != asked.term_months:
        changed["termMonths"] = {"from": asked.term_months, "to": variant.term_months}
    if variant.security_required:
        changed["security"] = True
    if variant.requirements:  # «что нужно от вас» по карточке
        changed["requirements"] = list(variant.requirements)
    return changed


def _drafts(inp: DecisionInput, result: DecisionResult) -> list[VariantDraft]:
    if result.outcome == Outcome.APPROVED:
        asked = inp.application
        rate = result.numbers.rate
        if rate is None:  # у одобрения ставка есть всегда; защита от битого результата ядра
            raise ValueError("APPROVED без ставки")
        return [
            VariantDraft(
                kind="AS_REQUESTED",
                label="Как вы просили",
                product_code=asked.product.value,
                amount_rub=asked.amount_rub,
                term_months=asked.term_months,
                annual_rate=rate,
                recommended=True,
            )
        ]
    return [
        VariantDraft(
            kind=v.kind,
            label=_LABELS.get(v.kind, "Другие условия"),
            product_code=v.product.value,
            amount_rub=v.amount_rub,
            term_months=v.term_months,
            annual_rate=v.rate,
            collateral_required=v.security_required,
            recommended=v.recommended,
            what_changed=_changes(inp, v),
            note=v.note,
        )
        for v in result.variants
    ]


def create_offer(
    session: Session,
    application: Application,
    decision: Decision,
    inp: DecisionInput,
    result: DecisionResult,
) -> None:
    """Предложение по решению в той же транзакции (50-05, шаг 6, T-340).

    `APPROVED` — один вариант «как просили». `COUNTER_OFFER` — карточки оптимизатора (T-297)
    или условное встречное; вариантов в норме не меньше одного. `PENDING` остался запасным
    состоянием на случай пустого набора: принять такое предложение нельзя.
    """
    drafts = _drafts(inp, result)
    counter = result.outcome == Outcome.COUNTER_OFFER
    offers.create_offer(
        session,
        application,
        decision_id=decision.id,
        kind="COUNTER" if counter else "AS_REQUESTED",
        variants=drafts,
        variants_status="PENDING" if counter and not drafts else "READY",
    )


def after_decision(
    session: Session,
    application: Application,
    decision: Decision,
    inp: DecisionInput,
    result: DecisionResult,
) -> None:
    if result.outcome in OFFER_OUTCOMES:
        create_offer(session, application, decision, inp, result)
    # TODO(T-278): outbox — сообщение APPLICATION_DECIDED в БКИ, ключ уведомлений клиенту (та же транзакция)
    # TODO(T-2xx, 20-03): задача клиенту при NEEDS_INFO (`REVENUE_UNKNOWN`, `DATA_INCOMPLETE`)


def create_underwriter_offer(
    session: Session,
    application: Application,
    decision: Decision,
    inp: DecisionInput,
    outcome: Outcome,
    terms: UnderwriterTerms,
) -> None:
    """Предложение по ручному решению: так же, как после решения ядра (T-362).

    `APPROVED` — «как просили» по условиям с введённой ставкой; `COUNTER_OFFER` — одна карточка
    специалиста с тем, чем она отличается от запроса.
    """
    if terms.rate is None:
        raise ValueError("у решения андеррайтера ставка должна быть определена")
    asked = inp.application
    counter = outcome == Outcome.COUNTER_OFFER
    changed: dict[str, Any] = {}
    if terms.product != asked.product:
        changed["productCode"] = {"from": asked.product.value, "to": terms.product.value}
    if terms.amount_rub != asked.amount_rub:
        changed["amountRub"] = {"from": asked.amount_rub, "to": terms.amount_rub}
    if terms.term_months != asked.term_months:
        changed["termMonths"] = {"from": asked.term_months, "to": terms.term_months}
    draft = VariantDraft(
        kind="UNDERWRITER" if counter else "AS_REQUESTED",
        label="Предложение специалиста банка" if counter else "Как вы просили",
        product_code=terms.product.value,
        amount_rub=terms.amount_rub,
        term_months=terms.term_months,
        annual_rate=terms.rate,
        recommended=True,
        what_changed=changed if counter else {},
    )
    offers.create_offer(
        session,
        application,
        decision_id=decision.id,
        kind="COUNTER" if counter else "AS_REQUESTED",
        variants=[draft],
        variants_status="READY",
    )
