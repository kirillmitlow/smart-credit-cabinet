"""Thin HTTP composition: explicit client/bank sessions; streaming multipart has no full-body buffer."""

from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app import document_actions
from app.modules import auth
from app.modules.documents.limits import check_upload_limit
from app.modules.documents.uploads import read_upload
from app.modules.documents.validation import PDF_LIMIT
from app.shared.errors import AppError
from app.shared.settings import get_settings

router = APIRouter(prefix="/documents", tags=["документы"])


class DocumentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    companyId: UUID
    applicationId: UUID
    taskId: UUID | None
    kind: str
    origin: str
    filename: str
    mime: str
    sizeBytes: int
    sha256: str
    parseStatus: str
    parsed: dict[str, Any] | None
    parseError: str | None
    createdAt: str
    cancelledAt: str | None
    confirmedAt: str | None


def reader(request: Request, zone: Literal["client", "bank"] = "client") -> auth.Principal:
    return auth.current_bank(request) if zone == "bank" else auth.current_client(request)


@router.post(
    "",
    operation_id="uploadDocument",
    status_code=201,
    response_model=DocumentOut,
    summary="Загрузить исходный файл; содержимое неизменяемо",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["applicationId", "kind", "file"],
                        "properties": {
                            "applicationId": {"type": "string", "format": "uuid"},
                            "taskId": {"type": "string", "format": "uuid"},
                            "kind": {
                                "type": "string",
                                "enum": ["BANK_STATEMENT_1C", "FINANCIALS", "CONTRACT", "OTHER"],
                            },
                            "replacesId": {"type": "string", "format": "uuid"},
                            "file": {"type": "string", "format": "binary"},
                        },
                    }
                }
            },
        }
    },
)
async def upload_document(
    request: Request,
    principal: auth.ClientPrincipal,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
) -> JSONResponse:
    await run_in_threadpool(check_upload_limit, principal.session_id or str(principal.user_id))
    try:
        data = await read_upload(
            request, min(PDF_LIMIT, get_settings().upload_max_mb * 1024 * 1024)
        )
    except AppError:
        raise
    except ClientDisconnect:
        raise AppError(400, "UPLOAD_INTERRUPTED", "Загрузка прервана, повторите попытку") from None
    except Exception:
        # The generic application traceback can contain local source bytes; never send it there.
        raise AppError(500, "DOCUMENT_OPERATION_FAILED", "Не удалось прочитать загрузку") from None
    reply = await run_in_threadpool(document_actions.upload, principal, data, idempotency_key)
    return JSONResponse(
        reply.body,
        status_code=reply.status,
        headers={"Idempotent-Replayed": "true"} if reply.replayed else {},
    )


@router.get("/{document_id}", operation_id="getDocument", response_model=DocumentOut)
def get_document(
    document_id: UUID, principal: Annotated[auth.Principal, Depends(reader)]
) -> dict[str, Any]:
    return document_actions.metadata(principal, document_id)


@router.get(
    "/{document_id}/download",
    operation_id="downloadDocument",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            }
        }
    },
)
def download_document(
    document_id: UUID, principal: Annotated[auth.Principal, Depends(reader)]
) -> Response:
    meta, content = document_actions.download(principal, document_id)
    disposition = "attachment; filename=\"document\"; filename*=UTF-8''" + quote(
        meta["filename"], safe=""
    )
    return Response(
        content,
        media_type=meta["mime"],
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
