"""Заявка и её стейт-машина, черновик, журнал, согласия, задачи клиенту, залог. Документ: 20-02, 20-03, 20-04, D-055."""

from app.modules.applications import reset  # noqa: F401 — регистрирует сброс демо-данных (T-371)
from app.modules.applications import wizard_draft as _wizard_draft  # noqa: F401  (регистрирует слушателя)
from app.modules.applications.bureau_lifecycle import register_bureau_handlers
from app.modules.applications.client_tasks import (
    InfoRequestReceipt,
    TaskSpec,
    information_rounds_exhausted,
    register_recheck,
    request_information,
)
from app.modules.applications.consent_proof import SIGN_METHOD, proof_for
from app.modules.applications.consents import (
    BANK_NAME,
    SignedBkiConsent,
    SignedConsent,
    bki_consents,
    ensure_pep_rules,
    get_valid_consent,
    pep_rules_version,
    signer_identity,
)
from app.modules.applications.consents_router import router as consents_router
from app.modules.applications.document_access import (
    document_confirmation_context,
    document_upload_context,
    statement_processing_context,
)
from app.modules.applications.events import EventNotice, event_ids, event_notice
from app.modules.applications.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
)
from app.modules.applications.operations import hold as hold_operation
from app.modules.applications.operations import scope as operation_scope
from app.modules.applications.router import router
from app.modules.applications.service import (
    add_version,
    current_version,
    get_for,
    record_event,
    register_submit_check,
    transition,
)
from app.modules.applications.states import Actor, Status
from app.modules.applications.tasks_router import router as tasks_router

__all__ = [
    "EventNotice",
    "event_ids",
    "event_notice",
    "BANK_NAME",
    "SIGN_METHOD",
    "Actor",
    "Application",
    "InfoRequestReceipt",
    "ApplicationEvent",
    "ApplicationVersion",
    "SignedBkiConsent",
    "SignedConsent",
    "Status",
    "TaskSpec",
    "add_version",
    "bki_consents",
    "consents_router",
    "current_version",
    "document_upload_context",
    "document_confirmation_context",
    "statement_processing_context",
    "ensure_pep_rules",
    "get_for",
    "get_valid_consent",
    "hold_operation",
    "information_rounds_exhausted",
    "operation_scope",
    "pep_rules_version",
    "proof_for",
    "record_event",
    "register_recheck",
    "register_bureau_handlers",
    "register_submit_check",
    "request_information",
    "router",
    "signer_identity",
    "tasks_router",
    "transition",
]
