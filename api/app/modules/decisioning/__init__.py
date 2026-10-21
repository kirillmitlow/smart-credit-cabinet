"""Чистое ядро решения: признаки, скоринг, лимиты, ставка, встречные, объяснения.

Без сети, БД, времени и случайности (R2, D-030): данные и правила приходят аргументами,
результат возвращается значением. Спецификации — docs/plan/30-decisioning/.

Публичный интерфейс (50-04): другие модули импортируют только отсюда.
"""

from app.modules.decisioning.decide import decide
from app.modules.decisioning.loan_math import build_schedule
from app.modules.decisioning.policy import Policy, PolicyError, parse_policy
from app.modules.decisioning.products import ProductContext, check_product
from app.modules.decisioning.serialization import (
    input_from_json,
    input_to_json,
    inputs_hash,
    policy_hash,
)
from app.modules.decisioning.types import DecisionInput, DecisionResult

__all__ = [
    "DecisionInput",
    "DecisionResult",
    "Policy",
    "PolicyError",
    "ProductContext",
    "build_schedule",
    "check_product",
    "decide",
    "input_from_json",
    "input_to_json",
    "inputs_hash",
    "parse_policy",
    "policy_hash",
]
