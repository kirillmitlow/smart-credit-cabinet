"""Ручной толчок существующего сообщения: ключ получателя и окно24ч не меняются (T-365)."""

from uuid import UUID

from app.modules import applications, audit, auth
from app.modules.backoffice import queries
from app.modules.backoffice.outbox_schemas import BankOutboxItem, BankOutboxPage, BankOutboxRetried
from app.modules.backoffice.service import require_bank
from app.shared import clock, db, idempotency, operations, outbox, tasks
from app.shared.errors import AppError, not_found


def operation_scope(message_id: int) -> operations.Scope | None:
    with db.transaction() as session:
        reference = queries.outbox_reference(session, message_id)
    application_id = reference["application_id"] if reference else None
    return applications.operation_scope(application_id) if application_id is not None else None


def failed(
    principal: auth.Principal, application_id: UUID | None, limit: int, cursor: str | None
) -> BankOutboxPage:
    require_bank(principal)
    with db.transaction() as session:
        rows = queries.outbox_failed(session, application_id, int(cursor or "0"), limit + 1)
        now = clock.system_now()
        items = []
        for row in rows[:limit]:
            reason = (
                "APPLICATION_MISSING"
                if row["application_id"] is None
                else "EXPIRED"
                if row["created_at"] <= now - outbox.MAX_AGE
                else None
            )
            items.append(
                BankOutboxItem(
                    id=row["id"],
                    application_id=row["application_id"],
                    target_system=row["target_system"],
                    event_type=row["event_type"],
                    attempts=row["attempts"],
                    created_at=row["created_at"],
                    last_error=row["last_error"],
                    can_retry=reason is None,
                    blocked_reason=reason,
                )
            )
        return BankOutboxPage(
            items=items, next_cursor=str(rows[limit - 1]["id"]) if len(rows) > limit else None
        )


def retry(principal: auth.Principal, message_id: int, key: str) -> idempotency.Reply:
    # HTTP OperationFence держит общий и компанейский замки до ответа, включая commit и enqueue.
    require_bank(principal)
    with db.transaction() as session:
        reference = queries.outbox_reference(session, message_id)
        if reference is None or reference["application_id"] is None:
            raise not_found("Сообщение или его заявка")
        application_id = reference["application_id"]

        def action() -> idempotency.Reply:
            row = queries.outbox_for_retry(session, message_id)
            if row is None:
                raise not_found("Сообщение")
            if row["status"] != outbox.FAILED:
                raise AppError(409, "OUTBOX_NOT_FAILED", "Сообщение уже повторяется или доставлено")
            if row["created_at"] <= clock.system_now() - outbox.MAX_AGE:
                raise AppError(
                    409, "OUTBOX_RETRY_EXPIRED", "Окно безопасного повтора24ч закончилось"
                )
            if not outbox.retry_dead(session, message_id):
                raise AppError(409, "OUTBOX_RETRY_EXPIRED", "Повтор сейчас невозможен")
            audit.record(
                session,
                "OUTBOX_RETRY",
                actor_id=principal.user_id,
                actor_role=principal.role,
                object_type="OUTBOX",
                object_id=str(message_id),
                company_id=reference["company_id"],
                details={
                    "applicationId": str(application_id),
                    "targetSystem": row["target_system"],
                    "eventType": row["event_type"],
                },
            )
            tasks.enqueue(session, outbox.RELAY_TASK)
            result = BankOutboxRetried(id=message_id, application_id=application_id)
            return idempotency.Reply(200, result.model_dump(mode="json", by_alias=True))

        return idempotency.run_once(
            session,
            scope=f"{principal.user_id}:POST:/backoffice/outbox/{message_id}/retry:{application_id}",
            key=key,
            request={},
            action=action,
        )
