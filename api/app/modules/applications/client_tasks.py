"""Задачи клиенту: создание раунда, ответ и отправка раунда (T-350, T-351, 20-03).

Все функции работают в транзакции вызывающего (R7): задачи, события `TASK` и переход статуса
либо появляются вместе, либо не появляются. Раундов не больше трёх (D-091, Q-127): затем заявку
обязан решить андеррайтер. Перепроверку после ответа запускает `pipeline.request_recheck`; чтобы
не импортировать вышестоящий модуль (R1), конвейер регистрирует её через `register_recheck`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules import auth, companies, documents
from app.modules.applications.models import TASK_KINDS, Application, Task
from app.modules.applications.service import get_for, record_event, transition
from app.modules.applications.states import Actor, Status
from app.shared import clock
from app.shared.errors import AppError, not_found
from app.shared.settings import get_settings

MAX_ROUNDS = 3
MAX_TASKS_PER_ROUND = 10
ANSWER_TIMEOUT = timedelta(days=5)  # демо-значение 20-02; заполняется только при включённом таймере

RecheckFn = Callable[..., Any]
_recheck: RecheckFn | None = None


def register_recheck(fn: RecheckFn) -> None:
    """Конвейер подключает `request_recheck` (регистрация вместо импорта вверх, R10)."""
    global _recheck
    _recheck = fn


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Что просим у клиента. Исполнитель: `assignee_person_inn` (поручитель), `assignee_user_id`
    (участник компании) либо пусто (любой участник, кроме поручителя)."""

    kind: str
    title: str
    why_text: str
    details: dict[str, Any] = field(default_factory=dict)  # «что именно», «где взять»
    assignee_user_id: UUID | None = None
    assignee_person_inn: str | None = None


@dataclass(frozen=True, slots=True)
class InfoRequestReceipt:
    application_id: UUID
    round: int
    task_ids: tuple[UUID, ...]
    status: str
    application_version: int


def _lock(session: Session, application_id: UUID) -> Application:
    application = session.scalars(
        select(Application).where(Application.id == application_id).with_for_update()
    ).first()
    if application is None:
        raise not_found("Заявка")
    return application


def _rounds(session: Session, application_id: UUID) -> tuple[int, int]:
    """(последний раунд, сколько в нём открытых задач)."""
    last = session.scalar(select(func.max(Task.round)).where(Task.application_id == application_id))
    if last is None:
        return 0, 0
    open_count = session.scalar(
        select(func.count()).where(
            Task.application_id == application_id, Task.round == last, Task.status == "OPEN"
        )
    )
    return last, int(open_count or 0)


def _validate(session: Session, application: Application, items: Sequence[TaskSpec]) -> None:
    errors: list[dict[str, Any]] = []
    if not 1 <= len(items) <= MAX_TASKS_PER_ROUND:
        errors.append({"loc": ["items"], "msg": f"Нужно от 1 до {MAX_TASKS_PER_ROUND} задач"})
    people = companies.people(session, application.company_id)
    for i, item in enumerate(items):
        if item.kind not in TASK_KINDS:
            errors.append({"loc": ["items", i, "kind"], "msg": "Неизвестный тип задачи"})
        if not item.title.strip() or len(item.title) > 200:
            errors.append({"loc": ["items", i, "title"], "msg": "Заголовок 1–200 символов"})
        if not item.why_text.strip():
            errors.append({"loc": ["items", i, "whyText"], "msg": "Нужно пояснить, зачем"})
        if item.assignee_user_id is not None and not any(
            p.user_id == item.assignee_user_id and p.role != "GUARANTOR" for p in people
        ):
            errors.append({"loc": ["items", i, "assigneeUserId"], "msg": "Нет такого участника"})
        if item.assignee_person_inn is not None and not any(
            p.person_inn == item.assignee_person_inn for p in people
        ):
            errors.append({"loc": ["items", i, "assigneePersonInn"], "msg": "Нет такого человека"})
    if errors:
        raise AppError(422, "VALIDATION_ERROR", "Проверьте задачи", errors=errors)


