"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.companies.gov_contracts import CACHE_PREFIX
from app.modules.companies.models import Company
from app.modules.companies.profile_limit import KEY_PREFIX
from app.modules.companies.sync import sync_all
from app.shared import cache
from app.shared.resets import (
    Persona,
    register_after_reset,
    register_cache_prefix,
    register_persona_reset,
    register_reset,
    truncate,
)

TABLES = (
    "companies",
    "company_members",
)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("companies", reset_demo_data)
register_cache_prefix("companies", KEY_PREFIX)
# После чистки базы компании и учётки нужны снова: вход по ИНН берёт их отсюда (T-221)
register_after_reset("companies", sync_all)

register_cache_prefix("companies", CACHE_PREFIX)


def reset_persona(session: Session, scope: Persona) -> None:
    company = session.get(Company, scope.company_id)
    if company is not None:
        company.profile = None
        company.profile_fetched_at = None
        company.registered_on = None
        company.is_bank_customer = None


def reset_persona_cache(scope: Persona) -> None:
    cache.get_redis().unlink(CACHE_PREFIX + str(scope.company_id))


register_persona_reset("companies", reset_persona, priority=100, cache=reset_persona_cache)
