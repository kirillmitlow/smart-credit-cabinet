"""«Мои кредиты»: кредит и график платежей. Документ: 20-05, 30-16.

Публичный интерфейс: `open_loan` (вызывает выдача, одна транзакция с `DISBURSED`) и ручки `router`.
"""

from app.modules.loans.models import Loan, PaymentScheduleRow
from app.modules.loans.router import router
from app.modules.loans.service import NewLoan, next_payment, open_loan, schedule_rows

__all__ = [
    "Loan",
    "NewLoan",
    "PaymentScheduleRow",
    "next_payment",
    "open_loan",
    "router",
    "schedule_rows",
]
