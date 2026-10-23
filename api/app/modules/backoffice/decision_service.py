"""T-362: HTTP-команда не владеет ни решением, ни переходом — ими владеет pipeline."""

from decimal import Decimal
from uuid import UUID

from app.modules import audit, auth, decisioning, pipeline
from app.modules.backoffice.decision_schemas import (
    BankDecisionRequest,
    BankDecisionSaved,
    BankDecisionTerms,
)
from app.modules.backoffice.manual_reference import resolve
from app.modules.backoffice.service import require_bank
from app.shared import db, idempotency
from app.shared.errors import AppError


def actor_level(principal: auth.Principal) -> decisioning.Level:
    require_bank(principal)
    if principal.level not in {"L1", "L2"}:
        raise AppError(403, "FORBIDDEN", "У сотрудника нет уровня полномочий")
    return decisioning.Level(principal.level)


def decision_terms(terms: BankDecisionTerms | None) -> decisioning.UnderwriterTerms | None:
    if terms is None:
        return None
    return decisioning.UnderwriterTerms(
        product=decisioning.Product(terms.product_code),
        amount_rub=terms.amount_rub,
        term_months=terms.term_months,
        rate=terms.rate_percent / Decimal(100) if terms.rate_percent is not None else None,
    )


def decide(
    principal: auth.Principal, application_id: UUID, body: BankDecisionRequest, key: str
) -> idempotency.Reply:
    level = actor_level(principal)
    request = body.model_dump(mode="json", by_alias=True)
    if body.evaluation_ref is None:
        # Новый необязательный атрибут не меняет hash запросов, сохранённых до T-364.
        request.pop("evaluationRef", None)
    # HTTP OperationFence держит замок компании до commit/ответа, включая отказ с аудитом.
    try:
        with db.transaction() as session:

            def action() -> idempotency.Reply:
                terms, engine_id = resolve(principal.user_id, application_id, body)
                receipt = pipeline.record_underwriter_decision(
                    session,
                    application_id=application_id,
                    expected_version=body.expected_version,
                    actor_id=principal.user_id,
                    actor_level=level,
                    outcome=decisioning.Outcome(body.outcome),
                    terms=decision_terms(terms),
                    reason_code=body.reason_code,
                    comment=body.comment,
                    engine_decision_id=engine_id,
                )
                audit.record(
                    session,
                    "UNDERWRITER_DECISION",
                    actor_id=principal.user_id,
                    actor_role=principal.role,
                    object_type="APPLICATION",
                    object_id=str(application_id),
                    details={
                        "decisionId": str(receipt.decision_id),
                        "outcome": body.outcome,
                        "level": level.value,
                        "deviation": receipt.deviation,
                    },
                )
                result = BankDecisionSaved(
                    application_id=application_id,
                    decision_id=receipt.decision_id,
                    engine_decision_id=receipt.engine_decision_id,
                    status=receipt.new_status,
                    version=receipt.version,
                    outcome=body.outcome,
                    deviation=receipt.deviation,
                    exception_used=receipt.exception_used,
                    offer_id=receipt.offer_id,
                )
                return idempotency.Reply(200, result.model_dump(mode="json", by_alias=True))

            return idempotency.run_once(
                session,
                scope=f"{principal.user_id}:POST:/backoffice/applications/{application_id}/decision",
                key=key,
                request=request,
                action=action,
            )
    except AppError as exc:
        authority_denied = exc.code == "AUTHORITY_LEVEL_TOO_LOW" or any(
            error.get("kind") == "AUTHORITY" for error in exc.errors or []
        )
        if authority_denied:
            # Бизнес-транзакция уже откатилась. Сам отказ должен остаться в аудите (30-11).
            with db.transaction() as session:
                audit.record(
                    session,
                    "AUTHORITY_LEVEL_TOO_LOW",
                    actor_id=principal.user_id,
                    actor_role=principal.role,
                    object_type="APPLICATION",
                    object_id=str(application_id),
                    details={"outcome": body.outcome, "levels": exc.errors or []},
                )
        raise
