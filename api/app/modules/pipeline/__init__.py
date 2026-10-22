"""Оркестрация конвейера: сбор данных, снимки, вызов decide(), переход по результату. Документ: 30-01, 50-05."""

from app.modules.pipeline.consents import ConsentView, set_consents_provider
from app.modules.pipeline.policy_loader import load_policy_file
from app.modules.pipeline.policy_registry import (
    current_policy,
    register_current,
    register_policy,
    reset_policy_cache,
)
from app.modules.pipeline.runner import RunResult, run_pipeline

__all__ = [
    "ConsentView",
    "RunResult",
    "current_policy",
    "load_policy_file",
    "register_current",
    "register_policy",
    "reset_policy_cache",
    "run_pipeline",
    "set_consents_provider",
]
