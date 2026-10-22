"""Выдача кредита: открытие счёта, выдача в АБС через outbox, кредит и график. Документ: 20-05.

Публичный интерфейс: имя задачи (`TASK_NAME`, ставит подписание), `register_terms_provider`
(условия кредита; подключает `app/wiring.py`), обработчики outbox (`register`) и аудит тупиков.
"""

from app.modules.disbursement import reset  # noqa: F401 — регистрирует сброс демо-данных (T-371)
from app.modules.disbursement.delivery import audit_dead_letter, register
from app.modules.disbursement.keys import account_key, disbursement_key, obligation_key
from app.modules.disbursement.models import Disbursement
from app.modules.disbursement.service import StartResult, start
from app.modules.disbursement.tasks import TASK_NAME, run
from app.modules.disbursement.terms import AgreedTerms, register_terms_provider

__all__ = [
    "TASK_NAME",
    "AgreedTerms",
    "Disbursement",
    "StartResult",
    "account_key",
    "audit_dead_letter",
    "disbursement_key",
    "obligation_key",
    "register",
    "register_terms_provider",
    "run",
    "start",
]
