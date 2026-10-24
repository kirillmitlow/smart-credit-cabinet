"""Сценарии заявки: создание, черновик, отправка, переходы (T-250…T-254, R7: транзакцию держит вызывающий).

Статус меняется только здесь и только «сравнить и поменять»: UPDATE … WHERE status=:from AND
version=:v. Ноль строк — 409, а не тихая порча (R5, 20-02).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Sequence, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules import auth, notifications
from app.modules.applications.models import Application, ApplicationEvent, ApplicationVersion
from app.modules.applications.states import CLIENT_ACTIONS, TERMINAL, Actor, Status, is_allowed
from app.shared import clock, db
from app.shared.errors import AppError, not_found
from app.shared.tasks import enqueue

NUMBER_SEQUENCE = Sequence("application_number_seq")
PIPELINE_TASK = "pipeline.run"

# Проверки перед отправкой, которые добавляют другие подмодули (согласия T-260 и т.п.):
# функция поднимает AppError, если отправлять нельзя. Регистрация вместо импорта вверх (R10).
SubmitCheck = Callable[[Session, Application, auth.Principal], None]
_submit_checks: list[SubmitCheck] = []


def register_submit_check(check: SubmitCheck) -> None:
    _submit_checks.append(check)


def record_event(
    session: Session,
    application: Application,
    kind: str,
    *,
    actor_type: Actor,
    actor_id: UUID | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    step_code: str | None = None,
    reason_code: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ApplicationEvent:
    """Единственный способ писать в журнал заявки. В payload — без персональных данных."""
    event = ApplicationEvent(
        application_id=application.id,
        kind=kind,
        from_status=from_status,
        to_status=to_status,
        step_code=step_code,
        actor_type=actor_type.value,
        actor_id=actor_id,
        reason_code=reason_code,
        payload=payload or {},
        request_id=structlog.contextvars.get_contextvars().get("requestId"),
    )
    session.add(event)
    session.flush()
    event_id, company_id = event.id, application.company_id
    db.after_commit(session, lambda: notifications.publish(event_id, company_id))
    return event


def transition(
    session: Session,
    application: Application,
    target: Status,
    *,
    actor: Actor,
    actor_id: UUID | None = None,
    reason_code: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Application:
    """Перевести заявку; недопустимый переход или гонка — 409 INVALID_TRANSITION."""
    source = Status(application.status)
    if not is_allowed(source, target, actor):
        raise AppError(
            409,
            "INVALID_TRANSITION",
            f"Переход {source} → {target} недопустим",
            errors=[{"currentStatus": source.value}],
        )
    now = clock.now()
    values: dict[str, Any] = {
        "status": target.value,
        "version": application.version + 1,
        "updated_at": now,
    }
    if target is Status.SUBMITTED:
        values["submitted_at"] = now
    if target in TERMINAL:
        values["closed_at"] = now
    result = session.execute(
        update(Application)
        .where(
            Application.id == application.id,
            Application.status == source.value,
            Application.version == application.version,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.refresh(application)
        raise AppError(
            409,
            "INVALID_TRANSITION",
            "Заявку уже изменили, обновите страницу",
            errors=[{"currentStatus": application.status}],
        )
    session.refresh(application)
    record_event(
        session,
        application,
        "TRANSITION",
        actor_type=actor,
        actor_id=actor_id,
        from_status=source.value,
        to_status=target.value,
        reason_code=reason_code,
        payload=payload,
    )
    return application


def _next_number(session: Session) -> str:
    value = session.execute(NUMBER_SEQUENCE.next_value()).scalar_one()
    return f"АЗ-{clock.today().year}-{value:06d}"


def _require_member(principal: auth.Principal, company_id: UUID | None) -> UUID:
    if company_id is None or not principal.can_access(company_id):
        raise not_found("Компания")
    return company_id


def create(session: Session, principal: auth.Principal, fields: dict[str, Any]) -> Application:
    company_id = _require_member(principal, principal.active_company_id)
    member = principal.membership(company_id)
    if member is None or member.role == "GUARANTOR":
        raise AppError(403, "FORBIDDEN", "Поручитель не создаёт заявки")
    application = Application(
        number=_next_number(session),
        company_id=company_id,
        created_by=principal.user_id,
        status=Status.DRAFT.value,
        version=1,
        draft={},
        flags=[],
        **fields,
    )
    session.add(application)
    session.flush()
    return application


def get_for(session: Session, principal: auth.Principal, application_id: UUID) -> Application:
    """Чужая и несуществующая заявка неразличимы: 404 (R11)."""
    application = session.get(Application, application_id)
    if application is None or not principal.can_access(application.company_id):
        raise not_found("Заявка")
    return application


def list_for(
    session: Session, principal: auth.Principal, limit: int, cursor: str | None
) -> tuple[list[Application], str | None]:
    company_ids = [m.company_id for m in principal.memberships]
    query = select(Application).where(Application.company_id.in_(company_ids))
    if cursor:
        query = query.where(Application.id < UUID(cursor))
    rows = list(session.scalars(query.order_by(Application.id.desc()).limit(limit + 1)))
    next_cursor = str(rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], next_cursor


def allowed_actions(application: Application, principal: auth.Principal) -> list[str]:
    member = principal.membership(application.company_id)
    if member is None or member.role == "GUARANTOR":
        return []
    actions = list(CLIENT_ACTIONS.get(Status(application.status), ()))
    if "SIGN" in actions and member.role != "DIRECTOR":
        actions.remove("SIGN")
        actions.append("PASS_TO_DIRECTOR")
    return actions


DRAFT_FIELDS = ("product_code", "amount_rub", "term_months", "purpose_code")


def validate_collateral(answers: dict[str, Any]) -> None:
    raw = answers.get("collateral")
    if raw is None:
        return
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("description"), str)
        or not 1 <= len(raw["description"].strip()) <= 500
        or type(raw.get("valueRub")) is not int
        or not 0 < raw["valueRub"] <= 1_000_000_000
    ):
        raise AppError(
            422, "INVALID_COLLATERAL", "Укажите описание залога и положительную стоимость в рублях"
        )


def update_draft(
    session: Session,
    application: Application,
    version: int,
    fields: dict[str, Any],
    answers: dict[str, Any],
) -> Application:
    if application.status != Status.DRAFT.value:
        raise AppError(
            409,
            "INVALID_TRANSITION",
            "Черновик уже отправлен",
            errors=[{"currentStatus": application.status}],
        )
    if application.version != version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "Черновик изменён в другой вкладке",
            errors=[{"version": application.version}],
        )
    validate_collateral(answers)
    values: dict[str, Any] = {k: v for k, v in fields.items() if k in DRAFT_FIELDS}
    values["draft"] = {**application.draft, **answers}
    values["version"] = application.version + 1
    values["updated_at"] = clock.now()
    result = session.execute(
        update(Application)
        .where(Application.id == application.id, Application.version == version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.refresh(application)
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "Черновик изменён в другой вкладке",
            errors=[{"version": application.version}],
        )
    session.refresh(application)
    return application


def _snapshot(application: Application) -> dict[str, Any]:
    return {
        "productCode": application.product_code,
        "amountRub": application.amount_rub,
        "termMonths": application.term_months,
        "purposeCode": application.purpose_code,
        "draft": application.draft,
    }


def submit(session: Session, principal: auth.Principal, application: Application) -> Application:
    validate_collateral(application.draft)
    missing = [
        f for f in ("product_code", "amount_rub", "term_months") if getattr(application, f) is None
    ]
    if missing:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Заполните условия заявки",
            errors=[{"loc": ["body", f], "msg": "Field required"} for f in missing],
        )
    for check in _submit_checks:
        check(session, application, principal)
    data = _snapshot(application)
    data_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    try:
        with session.begin_nested():
            transition(
                session,
                application,
                Status.SUBMITTED,
                actor=Actor.CLIENT,
                actor_id=principal.user_id,
            )
    except IntegrityError as exc:
        raise AppError(409, "DUPLICATE_APPLICATION", "У компании уже есть заявка в работе") from exc
    version = ApplicationVersion(
        application_id=application.id, number=1, reason="SUBMIT", data=data, data_hash=data_hash
    )
    session.add(version)
    session.flush()
    application.current_version_id = version.id
    session.flush()
    enqueue(session, PIPELINE_TASK, application_id=str(application.id))
    return application


def current_version(session: Session, application: Application) -> ApplicationVersion | None:
    if application.current_version_id is None:
        return None
    return session.get(ApplicationVersion, application.current_version_id)


def add_version(
    session: Session,
    application: Application,
    reason: str,
    *,
    data_patch: dict[str, Any] | None = None,
) -> ApplicationVersion:
    """Новая неизменяемая версия заявки (`INFO_PROVIDED`, `COLLATERAL_ADDED`) на основе текущей.

    Данные копируются из текущей версии, поверх них кладётся `data_patch` (верхний уровень).
    Транзакцию держит вызывающий (R7); версия сразу становится текущей.
    """
    previous = current_version(session, application)
    if previous is None:
        raise AppError(409, "INVALID_TRANSITION", "У заявки нет отправленной версии")
    data = {**previous.data, **(data_patch or {})}
    data_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    last_number = session.scalar(
        select(func.max(ApplicationVersion.number)).where(
            ApplicationVersion.application_id == application.id
        )
    )
    version = ApplicationVersion(
        application_id=application.id,
        number=(last_number or 0) + 1,
        reason=reason,
        data=data,
        data_hash=data_hash,
    )
    session.add(version)
    session.flush()
    application.current_version_id = version.id
    session.flush()
    return version


def withdraw(session: Session, principal: auth.Principal, application: Application) -> Application:
    from app.modules.applications import client_tasks  # отложенно: client_tasks импортирует service

    transition(
        session, application, Status.WITHDRAWN, actor=Actor.CLIENT, actor_id=principal.user_id
    )
    client_tasks.cancel_open_tasks(
        session,
        application,
        reason="APPLICATION_WITHDRAWN",
        actor=Actor.CLIENT,
        actor_id=principal.user_id,
    )
    return application
