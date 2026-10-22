"""Заявка и её стейт-машина, черновик, журнал, согласия, задачи клиенту, залог. Документ: 20-02, 20-03, 20-04, D-055."""

from app.modules.applications import wizard_draft as _wizard_draft  # noqa: F401  (регистрирует слушателя)
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
from app.modules.applications.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
)
from app.modules.applications.router import router
from app.modules.applications.service import (
    get_for,
    record_event,
    register_submit_check,
    transition,
)
from app.modules.applications.states import Actor, Status

__all__ = [
    "BANK_NAME",
    "SIGN_METHOD",
    "Actor",
    "Application",
    "ApplicationEvent",
    "ApplicationVersion",
    "SignedBkiConsent",
    "SignedConsent",
    "Status",
    "bki_consents",
    "consents_router",
    "ensure_pep_rules",
    "get_for",
    "get_valid_consent",
    "pep_rules_version",
    "proof_for",
    "record_event",
    "register_submit_check",
    "router",
    "signer_identity",
    "transition",
]
