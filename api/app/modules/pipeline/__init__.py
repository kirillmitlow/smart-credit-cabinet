"""Оркестрация конвейера: сбор данных, снимки, вызов decide(), переход по результату. Документ: 30-01, 50-05."""

from app.modules.pipeline import reset  # noqa: F401 — регистрирует сброс демо-данных (T-371)
from app.modules.pipeline.consents import ConsentView, set_consents_provider
from app.modules.pipeline.decision_view import router
from app.modules.pipeline.policy_loader import load_policy_file
from app.modules.pipeline.policy_registry import (
    current_policy,
    register_current,
    register_policy,
    reset_policy_cache,
)
from app.modules.pipeline.runner import RunResult, run_pipeline
from app.modules.pipeline.underwriter import (
    UnderwriterReceipt,
    preview_underwriter_decision,
    record_underwriter_decision,
)

__all__ = [
    "ConsentView",
    "RunResult",
    "UnderwriterReceipt",
    "current_policy",
    "load_policy_file",
    "preview_underwriter_decision",
    "record_underwriter_decision",
    "register_current",
    "register_policy",
    "reset_policy_cache",
    "router",
    "run_pipeline",
    "set_consents_provider",
]
