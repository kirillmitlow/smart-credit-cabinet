"""Каталог продуктов, мастер подбора, калькулятор платежа, клиент nlu. Документ: 10-06, 10-07, D-060.

Публичный интерфейс модуля — только то, что ниже.
"""

from app.modules.catalog.facts import CompanyFacts, register_company_facts_provider
from app.modules.catalog.policy import clear_cache as clear_policy_cache
from app.modules.catalog.policy import get_policy, policy_dir
from app.modules.catalog.router import register_recommendation_listener, router
from app.modules.catalog.schemas import WizardAnswers, WizardResult

__all__ = [
    "CompanyFacts",
    "WizardAnswers",
    "WizardResult",
    "clear_policy_cache",
    "get_policy",
    "policy_dir",
    "register_company_facts_provider",
    "register_recommendation_listener",
    "router",
]
