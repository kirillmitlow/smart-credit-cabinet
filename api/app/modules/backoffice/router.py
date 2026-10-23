"""Банковские ручки: только банковская cookie, отдельные модели (T-360)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.modules.applications import Status
from app.modules.backoffice import card, decision_service, manual_service, outbox_service, service
from app.modules.backoffice.card_schemas import BankApplicationCard
from app.modules.backoffice.decision_schemas import BankDecisionRequest, BankDecisionSaved
from app.modules.backoffice.info_router import router as info_router
from app.modules.backoffice.manual_schemas import BankOfferEvaluation, BankOfferEvaluationRequest
from app.modules.backoffice.outbox_schemas import (
    BankOutboxPage,
    BankOutboxRetried,
    BankOutboxRetryRequest,
)
from app.modules.backoffice.schemas import BankQueuePage, ProductCode

router = APIRouter(prefix="/backoffice", tags=["банк"])
router.include_router(info_router)


@router.post(
    "/applications/{application_id}/evaluate-offer",
    operation_id="evaluateBackofficeOffer",
    summary="Проверить ручные условия без сохранения",
    response_model=BankOfferEvaluation,
    response_model_by_alias=True,
    responses={
        401: {"description": "UNAUTHENTICATED"},
        403: {"description": "FORBIDDEN"},
        404: {"description": "NOT_FOUND"},
        409: {
            "description": "VERSION_CONFLICT / INVALID_TRANSITION / ENGINE_DECISION_STALE / DEMO_RESET_IN_PROGRESS"
        },
        422: {"description": "VALIDATION_ERROR"},
    },
)
async def evaluate_offer(
    application_id: UUID,
    body: BankOfferEvaluationRequest,
    principal: auth.BankPrincipal,
) -> BankOfferEvaluation:
    return await run_in_threadpool(manual_service.evaluate, principal, application_id, body)


@router.post(
    "/applications/{application_id}/decision",
    operation_id="saveBackofficeDecision",
    summary="Сохранить решение сотрудника банка",
    response_model=BankDecisionSaved,
    response_model_by_alias=True,
    responses={
        401: {"description": "UNAUTHENTICATED"},
        403: {"description": "FORBIDDEN / AUTHORITY_LEVEL_TOO_LOW"},
        404: {"description": "NOT_FOUND"},
        409: {
            "description": "VERSION_CONFLICT / INVALID_TRANSITION / ENGINE_DECISION_STALE / "
            "ENGINE_DECISION_MISSING / ENGINE_SNAPSHOT_INCOMPATIBLE / ENGINE_SNAPSHOT_MISMATCH / "
            "IDEMPOTENCY_KEY_REUSED / IDEMPOTENCY_IN_PROGRESS / DEMO_RESET_IN_PROGRESS"
        },
        422: {"description": "VALIDATION_ERROR / UNDERWRITER_DECISION_INVALID"},
    },
)
async def save_decision(
    application_id: UUID,
    body: BankDecisionRequest,
    principal: auth.BankPrincipal,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"^\S+$")
    ],
) -> BankDecisionSaved:
    result = await run_in_threadpool(
        decision_service.decide, principal, application_id, body, idempotency_key
    )
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return BankDecisionSaved.model_validate(result.body)


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


@router.get(
    "/outbox",
    operation_id="listBackofficeOutbox",
    summary="Застрявшие сообщения",
    response_model=BankOutboxPage,
    response_model_by_alias=True,
    responses={
        401: {"description": "UNAUTHENTICATED"},
        403: {"description": "FORBIDDEN"},
        422: {"description": "VALIDATION_ERROR"},
    },
)
async def failed_outbox(
    principal: auth.BankPrincipal,
    application_id: Annotated[UUID | None, Query(alias="applicationId")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(pattern=r"^[1-9]\d{0,18}$")] = None,
) -> BankOutboxPage:
    return await run_in_threadpool(outbox_service.failed, principal, application_id, limit, cursor)


@router.post(
    "/outbox/{message_id}/retry",
    operation_id="retryBackofficeOutbox",
    summary="Поставить сообщение на повтор",
    response_model=BankOutboxRetried,
    response_model_by_alias=True,
    responses={
        401: {"description": "UNAUTHENTICATED"},
        403: {"description": "FORBIDDEN"},
        404: {"description": "NOT_FOUND"},
        409: {
            "description": "OUTBOX_NOT_FAILED / OUTBOX_RETRY_EXPIRED / IDEMPOTENCY_IN_PROGRESS / DEMO_RESET_IN_PROGRESS"
        },
        422: {"description": "VALIDATION_ERROR"},
    },
)
async def retry_outbox(
    message_id: int,
    principal: auth.BankPrincipal,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"^\S+$")
    ],
    body: BankOutboxRetryRequest | None = None,
) -> BankOutboxRetried:
    result = await run_in_threadpool(outbox_service.retry, principal, message_id, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return BankOutboxRetried.model_validate(result.body)
