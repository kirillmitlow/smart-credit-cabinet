"""Бизнес-API mock-credit-bureau (раздел 6): отчёты, чтение снимка, сведения банка.

Роль подключает себя сама (main.py ищет `router` и `admin_router`). Порядок обработки запроса
(8.2): chaos → ключ API → идемпотентность → обработчик; проверки тела и согласия идут в обработчике.
"""

from __future__ import annotations

from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse

from app.common.auth import require_api_key
from app.common.db import Session
from app.common.idempotency import IdempotencyDep, OptionalIdempotencyDep
from app.common.problems import ProblemException
from app.common.schemas import build_meta, problem_responses
from app.roles.bki import models, service
from app.roles.bki import schemas as s
from app.roles.bki.admin import admin_router
from app.roles.bki.config import BkiSettings

__all__ = ["admin_router", "router"]

router = APIRouter(
    prefix="/api/v1", tags=["mock-credit-bureau"], dependencies=[Depends(require_api_key)]
)


def _settings(request: Request) -> BkiSettings:
    cached = getattr(request.app.state, "bki_settings", None)
    if not isinstance(cached, BkiSettings):
        cached = BkiSettings()
        request.app.state.bki_settings = cached
    return cached


def _with_meta(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    meta = build_meta(request, "CREDIT_BUREAU", request.app.state.clock.today())
    return {"meta": meta.model_dump(mode="json", by_alias=True), **body}


@router.post(
    "/credit-reports",
    summary="Запросить кредитный отчёт",
    description=(
        "Требует согласие субъекта; запрос всегда оставляет след в истории запросов, в том числе "
        "при `NOT_FOUND`. Необязательный `Idempotency-Key`: повтор вернёт тот же отчёт и не "
        "запишет второй запрос. Значения «на сегодня» (дни просрочки, корзины, `summary`) "
        "считаются при каждом запросе из дат и периодов (6.4)."
    ),
    operation_id="requestCreditReport",
    response_model=s.CreditReport,
    responses=problem_responses(400, 401, 403, 409, 422, 429, 503),
)
async def request_credit_report(
    request: Request, body: s.CreditReportRequest, session: Session, idem: OptionalIdempotencyDep
) -> Response:
    clock = request.app.state.clock

    async def handle() -> Response:
        service.check_subject(body.subject)
        consent = service.check_consent(body.consent, body.subject.inn, body.purpose, clock)
        snapshot = await service.issue_report(
            session,
            body,
            consent,
            clock=clock,
            settings=_settings(request),
            idempotency_key=idem.key,
        )
        return JSONResponse(_with_meta(request, snapshot))

    return await idem.run(handle)


@router.get(
    "/credit-reports/{reportId}",
    summary="Ранее выданный отчёт (снимок на момент выдачи)",
    description=(
        "Нового запроса в историю не пишет. Дни просрочки не пересчитываются: "
        "отдаётся ровно то, что было выдано."
    ),
    operation_id="getCreditReport",
    response_model=s.CreditReport,
    responses=problem_responses(401, 403, 404, 429, 503),
)
async def get_credit_report(
    request: Request,
    reportId: Annotated[str, Path(max_length=64, description="Идентификатор отчёта, `rep_…`")],  # noqa: N803
    session: Session,
) -> Response:
    snapshot = await session.scalar(
        sa.select(models.Report.response).where(models.Report.id == reportId)
    )
    if snapshot is None:
        raise ProblemException(404, "REPORT_NOT_FOUND", f"Отчёт {reportId} не найден")
    return JSONResponse(_with_meta(request, snapshot))


@router.post(
    "/submissions",
    summary="Банк передаёт сведения в БКИ",
    description=(
        "События `APPLICATION_REGISTERED`, `APPLICATION_DECIDED`, `OBLIGATION_OPENED`, "
        "`OBLIGATION_CLOSED`. `Idempotency-Key` обязателен. Повтор события с тем же `eventId` "
        "(в том числе с другим ключом) возвращает исходный `202` с тем же `submissionId`; "
        "другое тело при том же `eventId` — `409 IDEMPOTENCY_KEY_REUSED`."
    ),
    operation_id="submitToBureau",
    status_code=202,
    response_model=s.SubmissionAccepted,
    responses=problem_responses(400, 401, 403, 404, 409, 422, 429, 503),
)
async def submit_to_bureau(
    request: Request, event: s.SubmissionEvent, session: Session, idem: IdempotencyDep
) -> Response:
    clock = request.app.state.clock

    async def handle() -> Response:
        service.check_subject(event.subject)
        raw = await request.json()
        submission_id = await service.accept_submission(session, event, raw, clock)
        return JSONResponse(
            _with_meta(request, {"submissionId": submission_id, "status": "ACCEPTED"}),
            status_code=202,
        )

    return await idem.run(handle)
