"""Банковские ручки: только банковская cookie, отдельные модели (T-360)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.modules.applications import Status
from app.modules.backoffice import card, service
from app.modules.backoffice.card_schemas import BankApplicationCard
from app.modules.backoffice.schemas import BankQueuePage, ProductCode

router = APIRouter(prefix="/backoffice", tags=["банк"])


@router.get(
    "/queue",
    operation_id="getBackofficeQueue",
    summary="Очередь ручного рассмотрения, старые сверху",
    response_model=BankQueuePage,
    response_model_by_alias=True,
    responses={
        401: {"description": "UNAUTHENTICATED"},
        403: {"description": "FORBIDDEN"},
        422: {"description": "VALIDATION_ERROR: фильтр или курсор"},
    },
)
async def queue(
    principal: auth.BankPrincipal,
    status: Status = Status.MANUAL_REVIEW,
    product_code: Annotated[ProductCode | None, Query(alias="productCode")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> BankQueuePage:
    return await run_in_threadpool(
        service.queue, principal, status.value, product_code, limit, cursor
    )


@router.get(
    "/applications/{application_id}",
    operation_id="getBackofficeApplication",
    summary="Полная карточка для сотрудника банка",
    response_model=BankApplicationCard,
    response_model_by_alias=True,
    responses={
        401: {"description": "UNAUTHENTICATED"},
        403: {"description": "FORBIDDEN"},
        404: {"description": "NOT_FOUND"},
        422: {"description": "VALIDATION_ERROR"},
    },
)
async def application_card(
    application_id: UUID,
    principal: auth.BankPrincipal,
    expected_version: Annotated[int | None, Query(alias="expectedVersion", ge=1)] = None,
) -> BankApplicationCard:
    return await run_in_threadpool(card.card, principal, application_id, expected_version)
