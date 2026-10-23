"""T-364: предварительный расчёт — read-only, сохранение остаётся в T-362."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from app.modules import auth, decisioning, pipeline
from app.modules.backoffice.decision_schemas import BankDecisionTerms
from app.modules.backoffice.decision_service import actor_level, decision_terms
from app.modules.backoffice.manual_reference import Reference, issue
from app.modules.backoffice.manual_schemas import (
    BankOfferEvaluation,
    BankOfferEvaluationRequest,
    BankOfferViolation,
)
from app.shared import db


def evaluate(
    principal: auth.Principal, application_id: UUID, body: BankOfferEvaluationRequest
) -> BankOfferEvaluation:
    level = actor_level(principal)
    with db.transaction() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        ev = pipeline.preview_underwriter_decision(
            session,
            application_id=application_id,
            actor_level=level,
            outcome=decisioning.Outcome(body.outcome),
            terms=decision_terms(body.terms),
            reason_code=body.reason_code,
            comment=body.comment,
            expected_version=body.expected_version,
            engine_decision_id=body.engine_decision_id,
        )
    reference = None
    if ev.allowed and ev.terms is not None:
        reference = issue(
            Reference(
                actor_id=principal.user_id,
                application_id=application_id,
                expected_version=body.expected_version,
                engine_decision_id=body.engine_decision_id,
                outcome=body.outcome,
                terms=BankDecisionTerms(
                    product_code=ev.terms.product.value,
                    amount_rub=ev.terms.amount_rub,
                    term_months=ev.terms.term_months,
                    rate_percent=ev.rate * Decimal(100) if ev.rate is not None else None,
                ),
            )
        )
    return BankOfferEvaluation(
        application_id=application_id,
        version=body.expected_version,
        engine_decision_id=body.engine_decision_id,
        allowed=ev.allowed,
        evaluation_ref=reference,
        required_level=ev.required_level.value,
        min_comment_chars=ev.min_comment_chars,
        deviation=ev.deviation,
        exception_used=ev.exception_used,
        rate_percent=ev.rate * Decimal(100) if ev.rate is not None else None,
        corridor_min_percent=ev.rate_corridor_min * Decimal(100)
        if ev.rate_corridor_min is not None
        else None,
        corridor_max_percent=ev.rate_corridor_max * Decimal(100)
        if ev.rate_corridor_max is not None
        else None,
        payment_rub=ev.payment_rub,
        last_payment_rub=ev.last_payment_rub,
        overpayment_rub=ev.overpayment_rub,
        dscr=ev.dscr,
        stress_dscr=ev.stress_dscr,
        violations=[
            BankOfferViolation(code=v.code, kind=v.kind.value, params=dict(v.params))
            for v in ev.violations
        ],
    )
