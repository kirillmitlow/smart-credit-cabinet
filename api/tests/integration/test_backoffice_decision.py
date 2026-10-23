"""T-362: банковская команда на настоящей БД, авторизация, аудит, откат и повторы."""

import asyncio
import json
import threading
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.modules import applications, audit, auth, pipeline
from app.modules.backoffice import decision_service
from app.modules.offers import Offer
from app.modules.pipeline.models import Decision
from app.shared import db, operations
from app.shared.models import IdempotencyKey
from tests.fixtures import core_personas as cases
from tests.integration.test_backoffice_queue import bank as bank
from tests.integration.test_backoffice_queue import seed

pytestmark = pytest.mark.integration
SECRET = "Внутренняя заметка: документы изучены, риск оценён специалистом."


@pytest.fixture(autouse=True)
def isolated_commands(bank: httpx.AsyncClient) -> None:
    with db.transaction() as session:
        session.execute(text("TRUNCATE idempotency_keys"))


def command(**changes: Any) -> dict[str, Any]:
    return {
        "expectedVersion": 3,
        "outcome": "APPROVED",
        "terms": {"productCode": "INVESTMENT", "amountRub": 15_000_000, "termMonths": 60},
        **changes,
    }


async def send(
    bank: httpx.AsyncClient,
    app_id: UUID,
    body: dict[str, Any] | None = None,
    key: str = "decision",
) -> httpx.Response:
    return await bank.post(
        f"/backoffice/applications/{app_id}/decision",
        json=body if body is not None else command(),
        headers={"Idempotency-Key": key},
    )


def snapshot(app_id: UUID) -> tuple[str, int, int, int, int]:
    with db.transaction() as session:
        app = session.get(applications.Application, app_id)
        assert app is not None
        return (
            app.status,
            app.version,
            len(session.scalars(select(Decision).where(Decision.application_id == app_id)).all()),
            len(session.scalars(select(Offer).where(Offer.application_id == app_id)).all()),
            len(session.scalars(select(IdempotencyKey)).all()),
        )


async def set_level(bank: httpx.AsyncClient, level: str) -> None:
    user_id = UUID((await bank.get("/auth/bank-me")).json()["userId"])
    with db.transaction() as session:
        user = session.get(auth.User, user_id)
        assert user is not None
        user.level = level


