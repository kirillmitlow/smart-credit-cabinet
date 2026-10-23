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
from app.modules.pipeline.recheck import RecheckReceipt, request_recheck
from app.modules.pipeline.runner import RunResult, run_pipeline

__all__ = [
    "ConsentView",
    "RecheckReceipt",
    "RunResult",
    "current_policy",
    "load_policy_file",
    "register_current",
    "register_policy",
    "request_recheck",
    "reset_policy_cache",
    "router",
    "run_pipeline",
    "set_consents_provider",
]
