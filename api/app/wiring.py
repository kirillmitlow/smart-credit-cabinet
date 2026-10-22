"""Сборка связей между модулями одного уровня графа (50-04).

`catalog` и `companies` друг друга не знают; факты о компании для каталога и мастера им передаёт
эта функция при создании приложения. Остальные связи (заявка ← мастер, заявка ← согласия)
регистрируются внутри `applications`, который стоит выше обоих.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import applications, catalog, companies, disbursement, pipeline


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


def agreed_terms(session: Session, application_id: UUID) -> disbursement.AgreedTerms | None:
    """Условия выдачи: продукт, сумма и срок из заявки, ставка из последнего решения.

    Запасной путь до модуля `offers` (принятый вариант и договор, T-340/T-341): когда он появится,
    эта функция берёт условия оттуда и отдаёт номер и УИд договора. Время подписи — из журнала заявки.
    """
    application = session.get(applications.Application, application_id)
    decision = pipeline.latest_terms(session, application_id)
    if (
        application is None
        or decision is None
        or application.product_code is None
        or application.amount_rub is None
        or application.term_months is None
    ):
        return None
    signed_at = session.scalar(
        select(applications.ApplicationEvent.at)
        .where(
            applications.ApplicationEvent.application_id == application_id,
            applications.ApplicationEvent.to_status == applications.Status.SIGNED.value,
        )
        .order_by(applications.ApplicationEvent.id.desc())
        .limit(1)
    )
    return disbursement.AgreedTerms(
        product_code=application.product_code,
        amount_rub=application.amount_rub,
        term_months=application.term_months,
        rate_percent=decision.rate_percent,
        signed_at=signed_at,
    )


def wire_modules() -> None:
    catalog.register_company_facts_provider(company_facts)
    disbursement.register_terms_provider(agreed_terms)