async def test_approval_commits_one_decision_offer_and_audit_with_replay(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    engine = (await bank.get(f"/backoffice/applications/{app_id}")).json()["decision"]["id"]
    body = command(engineDecisionId=engine)
    first = await send(bank, app_id, body)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["applicationId"] == str(app_id)
    assert result["engineDecisionId"] == engine
    assert (result["status"], result["outcome"], result["version"]) == ("APPROVED", "APPROVED", 4)
    assert (result["deviation"], result["exceptionUsed"]) == (False, False)
    assert result["offerId"] is not None
    replay = await send(bank, app_id, body)
    assert replay.status_code == 200
    assert replay.json() == result
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert snapshot(app_id) == ("APPROVED", 4, 2, 1, 1)
    with db.transaction() as session:
        records = session.scalars(
            select(audit.AuditRecord).where(
                audit.AuditRecord.action == "UNDERWRITER_DECISION",
                audit.AuditRecord.object_id == str(app_id),
            )
        ).all()
        assert len(records) == 1
        assert records[0].details["decisionId"] == result["decisionId"]
    different_key = await send(bank, app_id, body, key="second-click")
    assert different_key.status_code == 409
    assert different_key.json()["code"] == "VERSION_CONFLICT"
    assert snapshot(app_id) == ("APPROVED", 4, 2, 1, 1)


async def test_reject_requires_reason_and_comment_and_keeps_comment_bank_only(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    body = command(outcome="REJECTED", terms=None)
    invalid = await send(bank, app_id, body)
    assert invalid.status_code == 422
    assert {x["code"] for x in invalid.json()["errors"]} >= {"REASON_REQUIRED", "COMMENT_TOO_SHORT"}
    body.update(reasonCode="UW_RISK_HIGHER", comment=SECRET)
    response = await send(bank, app_id, body)
    assert response.status_code == 200, response.text
    assert response.json()["deviation"] is True
    with db.transaction() as session:
        app = session.get(applications.Application, app_id)
        assert app is not None
        user_id, company_id = app.created_by, app.company_id
    bank.cookies.set(
        "sid_client",
        auth.sessions.create(
            auth.Principal(
                user_id=user_id,
                role="CLIENT",
                zone=auth.Zone.CLIENT,
                display_name="Руководитель",
                memberships=(auth.Membership(company_id, "DIRECTOR"),),
                active_company_id=company_id,
            )
        ),
    )
    client = await bank.get(f"/applications/{app_id}/decision")
    assert client.status_code == 200, client.text
    assert client.json()["outcome"] == "REJECTED"
    assert SECRET not in client.text
    assert not ({"score", "dscr", "overrideReason", "inputs"} & client.json().keys())
    card = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    assert SECRET in json.dumps(card, ensure_ascii=False)


async def test_lowered_session_level_is_enforced_and_denial_audited(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("Заря", cases.zarya())
    await set_level(bank, "L1")
    body = command(terms={"productCode": "CREDIT_LINE", "amountRub": 20_000_000, "termMonths": 12})
    response = await send(bank, app_id, body)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "AUTHORITY_LEVEL_TOO_LOW"
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)
    with db.transaction() as session:
        row = session.scalars(
            select(audit.AuditRecord).where(
                audit.AuditRecord.action == "AUTHORITY_LEVEL_TOO_LOW",
                audit.AuditRecord.object_id == str(app_id),
            )
        ).one()
        assert row.object_id == str(app_id)
        assert row.details["levels"] == [{"requiredLevel": "L2", "actorLevel": "L1"}]
    await set_level(bank, "L2")
    assert (await send(bank, app_id, body)).status_code == 200


async def test_authority_denial_is_audited_also_with_other_validation_errors(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("Заря", cases.zarya())
    await set_level(bank, "L1")
    response = await send(bank, app_id, command(outcome="REJECTED", terms=None))
    assert response.status_code == 422
    assert "AUTHORITY_LEVEL_TOO_LOW" in {x["code"] for x in response.json()["errors"]}
    with db.transaction() as session:
        assert session.scalars(
            select(audit.AuditRecord).where(
                audit.AuditRecord.action == "AUTHORITY_LEVEL_TOO_LOW",
                audit.AuditRecord.object_id == str(app_id),
            )
        ).one().object_id == str(app_id)
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_counter_offer_uses_recomputed_terms_and_percent_units(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    response = await send(
        bank,
        app_id,
        command(
            outcome="COUNTER_OFFER",
            terms={
                "productCode": "INVESTMENT",
                "amountRub": 10_000_000,
                "termMonths": 60,
                "ratePercent": "19.5",
            },
            reasonCode="UW_RISK_HIGHER",
            comment=SECRET,
        ),
    )
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["deviation"]) == ("COUNTER_OFFER", True)
    with db.transaction() as session:
        decision = session.get(Decision, UUID(response.json()["decisionId"]))
        assert decision is not None
        assert float(decision.rate_percent) == 19.5
        assert decision.payment_rub == 262_164  # аннуитет 262164,453… ₽, округление до рубля
        assert session.get(Offer, UUID(response.json()["offerId"])).kind == "COUNTER"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"expectedVersion": 2}, "VERSION_CONFLICT"),
        ({"engineDecisionId": str(uuid4())}, "ENGINE_DECISION_STALE"),
        ({"terms": None}, "UNDERWRITER_DECISION_INVALID"),
        ({"reasonCode": "NOT_A_REASON"}, "UNDERWRITER_DECISION_INVALID"),
        (
            {
                "terms": {
                    "productCode": "INVESTMENT",
                    "amountRub": 15_000_000,
                    "termMonths": 60,
                    "ratePercent": 60,
                }
            },
            "UNDERWRITER_DECISION_INVALID",
        ),
        (
            {"outcome": "REJECTED", "reasonCode": "UW_OTHER", "comment": "x" * 49, "terms": None},
            "UNDERWRITER_DECISION_INVALID",
        ),
    ],
)
async def test_invalid_decision_has_no_business_effect_or_key(
    bank: httpx.AsyncClient, changes: dict[str, Any], code: str
) -> None:
    app_id = seed("СтанкоПром")
    response = await send(bank, app_id, command(**changes))
    assert response.status_code in {409, 422}
    assert response.json()["code"] == code
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_stop_factor_cannot_be_overridden_even_with_forged_manual_status(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("Ромашка", cases.romashka(), status="MANUAL_REVIEW")
    response = await send(bank, app_id)
    assert response.status_code == 422
    assert response.json()["code"] == "UNDERWRITER_DECISION_INVALID"
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_missing_application_and_engine_and_wrong_state(bank: httpx.AsyncClient) -> None:
    assert (await send(bank, uuid4())).status_code == 404
    missing = seed("Без снимка", without_decision=True)
    assert (await send(bank, missing)).json()["code"] == "ENGINE_DECISION_MISSING"
    app_id = seed("Уже отозвана", status="WITHDRAWN")
    response = await send(bank, app_id)
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_TRANSITION"


async def test_key_reuse_cannot_change_a_successful_decision(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    assert (await send(bank, app_id)).status_code == 200
    response = await send(bank, app_id, command(comment="другой запрос"))
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert snapshot(app_id) == ("APPROVED", 4, 2, 1, 1)


async def test_rollback_on_audit_failure_leaves_no_decision_offer_or_key(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = seed("СтанкоПром")

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError, match="audit failed"):
        await send(bank, app_id)
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_concurrent_same_key_is_in_progress_and_only_one_decision(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = seed("СтанкоПром")
    entered, release = threading.Event(), threading.Event()
    original = pipeline.record_underwriter_decision

    def paused(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "record_underwriter_decision", paused)
    first = asyncio.create_task(send(bank, app_id))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        second = await send(bank, app_id)
        assert second.status_code == 409
        assert second.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
    finally:
        release.set()
    assert (await first).status_code == 200
    assert snapshot(app_id) == ("APPROVED", 4, 2, 1, 1)


async def test_two_tabs_actions_with_same_version_cannot_both_commit(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = seed("СтанкоПром")
    barrier = threading.Barrier(2)
    original = pipeline.record_underwriter_decision

    def racing(*args: Any, **kwargs: Any) -> Any:
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "record_underwriter_decision", racing)
    responses = await asyncio.gather(
        send(bank, app_id, key="tab-one"), send(bank, app_id, key="tab-two")
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "VERSION_CONFLICT"
    assert snapshot(app_id) == ("APPROVED", 4, 2, 1, 1)


async def test_lost_response_after_commit_replays_original_result(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = seed("СтанкоПром")
    original = decision_service.decide

    def lose_response(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise RuntimeError("ответ потерян после commit")

    monkeypatch.setattr(decision_service, "decide", lose_response)
    with pytest.raises(RuntimeError, match="ответ потерян"):
        await send(bank, app_id)
    monkeypatch.setattr(decision_service, "decide", original)
    replay = await send(bank, app_id)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert snapshot(app_id) == ("APPROVED", 4, 2, 1, 1)


async def test_persona_reset_excludes_decision_but_not_neighbour(bank: httpx.AsyncClient) -> None:
    app_id, neighbour = seed("СтанкоПром"), seed("Сосед")
    scope = applications.operation_scope(app_id)
    assert scope is not None
    with operations.hold(lambda: scope, exclusive=True):
        denied = await send(bank, app_id)
        assert denied.status_code == 409
        assert denied.json()["code"] == "DEMO_RESET_IN_PROGRESS"
        assert (await send(bank, neighbour)).status_code == 200
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 1)
    assert (await send(bank, app_id)).status_code == 200


async def test_active_decision_blocks_company_reset_until_commit(
    bank: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = seed("СтанкоПром")
    scope = applications.operation_scope(app_id)
    assert scope is not None
    original = pipeline.record_underwriter_decision

    def protected(*args: Any, **kwargs: Any) -> Any:
        with pytest.raises(operations.ResetInProgress):
            with operations.hold(lambda: scope, exclusive=True):
                pytest.fail("Сброс не должен пересечь сохранение решения")
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "record_underwriter_decision", protected)
    assert (await send(bank, app_id)).status_code == 200
    with operations.hold(lambda: scope, exclusive=True):
        pass  # После ответа все замки освобождены.


@pytest.mark.parametrize(
    "extra", [{"actorLevel": "L2"}, {"score": 100}, {"terms": {"amountRub": True}}]
)
async def test_injected_authority_or_score_is_not_accepted(
    bank: httpx.AsyncClient, extra: dict[str, Any]
) -> None:
    app_id = seed("СтанкоПром")
    assert (await send(bank, app_id, command(**extra))).status_code == 422
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_bank_cookie_and_key_are_required(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    assert (
        await bank.post(f"/backoffice/applications/{app_id}/decision", json=command())
    ).status_code == 422
    sid = bank.cookies["sid_bank"]
    bank.cookies.clear()
    bank.cookies.set("sid_client", sid)
    assert (await send(bank, app_id)).status_code == 401
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)
