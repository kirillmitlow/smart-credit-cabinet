"""Application/task authorization remains with their owner; documents stays below applications."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import auth, documents
from app.modules.applications import client_tasks
from app.modules.applications.models import Application, Task
from app.modules.applications.service import get_for
from app.shared.errors import AppError, not_found


def _editable_application(
    session: Session, principal: auth.Principal, application_id: UUID
) -> Application:
    application = get_for(session, principal, application_id)
    session.refresh(application, with_for_update=True)
    member = principal.membership(application.company_id)
    if (
        principal.role != "CLIENT"
        or member is None
        or member.role == "GUARANTOR"
        or principal.active_company_id != application.company_id
    ):
        raise not_found("Заявка")
    if application.status not in {"DRAFT", "NEEDS_INFO"}:
        raise AppError(409, "INVALID_TRANSITION", "На этом этапе нельзя загрузить файл")
    return application


def document_upload_context(
    session: Session, principal: auth.Principal, application_id: UUID, task_id: UUID | None
) -> documents.UploadContext:
    application = _editable_application(session, principal, application_id)
    if task_id is not None:
        task = session.get(Task, task_id)
        if task is None or task.application_id != application_id:
            raise not_found("Задача")
        if task.status != "OPEN" or application.status != "NEEDS_INFO":
            raise AppError(409, "TASK_CLOSED", "Задача уже закрыта")
        if task.kind not in {"DOCUMENT", "CONFIRM_REVENUE"}:
            raise AppError(422, "TASK_NOT_DOCUMENT", "В этой задаче не нужен файл")
        if not client_tasks.can_answer(principal, application, task):
            raise AppError(403, "FORBIDDEN", "Этот файл должен предоставить другой участник")
    elif application.status == "NEEDS_INFO":
        raise AppError(422, "TASK_REQUIRED", "Выберите задачу для загрузки файла")
    return documents.UploadContext(application.company_id, application.id, task_id)


def document_confirmation_context(
    session: Session, principal: auth.Principal, application_id: UUID, task_id: UUID | None
) -> documents.UploadContext:
    if task_id is not None:
        return document_upload_context(session, principal, application_id, task_id)
    application = _editable_application(session, principal, application_id)
    if application.status == "NEEDS_INFO":
        tasks = session.scalars(
            select(Task).where(
                Task.application_id == application_id,
                Task.status == "OPEN",
            )
        )
        # Reuse a statement uploaded in DRAFT; its immutable task_id is not rewritten.
        if not any(
            (task.kind == "CONFIRM_REVENUE" or task.details.get("reasonCode") == "REVENUE_UNKNOWN")
            and client_tasks.can_answer(principal, application, task)
            for task in tasks
        ):
            raise AppError(409, "TASK_CLOSED", "Нет открытой задачи подтверждения выручки")
    return documents.UploadContext(application.company_id, application.id, task_id)


def statement_processing_context(
    session: Session, application_id: UUID, task_id: UUID | None
) -> Application | None:
    """Worker locks in the same order as upload; closed applications/tasks get no result."""
    application = session.get(Application, application_id, with_for_update=True)
    if application is None or application.status not in {"DRAFT", "NEEDS_INFO"}:
        return None
    if task_id is not None:
        task = session.get(Task, task_id)
        if (
            task is None
            or task.application_id != application_id
            or task.status != "OPEN"
            or application.status != "NEEDS_INFO"
        ):
            return None
    return application
