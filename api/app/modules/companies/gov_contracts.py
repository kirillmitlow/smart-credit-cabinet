"""Список ЕИС для выбора контракта (T-224); кредитное решение запрашивает ЕИС заново."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel
from redis import RedisError

from app.modules import auth
from app.modules.companies.models import Company
from app.modules.integrations import Ok, get_integrations
from app.shared import db
from app.shared.cache import get_redis
from app.shared.errors import AppError, not_found

log = structlog.get_logger(__name__)
CACHE_PREFIX = "scc:gov-contracts:"
CACHE_TTL_SECONDS = 3600
type ContractStatus = Literal["IN_PROGRESS", "EXECUTED", "TERMINATED"]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GovContractOut(Camel):
    registry_number: str
    customer_name: str
    subject: str
    price_rub: int
    unpaid_rub: int
    concluded_at: date
    payment_deadline: date
    status: str


class Snapshot(Camel):
    items: list[GovContractOut]
    retrieved_at: datetime


class GovContractPage(Snapshot):
    next_cursor: str | None
    source: Literal["EIS"] = "EIS"


def _cached(key: str) -> Snapshot | None:
    try:
        raw = get_redis().get(key)
        return Snapshot.model_validate_json(raw) if isinstance(raw, str) else None
    except (RedisError, ValidationError):
        log.warning("gov_contracts_cache_read_failed")
        return None


def _snapshot(company_id: UUID, inn: str) -> Snapshot:
    key = CACHE_PREFIX + str(company_id)
    cached = _cached(key)
    if cached is not None:
        return cached
    result = get_integrations().tax.get_gov_contracts(inn)
    if not isinstance(result, Ok):
        raise AppError(503, "SERVICE_UNAVAILABLE", "Не удалось получить список госконтрактов")
    items = [
        GovContractOut(
            registry_number=item.registry_number,
            customer_name=item.customer_name,
            subject=item.subject,
            price_rub=item.price_rub,
            unpaid_rub=max(0, item.price_rub - item.paid_rub),
            concluded_at=item.concluded_at,
            payment_deadline=item.payment_deadline,
            status=item.status,
        )
        for item in result.data
    ]
    items.sort(key=lambda item: (item.concluded_at, item.registry_number), reverse=True)
    snapshot = Snapshot(items=items, retrieved_at=result.snapshot_meta.retrieved_at)
    try:
        get_redis().set(key, snapshot.model_dump_json(by_alias=True), ex=CACHE_TTL_SECONDS)
    except RedisError:
        log.warning("gov_contracts_cache_write_failed")
    return snapshot


def list_for(
    principal: auth.Principal,
    company_id: UUID,
    limit: int,
    cursor: str | None,
    status: ContractStatus | None,
) -> GovContractPage:
    with db.transaction() as session:
        company = session.get(Company, company_id)
        member = principal.membership(company_id)
        if company is None or member is None or member.role == "GUARANTOR":
            raise not_found("Компания")
        inn = company.inn
    snapshot = _snapshot(company_id, inn)
    items = [item for item in snapshot.items if status is None or item.status == status]
    if cursor is not None:
        position = next((i for i, item in enumerate(items) if item.registry_number == cursor), None)
        if position is None:
            raise AppError(422, "VALIDATION_ERROR", "Курсор не относится к списку контрактов")
        items = items[position + 1 :]
    return GovContractPage(
        items=items[:limit],
        next_cursor=items[limit - 1].registry_number if len(items) > limit else None,
        retrieved_at=snapshot.retrieved_at,
    )
