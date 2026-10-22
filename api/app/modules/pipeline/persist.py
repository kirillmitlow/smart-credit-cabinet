"""Шаг 6: снимок решения, причины, переход статуса и события — одна транзакция (T-275, 50-05, D-030).

Вызывающий держит транзакцию (R7). Повторный вызов для того же запуска ничего не создаёт и не
переводит: решение уникально по `run_id`. Тексты причин сохраняются в снимке (Q-113).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.applications import Actor, Application, Status, record_event, transition
from app.modules.decisioning import DecisionInput, DecisionResult, input_to_json
from app.modules.decisioning.types import Outcome
from app.modules.pipeline import hooks
from app.modules.pipeline.models import Decision, DecisionReason, PipelineRun

log = structlog.get_logger("app.pipeline.persist")

# Исход ядра → статус заявки. `NOT_ELIGIBLE` (самозанятый) закрывает заявку отказом с кодом причины
OUTCOME_STATUS: dict[Outcome, Status] = {
    Outcome.APPROVED: Status.APPROVED,
    Outcome.COUNTER_OFFER: Status.COUNTER_OFFER,
    Outcome.NEEDS_INFO: Status.NEEDS_INFO,
    Outcome.MANUAL_REVIEW: Status.MANUAL_REVIEW,
    Outcome.REJECTED: Status.REJECTED,
    Outcome.NOT_ELIGIBLE: Status.REJECTED,
}
_RESULT = TypeAdapter(DecisionResult)
_PERCENT = Decimal(100)


def _dump(model: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = TypeAdapter(type(model)).dump_python(model, mode="json")
    return dumped


def build_decision(
    run: PipelineRun,
    inp: DecisionInput,
    result: DecisionResult,
    *,
    policy_version_id: UUID,
    engine_version: str,
    snapshot_ids: list[UUID],
) -> Decision:
    """Строка `decisions` по результату ядра (без записи в базу)."""
    n = result.numbers
    explain = _RESULT.dump_python(result, mode="json")
    outcome = Outcome.REJECTED if result.outcome == Outcome.NOT_ELIGIBLE else result.outcome
    return Decision(
        application_id=run.application_id,
        run_id=run.id,
        source="ENGINE",
        outcome=outcome.value,
        route=result.route.value,
        required_level=result.required_level.value,
        policy_version_id=policy_version_id,
        engine_version=engine_version,
        inputs=json.loads(input_to_json(inp)),
        inputs_hash=result.inputs_hash,
        features=_dump(result.features) if result.features is not None else None,
        score=n.score_points,
        grade=n.grade.value if n.grade else None,
        pd=n.pd,
        revenue_monthly_rub=n.revenue_cautious_rub,
        free_cash_flow_rub=n.flow_rub,
        dscr=n.dscr,
        stress_dscr=n.stress_dscr,
        max_amount_rub=n.max_amount_rub,
        rate_percent=n.rate * _PERCENT if n.rate is not None else None,
        payment_rub=n.payment_rub,
        explain=explain,
        snapshot_ids=snapshot_ids,
    )


def build_reasons(decision_id: UUID, result: DecisionResult) -> list[DecisionReason]:
    return [
        DecisionReason(
            decision_id=decision_id,
            position=i,
            code=r.code,
            kind=r.kind.value,
            points=None,
            params=json.loads(json.dumps(r.params, default=str)),
        )
        for i, r in enumerate(result.reasons)
    ]


def persist_decision(
    session: Session,
    run: PipelineRun,
    inp: DecisionInput,
    result: DecisionResult,
    *,
    policy_version_id: UUID,
    engine_version: str,
    snapshot_ids: list[UUID],
) -> tuple[Decision, bool]:
    """Сохранить решение и перевести заявку. Возвращает (решение, создано ли сейчас)."""
    existing = session.scalars(select(Decision).where(Decision.run_id == run.id)).first()
    if existing is not None:
        return existing, False
    application = session.scalars(
        select(Application).where(Application.id == run.application_id).with_for_update()
    ).one()
    decision = build_decision(
        run,
        inp,
        result,
        policy_version_id=policy_version_id,
        engine_version=engine_version,
        snapshot_ids=snapshot_ids,
    )
    session.add(decision)
    session.flush()
    session.add_all(build_reasons(decision.id, result))
    session.flush()
    target = OUTCOME_STATUS[result.outcome]
    transition(
        session,
        application,
        target,
        actor=Actor.SYSTEM,
        reason_code=result.primary_reason,
        payload={"decisionId": str(decision.id), "outcome": result.outcome.value},
    )
    record_event(
        session,
        application,
        "STEP",
        actor_type=Actor.SYSTEM,
        step_code="DECISION",
        reason_code=result.primary_reason,
        payload={
            "decisionId": str(decision.id),
            "outcome": result.outcome.value,
            "reasons": list(result.reason_codes),
            "policyVersion": result.policy_version,
        },
    )
    hooks.after_decision(session, application, decision, result)
    return decision, True
