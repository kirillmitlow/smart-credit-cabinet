"""Сборка связей между модулями одного уровня графа (50-04).

`catalog` и `companies` друг друга не знают; факты о компании для каталога и мастера им передаёт
эта функция при создании приложения. Остальные связи (заявка ← мастер, заявка ← согласия)
регистрируются внутри `applications`, который стоит выше обоих.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules import catalog, companies


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def company_facts(session: Session, company_id: UUID) -> catalog.CompanyFacts | None:
    """Возраст, клиент ли банка и с какой даты, денежный поток — из карточки компании.

    Карточку (`companies.profile`) заполняет автозаполнение по ИНН: `customerSince` — дата начала
    обслуживания в банке, `monthlyCashFlowRub` — месячный денежный поток, если известен.
    """
    company = companies.by_id(session, company_id)
    if company is None:
        return None
    profile = company.profile or {}
    flow = profile.get("monthlyCashFlowRub")
    return catalog.CompanyFacts(
        registration_date=company.registered_on,
        is_bank_customer=bool(company.is_bank_customer),
        customer_since=_date(profile.get("customerSince")),
        monthly_cash_flow_rub=int(flow)
        if isinstance(flow, int | str) and str(flow).isdigit()
        else None,
    )


def wire_modules() -> None:
    catalog.register_company_facts_provider(company_facts)
