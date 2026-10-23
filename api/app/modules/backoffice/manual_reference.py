"""Ссылка на проверенные условия: подпись, сотрудник, версия и снимок ядра (T-364).

Хранения и новых таблиц нет. Ссылка действует лишь для той же версии/ENGINE: при сохранении
pipeline заново блокирует заявку и проверяет оба идентификатора и всю банковскую политику.
"""

import base64
import hashlib
import hmac
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.backoffice.decision_schemas import BankDecisionRequest, BankDecisionTerms
from app.shared.errors import AppError, not_found
from app.shared.settings import get_settings


class Reference(BaseModel):
    actor_id: UUID
    application_id: UUID
    expected_version: int
    engine_decision_id: UUID
    outcome: Literal["APPROVED", "COUNTER_OFFER"]
    terms: BankDecisionTerms


def _signature(payload: str) -> str:
    return hmac.new(
        get_settings().session_secret.encode(),
        f"scc-underwriter-v1:{payload}".encode(),
        hashlib.sha256,
    ).hexdigest()


def issue(reference: Reference) -> str:
    payload = base64.urlsafe_b64encode(reference.model_dump_json().encode()).decode().rstrip("=")
    return f"{payload}.{_signature(payload)}"


def resolve(
    actor_id: UUID, application_id: UUID, body: BankDecisionRequest
) -> tuple[BankDecisionTerms | None, UUID | None]:
    if body.evaluation_ref is None:
        return body.terms, body.engine_decision_id
    try:
        payload, signature = body.evaluation_ref.split(".")
        if not hmac.compare_digest(_signature(payload), signature):
            raise ValueError("Неверная подпись")
        raw = base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True)
        reference = Reference.model_validate_json(raw)
    except (ValueError, TypeError) as exc:
        raise AppError(
            422, "EVALUATION_REFERENCE_INVALID", "Ссылка на расчёт недействительна"
        ) from exc
    if reference.actor_id != actor_id or reference.application_id != application_id:
        raise not_found("Результат расчёта")
    if reference.expected_version != body.expected_version:
        raise AppError(409, "VERSION_CONFLICT", "Расчёт относится к другой версии заявки")
    if reference.outcome != body.outcome or (
        body.engine_decision_id is not None
        and reference.engine_decision_id != body.engine_decision_id
    ):
        raise AppError(422, "EVALUATION_REFERENCE_INVALID", "Ссылка относится к другому решению")
    return reference.terms, reference.engine_decision_id