def request_information(
    session: Session,
    application_id: UUID,
    *,
    expected_version: int,
    actor: Actor,
    actor_id: UUID | None = None,
    items: Sequence[TaskSpec],
    reason_code: str | None = None,
) -> InfoRequestReceipt:
    """Создать новый раунд задач клиенту и вернуть заявку в `NEEDS_INFO`.

    `Actor.UNDERWRITER`: из `MANUAL_REVIEW` в `NEEDS_INFO` (переход делается здесь).
    `Actor.SYSTEM` (конвейер): заявка уже в `NEEDS_INFO` после решения ядра, переход пропускается.
    Ошибки: 404; 409 `VERSION_CONFLICT`, `INVALID_TRANSITION`, `ROUND_OPEN` (прошлый раунд ещё
    не закрыт), `ROUNDS_LIMIT_REACHED` (уже три раунда, нужен ручной разбор); 422 при неверных
    задачах; 403, если вызывает не банк и не система.
    """
    if actor not in (Actor.UNDERWRITER, Actor.SYSTEM):
        raise AppError(403, "FORBIDDEN", "Запросить информацию может только банк")
    application = _lock(session, application_id)
    if application.version != expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "Заявку уже изменили, обновите страницу",
            errors=[{"version": application.version}],
        )
    status = Status(application.status)
    if actor is Actor.SYSTEM and status is not Status.NEEDS_INFO:
        raise AppError(
            409,
            "INVALID_TRANSITION",
            f"Переход {status} → {Status.NEEDS_INFO} недопустим",
            errors=[{"currentStatus": status.value}],
        )
    last_round, open_tasks = _rounds(session, application.id)
    if open_tasks:
        raise AppError(409, "ROUND_OPEN", "Предыдущий запрос клиенту ещё не закрыт")
    if last_round >= MAX_ROUNDS:
        raise AppError(
            409,
            "ROUNDS_LIMIT_REACHED",
            f"Уже {MAX_ROUNDS} раунда запросов: заявку нужно решить по имеющимся данным",
        )
    _validate(session, application, items)
    if actor is Actor.UNDERWRITER:
        transition(
            session,
            application,
            Status.NEEDS_INFO,
            actor=actor,
            actor_id=actor_id,
            reason_code=reason_code,
            payload={"round": last_round + 1},
        )
    expires_at = clock.now() + ANSWER_TIMEOUT if get_settings().expiry_enabled else None
    tasks: list[Task] = []
    for item in items:
        task = Task(
            application_id=application.id,
            round=last_round + 1,
            kind=item.kind,
            title=item.title.strip(),
            why_text=item.why_text.strip(),
            details=item.details,
            assignee_user_id=item.assignee_user_id,
            assignee_person_inn=item.assignee_person_inn,
            status="OPEN",
            expires_at=expires_at,
            created_by_actor=actor.value,
            created_by_id=actor_id,
        )
        session.add(task)
        tasks.append(task)
    session.flush()
    for task in tasks:
        record_event(
            session,
            application,
            "TASK",
            actor_type=actor,
            actor_id=actor_id,
            step_code="TASK_CREATED",
            reason_code=reason_code,
            payload={"taskId": str(task.id), "round": task.round, "kind": task.kind},
        )
    return InfoRequestReceipt(
        application.id,
        last_round + 1,
        tuple(t.id for t in tasks),
        application.status,
        application.version,
    )


# ---------------------------------------------------------------- клиент


def _member_role(principal: auth.Principal, application: Application) -> str:
    member = principal.membership(application.company_id)
    if member is None:
        raise not_found("Заявка")
    return member.role


def can_see(principal: auth.Principal, application: Application, task: Task) -> bool:
    role = _member_role(principal, application)
    if role == "GUARANTOR":
        return (
            task.assignee_person_inn is not None
            and task.assignee_person_inn == principal.person_inn
        )
    return True


def can_answer(principal: auth.Principal, application: Application, task: Task) -> bool:
    role = _member_role(principal, application)
    if task.assignee_person_inn is not None:  # задача поручителя: только он сам (D-096)
        return principal.person_inn == task.assignee_person_inn
    if role == "GUARANTOR":
        return False
    if task.assignee_user_id is not None:
        return principal.user_id == task.assignee_user_id or role == "DIRECTOR"
    return True


def list_tasks(
    session: Session, principal: auth.Principal, application_id: UUID
) -> tuple[Application, list[Task]]:
    application = get_for(session, principal, application_id)
    rows = session.scalars(
        select(Task)
        .where(Task.application_id == application.id)
        .order_by(Task.round, Task.created_at, Task.id)
    )
    return application, [t for t in rows if can_see(principal, application, t)]


