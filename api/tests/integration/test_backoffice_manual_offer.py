"""T-364: расчёт read-only, привязка условий и повторная проверка при сохранении."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.modules import audit, auth
from app.modules.pipeline.models import Decision
from app.shared import db, idempotency
from tests.fixtures import core_personas as cases
from tests.integration.test_backoffice_decision import SECRET, set_level, snapshot
from tests.integration.test_backoffice_queue import bank as bank
from tests.integration.test_backoffice_queue import seed
from tests.integration.test_underwriter_decision import underwriter

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolated(bank: httpx.AsyncClient) -> None:
    with db.transaction() as session:
        session.execute(text("TRUNCATE idempotency_keys"))


async def preview_body(bank: httpx.AsyncClient, app_id: UUID, **changes: Any) -> dict[str, Any]:
    card = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    return {
        "expectedVersion": card["version"],
        "engineDecisionId": card["engineDecisionId"],
        "outcome": "COUNTER_OFFER",
        "terms": {
            "productCode": "INVESTMENT",
            "amountRub": 10_000_000,
            "termMonths": 60,
            "ratePercent": "19.5",
        },
        "reasonCode": "UW_RISK_HIGHER",
        "comment": SECRET,
        **changes,
    }


async def preview(bank: httpx.AsyncClient, app_id: UUID, body: dict[str, Any]) -> httpx.Response:
    return await bank.post(f"/backoffice/applications/{app_id}/evaluate-offer", json=body)


async def save(
    bank: httpx.AsyncClient, app_id: UUID, body: dict[str, Any], **changes: Any
) -> httpx.Response:
    return await bank.post(
        f"/backoffice/applications/{app_id}/decision",
        json={**body, **changes},
        headers={"Idempotency-Key": "saved-preview"},
    )


def save_body(body: dict[str, Any], ref: str) -> dict[str, Any]:
    return {**body, "terms": None, "evaluationRef": ref}


async def test_preview_is_read_only_and_saved_terms_equal_its_result(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id)
    response = await preview(bank, app_id, body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["allowed"] is True
    assert result["evaluationRef"]
    assert (result["ratePercent"], result["paymentRub"]) == (19.5, 262_164)
    assert result["requiredLevel"] == "L1"
    assert result["violations"] == []
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)
    command = save_body(body, result["evaluationRef"])
    saved = await save(bank, app_id, command)
    assert saved.status_code == 200, saved.text
    assert saved.json()["outcome"] == "COUNTER_OFFER"
    replay = await save(bank, app_id, command)
    assert replay.json() == saved.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    with db.transaction() as session:
        decision = session.get(Decision, UUID(saved.json()["decisionId"]))
        assert decision is not None
        assert decision.payment_rub == result["paymentRub"]
        assert float(decision.rate_percent) == result["ratePercent"]
    assert snapshot(app_id) == ("COUNTER_OFFER", 4, 2, 1, 1)


async def test_preview_lists_hard_restriction_and_returns_no_reference(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(
        bank,
        app_id,
        terms={
            "productCode": "INVESTMENT",
            "amountRub": 10_000_000,
            "termMonths": 60,
            "ratePercent": 60,
        },
    )
    response = await preview(bank, app_id, body)
    assert response.status_code == 200
    result = response.json()
    assert result["allowed"] is False
    assert result["evaluationRef"] is None
    assert "RATE_OUT_OF_CORRIDOR" in {v["code"] for v in result["violations"]}
    assert result["corridorMaxPercent"] < 60
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_reason_length_and_calculation_returned_together(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id, reasonCode=None, comment=None)
    result = (await preview(bank, app_id, body)).json()
    assert result["allowed"] is False
    assert result["minCommentChars"] == 20
    assert result["paymentRub"] == 262_164
    assert "REASON_REQUIRED" in {v["code"] for v in result["violations"]}


@pytest.mark.parametrize("suffix", ["bad", "подделка", "..."])
async def test_tampered_reference_is_validation_error_without_effect(
    bank: httpx.AsyncClient, suffix: str
) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id)
    result = (await preview(bank, app_id, body)).json()
    response = await save(bank, app_id, save_body(body, result["evaluationRef"] + suffix))
    assert response.status_code == 422
    assert response.json()["code"] == "EVALUATION_REFERENCE_INVALID"
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_reference_cannot_be_used_for_other_application_or_outcome(
    bank: httpx.AsyncClient,
) -> None:
    app_id, other = seed("Первая"), seed("Вторая")
    body = await preview_body(bank, app_id)
    result = (await preview(bank, app_id, body)).json()
    command = save_body(body, result["evaluationRef"])
    assert (await save(bank, other, command)).status_code == 404
    assert (await save(bank, app_id, command, outcome="APPROVED")).status_code == 422
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_reference_does_not_allow_substituting_conditions(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id)
    result = (await preview(bank, app_id, body)).json()
    response = await save(
        bank, app_id, save_body(body, result["evaluationRef"]), terms=body["terms"]
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_reference_is_personal_and_does_not_authorize_another_underwriter(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id)
    result = (await preview(bank, app_id, body)).json()
    uid = underwriter("L2")
    bank.cookies.clear()
    bank.cookies.set(
        "sid_bank",
        auth.sessions.create(
            auth.Principal(
                user_id=uid,
                role="UNDERWRITER",
                zone=auth.Zone.BANK,
                display_name="Другой сотрудник",
                level="L2",
            )
        ),
    )
    response = await save(bank, app_id, save_body(body, result["evaluationRef"]))
    assert response.status_code == 404
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_downgraded_authority_rechecked_when_saving_valid_reference(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("Заря", cases.zarya())
    body = await preview_body(
        bank,
        app_id,
        outcome="APPROVED",
        terms={"productCode": "CREDIT_LINE", "amountRub": 20_000_000, "termMonths": 12},
        reasonCode=None,
        comment=None,
    )
    result = (await preview(bank, app_id, body)).json()
    assert result["allowed"] is True
    await set_level(bank, "L1")
    response = await save(bank, app_id, save_body(body, result["evaluationRef"]))
    assert response.status_code == 403
    assert response.json()["code"] == "AUTHORITY_LEVEL_TOO_LOW"
    with db.transaction() as session:
        assert session.scalars(
            select(audit.AuditRecord).where(
                audit.AuditRecord.action == "AUTHORITY_LEVEL_TOO_LOW",
                audit.AuditRecord.object_id == str(app_id),
            )
        ).one()
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_stale_version_or_engine_reference_cannot_be_previewed(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    for change, code in (
        ({"expectedVersion": 2}, "VERSION_CONFLICT"),
        ({"engineDecisionId": str(uuid4())}, "ENGINE_DECISION_STALE"),
    ):
        body = await preview_body(bank, app_id, **change)
        response = await preview(bank, app_id, body)
        assert response.status_code == 409
        assert response.json()["code"] == code


async def test_changing_command_version_does_not_refresh_old_evaluation(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id)
    result = (await preview(bank, app_id, body)).json()
    response = await save(bank, app_id, save_body(body, result["evaluationRef"]), expectedVersion=4)
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 0)


async def test_changed_application_rejects_previously_allowed_evaluation(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id)
    result = (await preview(bank, app_id, body)).json()
    with db.transaction() as session:
        session.execute(
            text("UPDATE applications SET version = version + 1 WHERE id = :id"), {"id": app_id}
        )
    response = await save(bank, app_id, save_body(body, result["evaluationRef"]))
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert snapshot(app_id) == ("MANUAL_REVIEW", 4, 1, 0, 0)


async def test_replay_of_a_pre_t364_action_does_not_change_its_request_hash(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    uid = (await bank.get("/auth/bank-me")).json()["userId"]
    # Историческое представление запроса T-362: поля evaluationRef ещё не существовало.
    legacy_request = {
        "expectedVersion": 3,
        "engineDecisionId": None,
        "outcome": "APPROVED",
        "terms": {
            "productCode": "INVESTMENT",
            "amountRub": 15_000_000,
            "termMonths": 60,
            "ratePercent": None,
        },
        "reasonCode": None,
        "comment": None,
    }
    cached = {
        "applicationId": str(app_id),
        "decisionId": str(uuid4()),
        "engineDecisionId": str(uuid4()),
        "status": "APPROVED",
        "version": 4,
        "outcome": "APPROVED",
        "deviation": False,
        "exceptionUsed": False,
        "offerId": str(uuid4()),
    }
    with db.transaction() as session:
        idempotency.run_once(
            session,
            scope=f"{uid}:POST:/backoffice/applications/{app_id}/decision",
            key="saved-preview",
            request=legacy_request,
            action=lambda: idempotency.Reply(200, cached),
        )
    response = await save(bank, app_id, legacy_request)
    assert response.status_code == 200
    assert response.json() == cached
    assert response.headers["Idempotent-Replayed"] == "true"
    assert snapshot(app_id) == ("MANUAL_REVIEW", 3, 1, 0, 1)


async def test_unknown_application_and_missing_bank_session(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    body = await preview_body(bank, app_id)
    assert (await preview(bank, uuid4(), body)).status_code == 404
    bank.cookies.clear()
    assert (await preview(bank, app_id, body)).status_code == 401
