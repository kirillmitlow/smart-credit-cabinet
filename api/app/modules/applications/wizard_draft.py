"""Ответы мастера → черновик заявки (T-242, 10-07, принцип 5: второй раз ничего не вводится).

`catalog` стоит ниже `applications` и заявок не знает: он вызывает зарегистрированного слушателя.
Мастер без `applicationId` создаёт черновик `DRAFT` и возвращает его id.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules import auth, catalog
from app.modules.applications import service


def save_wizard_result(
    session: Session,
    principal: auth.Principal,
    application_id: UUID | None,
    answers: catalog.WizardAnswers,
    result: catalog.WizardResult,
) -> UUID:
    if application_id is None:
        application = service.create(session, principal, {})
    else:
        application = service.get_for(session, principal, application_id)
    fields: dict[str, Any] = {}
    if result.primary is not None:
        fields["product_code"] = result.primary.product_code
    if answers.amount_rub is not None:
        fields["amount_rub"] = answers.amount_rub
    if answers.term_months is not None:
        fields["term_months"] = answers.term_months
    if answers.purpose not in (None, "UNKNOWN"):
        fields["purpose_code"] = answers.purpose
    wizard: dict[str, Any] = {
        "answers": answers.model_dump(mode="json", by_alias=True, exclude_none=True),
        "outcome": result.outcome.value,
        "ruleId": result.rule_id,
        "startPath": result.start_path,
        "primary": result.primary.product_code if result.primary else None,
        "alternative": result.alternative.product_code if result.alternative else None,
    }
    service.update_draft(session, application, application.version, fields, {"wizard": wizard})
    return application.id


catalog.register_recommendation_listener(save_wizard_result)
