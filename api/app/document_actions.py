"""Composition across application/auth/document boundaries, as in app.wiring (R1/R5).

Lower documents storage never imports application, auth or audit modules. All effects share
the caller's transaction; HTTP operation fences hold the company lock throughout upload.
"""

from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import wraps
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.modules import applications, audit, auth, companies, documents
from app.modules.documents.uploads import Upload
from app.shared import db, idempotency, tasks
from app.shared.errors import AppError


def file_boundary[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    """A traceback with locals can expose source bytes; log only an error type at this boundary."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return function(*args, **kwargs)
        except AppError:
            raise
        except Exception as exc:
            structlog.get_logger("documents").error(
                "document_operation_failed", error_type=type(exc).__name__
            )
            raise AppError(
                500, "DOCUMENT_OPERATION_FAILED", "Не удалось обработать документ"
            ) from None

    return wrapped


def fresh_principal(session: Session, principal: auth.Principal) -> auth.Principal:
    user = auth.get(session, principal.user_id)
    if user is None or user.status != "ACTIVE":
        raise AppError(401, "UNAUTHENTICATED", "Нужно войти")
    if user.role != principal.role:
        raise AppError(403, "FORBIDDEN", "Права пользователя изменились, войдите заново")
    memberships = tuple(
        auth.Membership(member.company_id, member.role, frozenset(member.poa_permissions))
        for member, _ in companies.memberships_of(session, principal.user_id)
    )
    return replace(principal, memberships=memberships)


def access_for(principal: auth.Principal) -> documents.Access:
    return documents.Access(
        principal.user_id,
        tuple(m.company_id for m in principal.memberships if m.role != "GUARANTOR"),
        bank=principal.zone is auth.Zone.BANK and principal.role in {"UNDERWRITER", "ADMIN"},
    )


@file_boundary
def upload(principal: auth.Principal, data: Upload, key: str) -> idempotency.Reply:
    try:
        application_id = UUID(data.fields["applicationId"])
        task_id = UUID(data.fields["taskId"]) if data.fields.get("taskId") else None
        replaces_id = UUID(data.fields["replacesId"]) if data.fields.get("replacesId") else None
        kind = data.fields["kind"]
    except (KeyError, ValueError) as exc:
        raise AppError(422, "INVALID_UPLOAD", "Укажите заявку, вид документа и задачу") from exc
    with db.transaction() as session:
        principal = fresh_principal(session, principal)
        context = applications.document_upload_context(session, principal, application_id, task_id)
        access = access_for(principal)

        def save() -> idempotency.Reply:
            row = documents.store(
                session,
                access,
                context,
                content=bytes(data.content),
                filename=data.filename,
                kind=kind,
                replaces_id=replaces_id,
            )
            application = applications.get_for(session, principal, application_id)
            applications.record_event(
                session,
                application,
                "STEP",
                actor_type=applications.Actor.CLIENT,
                actor_id=principal.user_id,
                step_code="FILE_UPLOADED",
                payload={"documentId": str(row.id), "kind": kind},
            )
            audit.record(
                session,
                "FILE_UPLOADED",
                actor_id=principal.user_id,
                actor_role=principal.role,
                object_type="document",
                object_id=str(row.id),
                company_id=context.company_id,
                details={"sha256": row.sha256, "sizeBytes": row.size_bytes, "kind": kind},
            )
            if kind == "BANK_STATEMENT_1C":
                tasks.enqueue(session, "documents.parse_statement", document_id=str(row.id))
            return idempotency.Reply(201, documents.as_dict(row))

        import hashlib

        return idempotency.run_once(
            session,
            scope=f"documents:{context.company_id}:{application_id}:{principal.user_id}",
            key=key,
            request={
                **data.fields,
                "filename": data.filename,
                "sha256": hashlib.sha256(data.content).hexdigest(),
            },
            action=save,
        )


@file_boundary
def metadata(principal: auth.Principal, document_id: UUID) -> dict[str, Any]:
    with db.transaction() as session:
        principal = fresh_principal(session, principal)
        return documents.as_dict(
            documents.get_metadata(session, access_for(principal), document_id)
        )


@file_boundary
def download(principal: auth.Principal, document_id: UUID) -> tuple[dict[str, Any], bytes]:
    with db.transaction() as session:
        principal = fresh_principal(session, principal)
        row, content = documents.verified_content(session, access_for(principal), document_id)
        audit.record(
            session,
            "FILE_DOWNLOADED",
            actor_id=principal.user_id,
            actor_role=principal.role,
            object_type="document",
            object_id=str(row.id),
            company_id=row.company_id,
            details={"sha256": row.sha256},
        )
        return documents.as_dict(row), content


@file_boundary
def list_for(principal: auth.Principal, application_id: UUID) -> list[dict[str, Any]]:
    with db.transaction() as session:
        principal = fresh_principal(session, principal)
        applications.get_for(session, principal, application_id)
        return [
            documents.as_dict(row)
            for row in documents.list_metadata(session, access_for(principal), application_id)
        ]


@file_boundary
def confirm_statement(
    principal: auth.Principal, document_id: UUID, sha256: str, months: Mapping[str, int], key: str
) -> idempotency.Reply:
    with db.transaction() as session:
        principal = fresh_principal(session, principal)
        access = access_for(principal)
        row = documents.get_metadata(session, access, document_id)
        context = applications.document_confirmation_context(
            session, principal, row.application_id, row.task_id
        )
        company = companies.by_id(session, context.company_id)
        if company is None:
            raise AppError(404, "NOT_FOUND", "Компания не найдена")
        inn = company.inn

        def save() -> idempotency.Reply:
            confirmed, created = documents.confirm_statement(
                session, access, document_id, inn=inn, sha256=sha256, months=months
            )
            if created:
                application = applications.get_for(session, principal, context.application_id)
                applications.record_event(
                    session,
                    application,
                    "STEP",
                    actor_type=applications.Actor.CLIENT,
                    actor_id=principal.user_id,
                    step_code="STATEMENT_CONFIRMED",
                    payload={"documentId": str(document_id)},
                )
                audit.record(
                    session,
                    "STATEMENT_CONFIRMED",
                    actor_id=principal.user_id,
                    actor_role=principal.role,
                    object_type="document",
                    object_id=str(document_id),
                    company_id=context.company_id,
                    details={"sha256": sha256},
                )
            return idempotency.Reply(200, documents.as_dict(confirmed))

        return idempotency.run_once(
            session,
            scope=f"documents:confirm:{document_id}:{principal.user_id}",
            key=key,
            request={"sha256": sha256, "months": dict(months)},
            action=save,
        )
