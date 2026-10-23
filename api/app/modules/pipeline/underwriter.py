"""Ручное решение андеррайтера: проверка и неизменяемый снимок (T-362, T-364, 30-11, D-010, D-030).

Вызывающий (backoffice) держит транзакцию (R7). Один вызов `record_underwriter_decision` делает всё
в этой транзакции: проверяет версию заявки, заново считает условия ядром, пишет снимок
`source = UNDERWRITER` со ссылкой на ENGINE-снимок, причины, переход статуса
`MANUAL_REVIEW → APPROVED | COUNTER_OFFER | REJECTED`, событие журнала и предложение клиенту.
Backoffice статус и событие сам не пишет: иначе они задвоятся. Откат транзакции убирает всё.
Отказ с аудитом (`AUTHORITY_LEVEL_TOO_LOW`) backoffice пишет в `audit_log` отдельной транзакцией
после отката: ошибка несёт уровень и код.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import offers
from app.modules.applications import Actor, Application, Status, record_event, transition
from app.modules.decisioning import (
    DecisionInput,
    DecisionResult,
    UnderwriterEvaluation,
    UnderwriterTerms,
    ViolationKind,
    decide,
    evaluate_underwriter_decision,
    input_from_json,
)
from app.modules.decisioning.types import Level, Outcome
from app.modules.pipeline import hooks
from app.modules.pipeline.models import Decision, DecisionReason
from app.shared.errors import AppError, not_found

_EVALUATION = TypeAdapter(UnderwriterEvaluation)
_PERCENT = Decimal(100)
_TARGET = {
    Outcome.APPROVED: Status.APPROVED,
    Outcome.COUNTER_OFFER: Status.COUNTER_OFFER,
    Outcome.REJECTED: Status.REJECTED,
}
# Что видит клиент вместо комментария андеррайтера (30-11: комментарий клиенту не пересказывается)
CLIENT_TEXTS = {
    "UW_NEW_INFO": "Специалист банка получил новые сведения и пересмотрел решение.",
    "UW_COLLATERAL_ASSESSED": "Специалист банка оценил предложенное обеспечение.",
    "UW_FLAG_CLEARED": "Специалист банка проверил заявку вручную.",
    "UW_POLICY_EXCEPTION": "Специалист банка рассмотрел заявку индивидуально.",
    "UW_RISK_HIGHER": "По итогам ручной проверки специалист оценил риск выше расчётного.",
    "UW_DOCUMENT_ISSUE": "По документам специалисту банка нужно больше определённости.",
    "UW_OTHER": "Решение принял специалист банка по итогам рассмотрения.",
}
UNDERWRITER_TEXTS = {
    "UW_NEW_INFO": "Получены новые данные",
    "UW_COLLATERAL_ASSESSED": "Залог оценён",
    "UW_FLAG_CLEARED": "Флаг проверен и снят",
    "UW_POLICY_EXCEPTION": "Исключение из политики",
    "UW_RISK_HIGHER": "Риск выше модельного",
    "UW_DOCUMENT_ISSUE": "Проблема с документами",
    "UW_OTHER": "Другое",
}


@dataclass(frozen=True, slots=True)
class UnderwriterReceipt:
    decision_id: UUID
    engine_decision_id: UUID
    application_id: UUID
    previous_status: str
    new_status: str
    version: int  # версия заявки после перехода
    outcome: Outcome
    deviation: bool
    exception_used: bool
    offer_id: UUID | None
    evaluation: UnderwriterEvaluation

    @property
    def checked_conditions(self) -> tuple[str, ...]:
        return tuple(c.code for c in self.evaluation.checks if c.passed)


@dataclass(frozen=True, slots=True)
class EngineBasis:
    decision: Decision
    inputs: DecisionInput
    result: DecisionResult


def _fail(status: int, code: str, detail: str, **extra: Any) -> AppError:
    return AppError(status, code, detail, errors=[extra] if extra else None)


def _load_basis(
    session: Session, application: Application, engine_decision_id: UUID | None
) -> EngineBasis:
    row = session.scalars(
        select(Decision)
        .where(Decision.application_id == application.id, Decision.source == "ENGINE")
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(1)
    ).first()
    if row is None:
        raise _fail(409, "ENGINE_DECISION_MISSING", "У заявки нет решения ядра")
    if engine_decision_id is not None and engine_decision_id != row.id:
        raise _fail(409, "ENGINE_DECISION_STALE", "Есть более новое решение ядра")
    try:
        inputs = input_from_json(json.dumps(row.inputs))
    except ValueError as exc:  # снимок старой схемы политики
        raise _fail(
            409, "ENGINE_SNAPSHOT_INCOMPATIBLE", "Снимок ядра не читается текущей схемой"
        ) from exc
    result = decide(inputs)
    if result.inputs_hash != row.inputs_hash or result.outcome.value != row.outcome:
        raise _fail(409, "ENGINE_SNAPSHOT_MISMATCH", "Решение ядра не воспроизводится по снимку")
    return EngineBasis(row, inputs, result)


def _application(session: Session, application_id: UUID, *, lock: bool) -> Application:
    query = select(Application).where(Application.id == application_id)
    application = session.scalars(query.with_for_update() if lock else query).first()
    if application is None:
        raise not_found("Заявка")
    return application


def _check_state(application: Application, expected_version: int | None) -> None:
    if expected_version is not None and application.version != expected_version:
        raise _fail(
            409,
            "VERSION_CONFLICT",
            "Заявку уже изменили, обновите карточку",
            version=application.version,
        )
    if application.status != Status.MANUAL_REVIEW.value:
        raise _fail(
            409,
            "INVALID_TRANSITION",
            "Заявка не на ручном рассмотрении",
            currentStatus=application.status,
        )


def preview_underwriter_decision(  # noqa: PLR0913 — зеркало записи без сохранения (evaluate-offer)
    session: Session,
    *,
    application_id: UUID,
    actor_level: Level,
    outcome: Outcome,
    terms: UnderwriterTerms | None,
    reason_code: str | None = None,
    comment: str | None = None,
    expected_version: int | None = None,
    engine_decision_id: UUID | None = None,
) -> UnderwriterEvaluation:
    """Только расчёт и проверка, ничего не пишет. Состояние заявки и версия проверяются так же."""
    application = _application(session, application_id, lock=False)
    _check_state(application, expected_version)
    basis = _load_basis(session, application, engine_decision_id)
    return evaluate_underwriter_decision(
        basis.inputs,
        basis.result,
        outcome,
        terms,
        actor_level,
        reason_code,
        comment,
        application_version=application.version,
    )


def _raise_if_denied(evaluation: UnderwriterEvaluation) -> None:
    if evaluation.allowed:
        return
    errors = [
        {
            "code": v.code,
            "kind": v.kind.value,
            "params": json.loads(json.dumps(v.params, default=str)),
        }
        for v in evaluation.violations
    ]
    only_authority = all(v.kind == ViolationKind.AUTHORITY for v in evaluation.violations)
    if only_authority:
        raise AppError(
            403,
            "AUTHORITY_LEVEL_TOO_LOW",
            "Решение требует более высокого уровня полномочий",
            errors=[
                {
                    "requiredLevel": evaluation.required_level.value,
                    "actorLevel": evaluation.actor_level.value,
                }
            ],
        )
    raise AppError(
        422,
        "UNDERWRITER_DECISION_INVALID",
        "Решение андеррайтера не прошло проверку",
        errors=errors,
    )


def _explain(
    engine: Decision,
    ev: UnderwriterEvaluation,
    waived: list[dict[str, Any]],
) -> dict[str, Any]:
    explain = copy.deepcopy(engine.explain)
    explain["outcome"] = ev.outcome.value
    explain["required_level"] = ev.required_level.value
    explain["variants"] = []
    explain["variants_status"] = "NOT_APPLICABLE"
    numbers = explain.setdefault("numbers", {})
    if ev.terms is not None and ev.rate is not None:
        if ev.rate != (engine.rate_percent / _PERCENT if engine.rate_percent is not None else None):
            numbers["rate_breakdown"] = None  # разбивка относится к ставке ядра
        for key, value in (
            ("rate", ev.rate),
            ("payment_rub", ev.payment_rub),
            ("last_payment_rub", ev.last_payment_rub),
            ("overpayment_rub", ev.overpayment_rub),
            ("dscr", ev.dscr),
            ("stress_dscr", ev.stress_dscr),
            ("debt_to_revenue_with_new", ev.debt_to_revenue_with_new),
        ):
            numbers[key] = json.loads(json.dumps(value, default=str))
    code = ev.reason_code
    reasons: list[dict[str, Any]] = []
    explanations: list[dict[str, Any]] = []
    if code is not None:
        reasons.append({"code": code, "kind": "OVERRIDE", "params": {}})
        client = CLIENT_TEXTS[code] if ev.outcome != Outcome.APPROVED else ""
        explanations.append(
            {"code": code, "client": client, "underwriter": UNDERWRITER_TEXTS[code], "action": ""}
        )
    for item in waived:
        reasons.append(item)
        explanations.append(
            {
                "code": item["code"],
                "client": "",
                "underwriter": "Исключение из политики",
                "action": "",
            }
        )
    explain["reasons"] = reasons
    explain["explanations"] = explanations
    explain["underwriter"] = _EVALUATION.dump_python(ev, mode="json")
    explain["underwriter"]["terms"] = (
        None
        if ev.terms is None
        else {
            "product": ev.terms.product.value,
            "amount_rub": ev.terms.amount_rub,
            "term_months": ev.terms.term_months,
            "rate": str(ev.terms.rate),
        }
    )
    return explain


def record_underwriter_decision(  # noqa: PLR0913 — полный набор данных ручного решения
    session: Session,
    *,
    application_id: UUID,
    expected_version: int,
    actor_id: UUID,
    actor_level: Level,
    outcome: Outcome,
    terms: UnderwriterTerms | None = None,
    reason_code: str | None = None,
    comment: str | None = None,
    engine_decision_id: UUID | None = None,
) -> UnderwriterReceipt:
    """Сохранить ручное решение и перевести заявку (всё в транзакции вызывающего).

    Ошибки (`AppError`): 404 `NOT_FOUND`; 409 `VERSION_CONFLICT` (версия заявки не `expected_version`,
    в том числе повторный вызов после успешного); 409 `INVALID_TRANSITION` (не `MANUAL_REVIEW`);
    409 `ENGINE_DECISION_MISSING` / `ENGINE_DECISION_STALE` / `ENGINE_SNAPSHOT_INCOMPATIBLE` /
    `ENGINE_SNAPSHOT_MISMATCH`; 403 `AUTHORITY_LEVEL_TOO_LOW` (в errors — требуемый уровень);
    422 `UNDERWRITER_DECISION_INVALID` (в errors — список нарушений: code, kind, params).
    """
    application = _application(session, application_id, lock=True)
    _check_state(application, expected_version)
    basis = _load_basis(session, application, engine_decision_id)
    ev = evaluate_underwriter_decision(
        basis.inputs,
        basis.result,
        outcome,
        terms,
        actor_level,
        reason_code,
        comment,
        application_version=application.version,
    )
    _raise_if_denied(ev)

    engine = basis.decision
    waived = [
        {"code": code, "kind": "CONSTRAINT", "params": {"exception": True}}
        for code in ev.exception_codes
    ]
    explain = _explain(engine, ev, waived)
    with_terms = ev.terms is not None
    decision = Decision(
        application_id=application.id,
        run_id=None,
        source="UNDERWRITER",
        outcome=outcome.value,
        route="MANUAL",
        required_level=ev.required_level.value,
        policy_version_id=engine.policy_version_id,
        engine_version=engine.engine_version,
        inputs=engine.inputs,
        inputs_hash=engine.inputs_hash,
        features=engine.features,
        score=engine.score,
        grade=engine.grade,
        pd=engine.pd,
        revenue_monthly_rub=engine.revenue_monthly_rub,
        free_cash_flow_rub=engine.free_cash_flow_rub,
        dscr=ev.dscr if with_terms else engine.dscr,
        stress_dscr=ev.stress_dscr if with_terms else engine.stress_dscr,
        max_amount_rub=engine.max_amount_rub,
        rate_percent=ev.rate * _PERCENT
        if with_terms and ev.rate is not None
        else engine.rate_percent,
        payment_rub=ev.payment_rub if with_terms else engine.payment_rub,
        explain=explain,
        snapshot_ids=list(engine.snapshot_ids),
        overrides_decision_id=engine.id,
        override_reason=(comment or "").strip() or None,
        actor_id=actor_id,
        actor_level=actor_level.value,
        override_reason_code=reason_code,
        deviation=ev.deviation,
    )
    session.add(decision)
    session.flush()
    session.add_all(
        DecisionReason(
            decision_id=decision.id,
            position=i,
            code=r["code"],
            kind=r["kind"],
            points=None,
            params=r["params"],
        )
        for i, r in enumerate(explain["reasons"])
    )
    session.flush()

    previous = application.status
    payload = {
        "decisionId": str(decision.id),
        "outcome": outcome.value,
        "level": actor_level.value,
        "deviation": ev.deviation,
    }
    transition(
        session,
        application,
        _TARGET[outcome],
        actor=Actor.UNDERWRITER,
        actor_id=actor_id,
        reason_code=reason_code,
        payload=payload,
    )
    record_event(
        session,
        application,
        "OVERRIDE" if ev.deviation else "STEP",
        actor_type=Actor.UNDERWRITER,
        actor_id=actor_id,
        step_code="UNDERWRITER_DECISION",
        reason_code=reason_code,
        payload={**payload, "exception": ev.exception_used},
    )
    offer_id: UUID | None = None
    if outcome != Outcome.REJECTED and ev.terms is not None:
        hooks.create_underwriter_offer(
            session, application, decision, basis.inputs, outcome, ev.terms
        )
        offer = offers.current_offer(session, application.id)
        offer_id = offer.id if offer is not None else None
    return UnderwriterReceipt(
        decision_id=decision.id,
        engine_decision_id=engine.id,
        application_id=application.id,
        previous_status=previous,
        new_status=application.status,
        version=application.version,
        outcome=outcome,
        deviation=ev.deviation,
        exception_used=ev.exception_used,
        offer_id=offer_id,
        evaluation=ev,
    )
