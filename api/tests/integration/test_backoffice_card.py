"""T-361: неизменяемые снимки, банковские поля и согласованное чтение при гонке."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, select, update

from app.modules import auth, pipeline
from app.modules.applications import Application, ApplicationEvent
from app.modules.companies.models import CompanyMember
from app.modules.decisioning import decide, parse_policy
from app.modules.pipeline.models import PipelineRun, SourceSnapshot
from app.modules.pipeline.persist import build_decision
from app.shared import clock, db
from tests.fixtures import core_personas as cases
from tests.integration.test_backoffice_queue import bank as bank
from tests.integration.test_backoffice_queue import seed

pytestmark = pytest.mark.integration


async def test_stankoprom_card_has_assessment_and_policy_evidence(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    response = await bank.get(f"/backoffice/applications/{app_id}")
    assert response.status_code == 200
    body = response.json()
    assessment = body["decision"]
    assert body["version"] == 3
    assert body["stale"] is False
    assert body["submittedBy"]["name"] == "Клиент"
    assert body["documents"] is None
    assert body["engineDecisionId"] == assessment["id"]
    assert assessment["score"] == 90
    assert assessment["grade"] == "A"
    assert assessment["engineVersion"] == "test"
    assert assessment["policy"]["version"] == 1
    assert len(assessment["policy"]["contentHash"]) == 64
    assert len(assessment["factors"]) == 9
    assert sum(x["points"] for x in assessment["factors"]) == 90
    assert all(x["value"] for x in assessment["factors"])
    assert assessment["paymentRub"] == 393247
    assert assessment["lastPaymentRub"] == 393215
    dscr = next(x for x in assessment["checks"] if x["code"] == "DSCR")
    assert dscr == {
        "code": "DSCR",
        "title": "Покрытие платежей",
        "value": 6.908297,
        "threshold": 1.25,
        "comparison": "MIN",
        "passed": True,
    }
    assert assessment["rate"]["ratePercent"] == 19.5
    assert {p["code"] for p in assessment["rate"]["parts"]} >= {
        "key_rate",
        "spread",
        "expected_loss",
        "expenses",
        "capital_charge",
    }
    assert sum(p["percent"] for p in assessment["rate"]["parts"]) == pytest.approx(19.5)
    assert all(not x["title"].startswith("SC_") for x in assessment["factors"])
    assert (
        assessment["rate"]["corridorMinPercent"] <= 19.5 <= assessment["rate"]["corridorMaxPercent"]
    )
    assert assessment["assessedInput"]["application"]["product"] == "INVESTMENT"
    assert body["history"][0]["toStatus"] == "MANUAL_REVIEW"


async def test_line_card_has_saved_limit_comparison(bank: httpx.AsyncClient) -> None:
    app_id = seed("Заря", cases.zarya())
    body = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    metric = next(x for x in body["decision"]["checks"] if x["code"] == "LINE_LIMIT")
    assert metric["value"] == 20_000_000
    assert metric["threshold"] == 27_083_333.5
    assert metric["passed"] is True


async def test_missing_decision_is_explicit_not_fake_zero_scores(bank: httpx.AsyncClient) -> None:
    app_id = seed("Сбой", without_decision=True, event_reason="PIPELINE_ERROR")
    response = await bank.get(f"/backoffice/applications/{app_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] is None
    assert body["engineRecommendation"] is None
    assert body["decisions"] == []
    assert body["history"][0]["reasonCode"] == "PIPELINE_ERROR"


async def test_thresholds_are_bound_to_decision_policy_not_latest_registered(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    later = pipeline.current_policy().model_dump(mode="json")
    later["meta"]["version"] = 2
    later["affordability"]["dscr_min"]["value"] = "8"
    with db.transaction() as session:
        assert pipeline.register_policy(session, parse_policy(later)).version == 2
    body = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    dscr = next(x for x in body["decision"]["checks"] if x["code"] == "DSCR")
    assert body["decision"]["policy"]["version"] == 1
    assert dscr["threshold"] == 1.25
    assert dscr["passed"] is True


async def test_snapshot_dates_request_and_used_ids_remain_visible(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    with db.transaction() as session:
        run = session.scalars(select(PipelineRun).where(PipelineRun.application_id == app_id)).one()
        snapshot = SourceSnapshot(
            application_id=app_id,
            run_id=run.id,
            system="registry",
            resource="company",
            subject_inn="0012345678",
            status="OK",
            payload={"status": "ACTIVE"},
            payload_hash="a" * 64,
            data_actual_at=clock.today() - timedelta(days=4),
            retrieved_at=clock.now() - timedelta(days=1),
            request_id="REQ-test-source",
        )
        session.add(snapshot)
        session.flush()
        policy = pipeline.register_current(session)
        inp = cases.stankoprom()
        decision = build_decision(
            run,
            inp,
            decide(inp),
            policy_version_id=policy.id,
            engine_version="v2",
            snapshot_ids=[snapshot.id],
        )
        decision.run_id = None
        decision.created_at = clock.now() + timedelta(seconds=1)
        session.add(decision)
    body = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    source = body["sourceSnapshots"][0]
    assert source["usedByCurrentDecision"] is True
    assert source["requestId"] == "REQ-test-source"
    assert source["payload"] == {"status": "ACTIVE"}
    assert source["dataActualAt"] != source["retrievedAt"][:10]
    assert source["payloadHash"] == "a" * 64
    assert len(body["decisions"]) == 2
    assert body["decision"]["engineVersion"] == "v2"


async def test_internal_override_is_banked_and_original_engine_stays_intact(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    original = (await bank.get(f"/backoffice/applications/{app_id}")).json()["decision"]
    with db.transaction() as session:
        run = session.scalars(select(PipelineRun).where(PipelineRun.application_id == app_id)).one()
        policy = pipeline.register_current(session)
        inp = cases.stankoprom()
        decision = build_decision(
            run,
            inp,
            decide(inp),
            policy_version_id=policy.id,
            engine_version="test",
            snapshot_ids=[],
        )
        decision.run_id = None
        decision.source, decision.outcome = "UNDERWRITER", "REJECTED"
        decision.overrides_decision_id = UUID(original["id"])
        decision.override_reason = "Внутренняя заметка: документ требует дополнительной проверки"
        decision.created_at = clock.now() + timedelta(seconds=1)
        session.add(decision)
    body = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    assert body["decision"]["source"] == "UNDERWRITER"
    assert body["decision"]["overridesDecisionId"] == original["id"]
    assert body["engineDecisionId"] == original["id"]
    assert body["engineRecommendation"]["outcome"] == "APPROVED"
    assert body["decisions"][1]["outcome"] == "MANUAL_REVIEW"


async def test_stale_expected_version_and_nonexistent_card(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    assert (await bank.get(f"/backoffice/applications/{app_id}?expectedVersion=3")).json()[
        "stale"
    ] is False
    stale = (await bank.get(f"/backoffice/applications/{app_id}?expectedVersion=2")).json()
    assert stale["version"] == 3
    assert stale["stale"] is True
    assert (await bank.get(f"/backoffice/applications/{uuid4()}")).status_code == 404
    assert (
        await bank.get(f"/backoffice/applications/{app_id}?expectedVersion=0")
    ).status_code == 422


async def test_repeatable_read_does_not_mix_new_status_with_old_history(
    bank: httpx.AsyncClient,
) -> None:
    app_id = seed("СтанкоПром")
    engine = db.get_database().engine
    changed = False

    def concurrent_update(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        nonlocal changed
        if changed or "FROM applications JOIN companies" not in statement:
            return
        changed = True
        with db.transaction() as session:
            session.execute(
                update(Application)
                .where(Application.id == app_id)
                .values(version=4, status="APPROVED")
            )
            session.add(
                ApplicationEvent(
                    application_id=app_id,
                    kind="TRANSITION",
                    actor_type="SYSTEM",
                    from_status="MANUAL_REVIEW",
                    to_status="APPROVED",
                )
            )

    event.listen(engine, "after_cursor_execute", concurrent_update)
    try:
        first = (await bank.get(f"/backoffice/applications/{app_id}?expectedVersion=3")).json()
    finally:
        event.remove(engine, "after_cursor_execute", concurrent_update)
    assert changed is True
    assert first["version"] == 3
    assert first["status"] == "MANUAL_REVIEW"
    assert len(first["history"]) == 1
    second = (await bank.get(f"/backoffice/applications/{app_id}?expectedVersion=3")).json()
    assert second["version"] == 4
    assert second["stale"] is True
    assert len(second["history"]) == 2


async def test_bank_fields_do_not_leak_through_client_decision(bank: httpx.AsyncClient) -> None:
    app_id = seed("СтанкоПром")
    with db.transaction() as session:
        application = session.get(Application, app_id)
        assert application is not None
        user = session.get(auth.User, application.created_by)
        assert user is not None
        session.add(
            CompanyMember(
                company_id=application.company_id, user_id=user.id, role="DIRECTOR", can_sign=True
            )
        )
        principal = auth.Principal(
            user_id=user.id,
            role="CLIENT",
            zone=auth.Zone.CLIENT,
            display_name="Клиент",
            memberships=(auth.Membership(application.company_id, "DIRECTOR"),),
            active_company_id=application.company_id,
        )
    bank.cookies.set("sid_client", auth.sessions.create(principal))
    card = (await bank.get(f"/backoffice/applications/{app_id}")).json()
    assert card["submittedBy"]["companyRole"] == "DIRECTOR"
    response = await bank.get(f"/applications/{app_id}/decision")
    assert response.status_code == 200

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(x) for x in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(x) for x in value))
        return set()

    assert not {
        "score",
        "grade",
        "pdPercent",
        "checks",
        "features",
        "assessedInput",
        "sourceSnapshots",
        "trace",
        "factors",
    } & keys(response.json())
    bank.cookies.delete("sid_bank")
    assert (await bank.get(f"/backoffice/applications/{app_id}")).status_code == 401
