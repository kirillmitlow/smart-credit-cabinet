"""T-363: команда банка и её версия/ключ передаются сервису без бизнес-логики."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Response
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.modules.backoffice import info_service
from app.modules.backoffice.info_schemas import (
    BankInfoRequest,
    BankInfoRequested,
    BankRecheckRequest,
    BankRecheckStarted,
)

router = APIRouter(prefix="/applications")
ActionKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"^\S+$")
]
_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "UNAUTHENTICATED"},
    403: {"description": "FORBIDDEN"},
    404: {"description": "NOT_FOUND"},
    409: {
        "description": "VERSION_CONFLICT / INVALID_TRANSITION / ROUND_OPEN / ROUNDS_LIMIT_REACHED / "
        "RECHECK_ALREADY_RUNNING / IDEMPOTENCY_KEY_REUSED / IDEMPOTENCY_IN_PROGRESS / DEMO_RESET_IN_PROGRESS"
    },
    422: {"description": "VALIDATION_ERROR"},
}


@router.post(
    "/{application_id}/request-info",
    operation_id="requestBackofficeInformation",
    summary="Запросить сведения у клиента",
    response_model=BankInfoRequested,
    response_model_by_alias=True,
    responses=_ERRORS,
)
async def request_info(
    application_id: UUID,
    body: BankInfoRequest,
    principal: auth.BankPrincipal,
    response: Response,
    idempotency_key: ActionKey,
) -> BankInfoRequested:
    result = await run_in_threadpool(
        info_service.request_info, principal, application_id, body, idempotency_key
    )
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return BankInfoRequested.model_validate(result.body)


@router.post(
    "/{application_id}/recheck",
    operation_id="recheckBackofficeApplication",
    summary="Повторно проверить источники заявки",
    response_model=BankRecheckStarted,
    response_model_by_alias=True,
    responses=_ERRORS,
)
async def recheck(
    application_id: UUID,
    body: BankRecheckRequest,
    principal: auth.BankPrincipal,
    response: Response,
    idempotency_key: ActionKey,
) -> BankRecheckStarted:
    result = await run_in_threadpool(
        info_service.recheck, principal, application_id, body, idempotency_key
    )
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return BankRecheckStarted.model_validate(result.body)
