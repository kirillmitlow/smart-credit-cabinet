"""Чистое ядро решения: признаки, скоринг, лимиты, ставка, встречные, объяснения.

Без сети, БД, времени и случайности (R2, D-030): данные и правила приходят аргументами,
результат возвращается значением. Спецификации — docs/plan/30-decisioning/.

Публичный интерфейс (50-04): другие модули импортируют только отсюда.
"""

from app.modules.decisioning.dates import add_months, full_months_between
from app.modules.decisioning.decide import decide
from app.modules.decisioning.loan_math import (
    ScheduleRow,
    build_schedule,
    bullet_schedule,
    max_payment,
    overpayment,
    payment_for,
)
from app.modules.decisioning.policy import Policy, PolicyError, parse_policy
from app.modules.decisioning.pricing import lowest_rate
from app.modules.decisioning.products import ProductContext, auto_limit, check_product
from app.modules.decisioning.serialization import (
    input_from_json,
    input_to_json,
    inputs_hash,
    policy_hash,
)
from app.modules.decisioning.texts_ru import client_factor_phrases, format_money, render
from app.modules.decisioning.types import (
    DecisionInput,
    DecisionResult,
    Explanation,
    Grade,
    Level,
    Outcome,
    Product,
    ReasonCode,
)
from app.modules.decisioning.underwriting import (
    UnderwriterEvaluation,
    UnderwriterTerms,
    UwCheck,
    UwViolation,
    ViolationKind,
    evaluate_underwriter_decision,
)

__all__ = [
    "Level",
    "Outcome",
    "lowest_rate",
    "DecisionInput",
    "DecisionResult",
    "Explanation",
    "Grade",
    "Policy",
    "PolicyError",
    "Product",
    "UnderwriterEvaluation",
    "UnderwriterTerms",
    "UwCheck",
    "UwViolation",
    "ViolationKind",
    "evaluate_underwriter_decision",
    "ProductContext",
    "ReasonCode",
    "ScheduleRow",
    "add_months",
    "auto_limit",
    "build_schedule",
    "bullet_schedule",
    "check_product",
    "client_factor_phrases",
    "decide",
    "format_money",
    "full_months_between",
    "input_from_json",
    "input_to_json",
    "inputs_hash",
    "max_payment",
    "overpayment",
    "parse_policy",
    "payment_for",
    "policy_hash",
    "render",
]