def save_answer(session: Session, principal: auth.Principal, task_id: UUID, text: str) -> Task:
    """Черновик ответа (банк его не видит). Чужая компания — 404; чужая задача — 403;
    закрытая задача — 409 `TASK_CLOSED`. Файлы ждут хранилища (T-332, T-333, T-336)."""
    task = session.get(Task, task_id)
    if task is None:
        raise not_found("Задача")
    application = get_for(session, principal, task.application_id)  # чужая компания — 404
    if not can_see(principal, application, task):
        raise not_found("Задача")
    if not can_answer(principal, application, task):
        raise AppError(403, "FORBIDDEN", "Эту задачу выполняет другой участник")
    clean = text.strip()
    if not clean:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Ответ не может быть пустым",
            errors=[{"loc": ["body", "text"], "msg": "Field required"}],
        )
    result = session.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == "OPEN")
        .values(
            answer={"text": clean, "savedAt": clock.now().isoformat()},
            answered_by=principal.user_id,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise AppError(409, "TASK_CLOSED", "Задача уже закрыта")
    session.refresh(task)
    return task


def document_readiness(
    session: Session, principal: auth.Principal, application: Application, tasks: Sequence[Task]
) -> dict[UUID, bool]:
    """The read projection and submit guard use the same file/confirmation conditions."""
    document_tasks = [
        t for t in tasks if t.status == "OPEN" and t.kind in {"DOCUMENT", "CONFIRM_REVENUE"}
    ]
    ready = {t.id: True for t in tasks}
    if document_tasks:
        files = documents.list_metadata(
            session, documents.Access(principal.user_id, (application.company_id,)), application.id
        )
        attached_tasks = {f.task_id for f in files if f.cancelled_at is None}
        revenue_tasks = {
            t.id
            for t in document_tasks
            if t.kind == "CONFIRM_REVENUE" or t.details.get("reasonCode") == "REVENUE_UNKNOWN"
        }
        if revenue_tasks:
            company = companies.by_id(session, application.company_id)
            source = (
                documents.confirmed_statement_source(
                    session, application.id, application.company_id, company.inn
                )
                if company is not None
                else None
            )
            # A generic PDF or unconfirmed parsed statement cannot answer a revenue request.
            attached_tasks -= revenue_tasks
            if source is not None:
                attached_tasks |= revenue_tasks
        for task in document_tasks:
            ready[task.id] = task.id in attached_tasks
        unready_tasks = {
            f.task_id
            for f in files
            if f.cancelled_at is None
            and f.kind == "BANK_STATEMENT_1C"
            and f.parse_status != "PARSED"
        }
        for task in document_tasks:
            if task.id in unready_tasks:
                ready[task.id] = False
    return ready


def submit_round(
    session: Session, principal: auth.Principal, application_id: UUID
) -> tuple[Application, list[Task]]:
    """«Отправить ответ банку»: все задачи раунда в `ANSWERED`, версия `INFO_PROVIDED`,
    `NEEDS_INFO → CHECKING` и запуск проверки одной транзакцией.

    Ошибки: 404 чужая заявка; 403 поручитель; 409 `ROUND_INCOMPLETE` (не на все задачи есть
    ответ), `ROUND_ALREADY_SENT` (двойное нажатие), `INVALID_TRANSITION`.
    """
    application = get_for(session, principal, application_id)
    if _member_role(principal, application) == "GUARANTOR":
        raise AppError(403, "FORBIDDEN", "Поручитель не отправляет ответ за компанию")
    application = _lock(session, application_id)
    last_round, open_count = _rounds(session, application.id)
    status = Status(application.status)
    if last_round and open_count == 0 and status is not Status.NEEDS_INFO:
        raise AppError(409, "ROUND_ALREADY_SENT", "Ответ уже отправлен банку")
    if status is not Status.NEEDS_INFO or not open_count:
        raise AppError(
            409,
            "INVALID_TRANSITION",
            f"Переход {status} → {Status.CHECKING} недопустим",
            errors=[{"currentStatus": status.value}],
        )
    open_tasks = list(
        session.scalars(
            select(Task)
            .where(Task.application_id == application.id, Task.round == last_round)
            .where(Task.status == "OPEN")
            .order_by(Task.created_at, Task.id)
        )
    )
    missing = [t for t in open_tasks if t.answer is None]
    ready = document_readiness(session, principal, application, open_tasks)
    missing.extend(t for t in open_tasks if not ready[t.id] and t not in missing)
    if missing:
        raise AppError(
            409,
            "ROUND_INCOMPLETE",
            "Ответьте на все задачи, дождитесь разбора выписок и подтвердите поступления от бизнеса",
            errors=[{"taskId": str(t.id)} for t in missing],
        )
    if _recheck is None:
        raise RuntimeError("Перепроверка не подключена: нет pipeline.request_recheck")
    now = clock.now()
    for task in open_tasks:
        task.status = "ANSWERED"
        task.answered_at = now
        record_event(
            session,
            application,
            "TASK",
            actor_type=Actor.CLIENT,
            actor_id=principal.user_id,
            step_code="TASK_ANSWERED",
            payload={"taskId": str(task.id), "round": task.round, "kind": task.kind},
        )
    session.flush()
    _recheck(
        session,
        application.id,
        expected_version=application.version,
        actor=Actor.CLIENT,
        actor_id=principal.user_id,
        reason_code="INFO_PROVIDED",
        version_reason="INFO_PROVIDED",
        data_patch={"infoRound": last_round},
    )
    session.refresh(application)
    return application, open_tasks


def cancel_open_tasks(
    session: Session,
    application: Application,
    *,
    reason: str,
    actor: Actor,
    actor_id: UUID | None = None,
) -> int:
    """Закрыть открытые задачи заявки (`CANCELLED`): отзыв заявки, снятие банком."""
    rows = list(
        session.scalars(
            select(Task).where(Task.application_id == application.id, Task.status == "OPEN")
        )
    )
    for task in rows:
        task.status = "CANCELLED"
        task.cancel_reason = reason
        record_event(
            session,
            application,
            "TASK",
            actor_type=actor,
            actor_id=actor_id,
            step_code="TASK_CANCELLED",
            reason_code=reason,
            payload={"taskId": str(task.id), "round": task.round},
        )
    session.flush()
    return len(rows)
