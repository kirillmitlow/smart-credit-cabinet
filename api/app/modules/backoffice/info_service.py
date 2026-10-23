"""Команды L1/L2; задачи/переходы и запуск проверки записывают владельцы модулей."""

from uuid import UUID

from app.modules import applications, audit, auth, pipeline
from app.modules.backoffice.decision_service import actor_level
from app.modules.backoffice.info_schemas import (
    BankInfoRequest,
    BankInfoRequested,
    BankRecheckRequest,
    BankRecheckStarted,
)
from app.shared import db, idempotency


def request_info(
    principal: auth.Principal, application_id: UUID, body: BankInfoRequest, key: str
) -> idempotency.Reply:
    actor_level(principal)  # L1 вправе запросить сведения и по заявке, решение которой требует L2.
    with db.transaction() as session:

        def action() -> idempotency.Reply:
            receipt = applications.request_information(
                session,
                application_id,
                expected_version=body.expected_version,
                actor=applications.Actor.UNDERWRITER,
                actor_id=principal.user_id,
                reason_code=body.reason_code,
                items=[
                    applications.TaskSpec(
                        kind=item.kind,
                        title=item.title,
                        why_text=item.why_text,
                        details={"what": item.what, "where": item.where},
                        assignee_user_id=item.assignee_user_id,
                        assignee_person_inn=item.assignee_person_inn,
                    )
                    for item in body.items
                ],
            )
            audit.record(
                session,
                "UNDERWRITER_REQUEST_INFO",
                actor_id=principal.user_id,
                actor_role=principal.role,
                object_type="APPLICATION",
                object_id=str(application_id),
                details={"round": receipt.round, "reasonCode": body.reason_code},
            )
            result = BankInfoRequested(
                application_id=application_id,
                version=receipt.application_version,
                round=receipt.round,
                task_ids=list(receipt.task_ids),
            )
            return idempotency.Reply(200, result.model_dump(mode="json", by_alias=True))

        return idempotency.run_once(
            session,
            scope=f"{principal.user_id}:POST:/backoffice/applications/{application_id}/request-info",
            key=key,
            request=body.model_dump(mode="json", by_alias=True),
            action=action,
        )


def recheck(
    principal: auth.Principal, application_id: UUID, body: BankRecheckRequest, key: str
) -> idempotency.Reply:
    actor_level(principal)
    with db.transaction() as session:

        def action() -> idempotency.Reply:
            receipt = pipeline.request_recheck(
                session,
                application_id,
                expected_version=body.expected_version,
                actor=applications.Actor.UNDERWRITER,
                actor_id=principal.user_id,
            )
            audit.record(
                session,
                "UNDERWRITER_RECHECK",
                actor_id=principal.user_id,
                actor_role=principal.role,
                object_type="APPLICATION",
                object_id=str(application_id),
                details={"runId": str(receipt.run_id)},
            )
            result = BankRecheckStarted(
                application_id=application_id,
                version=receipt.application_version,
                run_id=receipt.run_id,
            )
            return idempotency.Reply(200, result.model_dump(mode="json", by_alias=True))

        return idempotency.run_once(
            session,
            scope=f"{principal.user_id}:POST:/backoffice/applications/{application_id}/recheck",
            key=key,
            request=body.model_dump(mode="json", by_alias=True),
            action=action,
        )
