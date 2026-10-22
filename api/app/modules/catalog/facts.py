"""Что каталог знает о компании, не ходя в чужие таблицы.

`catalog` и `companies` стоят на одном уровне графа (50-04) и друг друга не импортируют. Факты о
компании отдаёт функция, которую при сборке приложения регистрирует `app.main`
(`register_company_facts_provider`). Без неё компания считается неизвестной: возраст не проверяем,
клиентом банка не считаем (осторожно: овердрафт не покажем доступным).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.decisioning import ProductContext, full_months_between


@dataclass(frozen=True, slots=True)
class CompanyFacts:
    registration_date: date | None = None
    is_bank_customer: bool = False
    customer_since: date | None = None
    # Чистый месячный денежный поток, если известен (выписка, обороты): для «комфортного платежа»
    monthly_cash_flow_rub: int | None = None


CompanyFactsProvider = Callable[[Session, UUID], CompanyFacts | None]
_provider: CompanyFactsProvider | None = None


def register_company_facts_provider(provider: CompanyFactsProvider | None) -> None:
    global _provider
    _provider = provider


def facts_for(session: Session, company_id: UUID) -> CompanyFacts:
    if _provider is None:
        return CompanyFacts()
    return _provider(session, company_id) or CompanyFacts()


def business_age_months(facts: CompanyFacts, today: date) -> int | None:
    if facts.registration_date is None:
        return None
    return full_months_between(facts.registration_date, today)


def customer_months(facts: CompanyFacts, today: date) -> int:
    """Месяцы обслуживания в банке; нет клиента или даты — 0 (требование овердрафта не выполнено)."""
    if not facts.is_bank_customer or facts.customer_since is None:
        return 0
    return full_months_between(facts.customer_since, today)


def product_context(facts: CompanyFacts, today: date) -> ProductContext:
    """Контекст требований продукта для компании без суммы и срока (общий для каталога и мастера)."""
    return ProductContext(
        app_today=today,
        business_age_months=business_age_months(facts, today),
        registration_date=facts.registration_date,
        is_bank_customer=facts.is_bank_customer,
        customer_turnover_months=customer_months(facts, today),
        collateral_provided=False,
        security_confirmed=False,
    )
