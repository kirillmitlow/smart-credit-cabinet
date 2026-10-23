"""Application/task authorization remains with their owner; documents stays below applications."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules import auth, documents
from app.modules.applications import client_tasks
from app.modules.applications.models import Task
from app.modules.applications.service import get_for
from app.shared.errors import AppError, not_found


def document_upload_context(
    session: Session, principal: auth.Principal, application_id: UUID, task_id: UUID | None
) -> documents.UploadContext:
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
