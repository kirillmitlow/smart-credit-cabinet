"""T-334: client confirmation, immutable evidence and Garipov's two-pass decision."""

import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from app import document_tasks
from app.modules import applications, companies, documents, integrations, pipeline
from app.modules.applications.models import Task
from app.modules.decisioning import decide, input_from_json
from app.modules.documents.models import Document
from app.modules.pipeline.models import Decision, SourceSnapshot
from app.shared import db
from tests.fixtures import pipeline_world as pw
from tests.fixtures.statements import cases as c
from tests.integration import test_documents
from tests.integration.support import client_for
from tests.integration.test_pipeline import consents_for

pytestmark = pytest.mark.integration
stand = test_documents.stand
INN = "001298765490"


def money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02}"


def statement(
    *,
    start: tuple[int, int] = (2025, 10),
    count: int = 12,
    incoming: int = 70_000_000,
    outgoing: int = 60_000_000,
    account: str = c.OWN,
    opening: int = 0,
) -> bytes:
    dates = []
    for index in range(start[0] * 12 + start[1] - 1, start[0] * 12 + start[1] - 1 + count):
        year, month0 = divmod(index, 12)
        dates.append(date(year, month0 + 1, 10))
    first = dates[0].replace(day=1).strftime("%d.%m.%Y")
    last = (
        dates[-1].replace(day=monthrange(dates[-1].year, dates[-1].month)[1]).strftime("%d.%m.%Y")
    )
    payments = []
    for index, at in enumerate(dates):
        day = at.strftime("%d.%m.%Y")
        payments += [
            c.payment(
                f"{index}-in",
                money(incoming),
                recipient=account,
                recipient_inn=INN,
                created=day,
                credited=day,
            ),
            c.payment(
                f"{index}-out",
                money(outgoing),
                payer=account,
                recipient=c.OTHER,
                payer_inn=INN,
                recipient_inn=c.OTHER_INN,
                created=day,
                credited="",
                debited=day,
            ),
        ]
    return c.statement(
        [
            c.account(
                account,
                start=first,
                end=last,
                opening=money(opening),
                incoming=money(incoming * count),
                outgoing=money(outgoing * count),
                closing=money(opening + (incoming - outgoing) * count),
            )
        ],
        payments,
        start=first,
        end=last,
        numbers=(account,),
    )


async def parsed(
    stand: dict[str, Any],
    *,
    key: str = "once",
    content: bytes | None = None,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await test_documents.upload(
        stand, key=key, content=content or statement(), data=data
    )
    assert response.status_code == 201, response.text
    assert document_tasks.run_statement(UUID(response.json()["id"])) == "PARSED"
    async with client_for(stand, "a:d") as client:
        return (await client.get(f"/documents/{response.json()['id']}")).json()


def assertion(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sha256": item["sha256"],
        "acknowledged": True,
        "months": [
            {"month": row["month"], "businessIncomingKopecks": row["unclassifiedIncomingKopecks"]}
            for row in item["parsed"]["months"]
            if row["complete"]
        ][-24:],
    }


async def confirm(
    stand: dict[str, Any],
    item: dict[str, Any],
    *,
    who: str = "a:d",
    key: str = "confirm",
    body: dict[str, Any] | None = None,
) -> Any:
    async with client_for(stand, who) as client:
        return await client.post(
            f"/documents/{item['id']}/confirm",
            json=body or assertion(item),
            headers={"Idempotency-Key": key},
        )


def source(stand: dict[str, Any]) -> dict[str, Any] | None:
    with db.transaction() as session:
        return documents.confirmed_statement_source(
            session, stand["a_app"], stand["companies"]["a"], INN
        )


async def test_confirmation_required_and_repeated_request_has_one_proof(
    stand: dict[str, Any],
) -> None:
    item = await parsed(stand)
    assert source(stand) is None
    with db.transaction() as session:
        task = session.get(Task, stand["a_task"])
        task.details = {"reasonCode": "REVENUE_UNKNOWN"}
    async with client_for(stand, "a:d") as client:
        await client.post(f"/tasks/{stand['a_task']}/answer", json={"text": "Проверил выписку"})
        assert (
            await client.post(f"/applications/{stand['a_app']}/tasks/submit")
        ).status_code == 409
    body = assertion(item)
    body["months"][0]["businessIncomingKopecks"] -= (
        12_345  # exclude non-business receipts, exact cents
    )
    first = await confirm(stand, item, body=body)
    assert first.status_code == 200, first.text
    assert first.json()["confirmedAt"] is not None
    replay = await confirm(stand, item, body=body)
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert (await confirm(stand, item, body=body, key="another-click")).status_code == 200
    bundle = source(stand)
    assert bundle["months"][0]["incomingKopecks"] == 69_987_655
    assert bundle["months"][0]["incomingRub"] == 699_877
    with db.transaction() as session:
        events = list(
            session.scalars(
                select(applications.ApplicationEvent).where(
                    applications.ApplicationEvent.step_code == "STATEMENT_CONFIRMED"
                )
            )
        )
        assert len(events) == 1
    async with client_for(stand, "a:d") as client:
        sent = await client.post(f"/applications/{stand['a_app']}/tasks/submit")
        assert sent.status_code == 200, sent.text


@pytest.mark.parametrize("bad", ["excess", "negative", "duplicate", "missing", "ack", "hash"])
async def test_invalid_assertion_never_confirms(stand: dict[str, Any], bad: str) -> None:
    item = await parsed(stand)
    body = assertion(item)
    if bad == "excess":
        body["months"][0]["businessIncomingKopecks"] += 1
    elif bad == "negative":
        body["months"][0]["businessIncomingKopecks"] = -1
    elif bad == "duplicate":
        body["months"][-1] = body["months"][0]
    elif bad == "missing":
        body["months"].pop()
    elif bad == "ack":
        body["acknowledged"] = False
    else:
        body["sha256"] = "0" * 64
    response = await confirm(stand, item, body=body)
    assert response.status_code == (409 if bad == "hash" else 422), response.text
    assert source(stand) is None
    with db.transaction() as session:
        assert session.get(Document, UUID(item["id"])).confirmed_at is None


@pytest.mark.parametrize("who", ["a:g", "b:d"])
async def test_foreign_and_guarantor_cannot_confirm(stand: dict[str, Any], who: str) -> None:
    assert (await confirm(stand, await parsed(stand), who=who)).status_code == 404


async def test_accountant_confirmation_immutable_and_replacement_needs_new_proof(
    stand: dict[str, Any],
) -> None:
    item = await parsed(stand)
    assert (await confirm(stand, item, who="a:acc")).status_code == 200
    changed = assertion(item)
    changed["months"][0]["businessIncomingKopecks"] -= 1
    response = await confirm(stand, item, body=changed, key="change")
    assert (response.status_code, response.json()["code"]) == (409, "STATEMENT_ALREADY_CONFIRMED")
    replacement = await test_documents.upload(
        stand,
        key="replace",
        content=statement(),
        data={**test_documents.fields(stand), "replacesId": item["id"]},
    )
    assert replacement.status_code == 201
    assert source(stand) is None
    assert (await confirm(stand, item, key="old")).status_code == 409


async def test_duplicate_bytes_count_once_and_conflicting_overlap_rolls_back(
    stand: dict[str, Any],
) -> None:
    first = await parsed(stand)
    assert (await confirm(stand, first)).status_code == 200
    duplicate = await parsed(stand, key="duplicate")
    assert (await confirm(stand, duplicate)).status_code == 200
    bundle = source(stand)
    assert len(bundle["documents"]) == 2
    assert bundle["months"][0]["incomingRub"] == 700_000
    other = await parsed(
        stand,
        key="overlap",
        content=statement().replace(
            "Оплата по договору".encode("cp1251"), "Другая операция".encode("cp1251")
        ),
    )
    failed = await confirm(stand, other)
    assert (failed.status_code, failed.json()["code"]) == (422, "OVERLAPPING_PERIODS")
    with db.transaction() as session:
        assert session.get(Document, UUID(other["id"])).confirmed_at is None


async def test_global_month_coverage_and_one_rounding_across_accounts(
    stand: dict[str, Any],
) -> None:
    first = await parsed(stand, content=statement(count=6, incoming=49, outgoing=0))
    assert (await confirm(stand, first)).status_code == 200
    second = await parsed(
        stand,
        key="other-account",
        content=statement(start=(2026, 1), count=6, incoming=49, outgoing=0, account=c.SECOND),
    )
    assert (await confirm(stand, second)).status_code == 200
    bundle = source(stand)
    assert [m["month"] for m in bundle["months"]] == ["2026-01", "2026-02", "2026-03"]
    assert all(m["incomingKopecks"] == 98 and m["incomingRub"] == 1 for m in bundle["months"])


async def test_adjacent_periods_reconcile_and_gaps_do_not_create_extra_history(
    stand: dict[str, Any],
) -> None:
    first = await parsed(stand, content=statement(count=3))
    assert (await confirm(stand, first)).status_code == 200
    second = await parsed(
        stand, key="adjacent", content=statement(start=(2026, 1), count=3, opening=30_000_000)
    )
    assert (await confirm(stand, second)).status_code == 200
    assert len(source(stand)["months"]) == 6
    later = await parsed(stand, key="gap", content=statement(start=(2026, 7), count=3))
    assert (await confirm(stand, later)).status_code == 200
    assert [m["month"] for m in source(stand)["months"]] == ["2026-07", "2026-08", "2026-09"]


async def test_unassigned_draft_file_reused_for_revenue_request(stand: dict[str, Any]) -> None:
    with db.transaction() as session:
        application = session.get(applications.Application, stand["a_app"])
        application.status = "DRAFT"
    item = await parsed(
        stand, data={"applicationId": str(stand["a_app"]), "kind": "BANK_STATEMENT_1C"}
    )
    with db.transaction() as session:
        session.get(applications.Application, stand["a_app"]).status = "NEEDS_INFO"
        session.get(Task, stand["a_task"]).details = {"reasonCode": "REVENUE_UNKNOWN"}
    assert (await confirm(stand, item)).status_code == 200
    replaced = await test_documents.upload(
        stand,
        key="replace",
        content=statement(),
        data={**test_documents.fields(stand), "replacesId": item["id"]},
    )
    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["taskId"] == str(stand["a_task"])


@pytest.mark.parametrize("origin", ["UPLOADED", "DEMO_GENERATED"])
async def test_garipov_upload_confirmation_recheck_is_reproducible(
    stand: dict[str, Any], origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = pw.World(
        registry={
            INN: {
                "type": "INDIVIDUAL_ENTREPRENEUR",
                "inn": INN,
                "ogrnip": "321000000123450",
                "registrationDate": "2021-09-01",
                "person": {"fullName": "Гарипов"},
                "status": {"code": "ACTIVE", "since": "2021-09-01"},
                "okvedMain": {"code": "96.02"},
            }
        },
        tax={INN: pw.tax_profile(INN, "PSN")},
        screening={INN: pw.screening((INN, "IE"))},
        bki={
            INN: pw.report(
                INN,
                "PERSON",
                closed=1,
                history_months=48,
                obligations=[pw.obligation("closed-loan", "LOAN", "CLOSED")],
            )
        },
    )
    ports = pw.build_integrations(world)
    pipeline.set_consents_provider(consents_for((INN, "COMPANY")))
    try:
        with db.transaction() as session:
            application = session.get(applications.Application, stand["a_app"])
            application.status = "SUBMITTED"
            session.get(Task, stand["a_task"]).status = "CANCELLED"
            version = session.get(applications.ApplicationVersion, application.current_version_id)
            version.data = {
                "productCode": "EXPRESS",
                "amountRub": 1_500_000,
                "termMonths": 36,
                "draft": {},
            }
        assert pipeline.run_pipeline(stand["a_app"], integrations=ports) == pipeline.RunResult.DONE
        with db.transaction() as session:
            task = session.scalars(
                select(Task).where(Task.application_id == stand["a_app"], Task.status == "OPEN")
            ).one()
            stand["a_task"] = task.id
            assert session.get(applications.Application, stand["a_app"]).status == "NEEDS_INFO"
        if origin == "UPLOADED":
            item = await parsed(stand)
        else:
            with db.transaction() as session:
                companies.by_id(session, stand["companies"]["a"]).scenario_code = "garipov"
            monkeypatch.setattr(
                integrations.scenarios, "bank_statement", lambda *a, **kw: statement()
            )
            async with client_for(stand, "a:d") as client:
                response = await client.post(
                    "/demo/bank-statement",
                    json={"applicationId": str(stand["a_app"]), "taskId": str(stand["a_task"])},
                    headers={"Idempotency-Key": "garipov-demo-file"},
                )
                assert response.status_code == 201, response.text
                assert document_tasks.run_statement(UUID(response.json()["id"])) == "PARSED"
                item = (await client.get(f"/documents/{response.json()['id']}")).json()
                assert item["origin"] == "DEMO_GENERATED"
        assert source(stand) is None
        assert (await confirm(stand, item)).status_code == 200
        async with client_for(stand, "a:d") as client:
            await client.post(
                f"/tasks/{stand['a_task']}/answer", json={"text": "Выручку проверил и подтвердил"}
            )
            sent = await client.post(f"/applications/{stand['a_app']}/tasks/submit")
            assert sent.status_code == 200, sent.text
        assert pipeline.run_pipeline(stand["a_app"], integrations=ports) == pipeline.RunResult.DONE
        with db.transaction() as session:
            application = session.get(applications.Application, stand["a_app"])
            assert application.status == "APPROVED"
            decision = session.scalars(
                select(Decision)
                .where(Decision.application_id == application.id)
                .order_by(Decision.created_at.desc(), Decision.id.desc())
            ).first()
            assert (
                decision.grade,
                decision.score,
                decision.revenue_monthly_rub,
                decision.free_cash_flow_rub,
            ) == ("B", 84, 700_000, 91_000)
            assert decision.dscr.quantize(Decimal("0.001")) == Decimal("1.578")
            local = session.scalars(
                select(SourceSnapshot).where(
                    SourceSnapshot.run_id == decision.run_id,
                    SourceSnapshot.system == "CLIENT_UPLOAD",
                )
            ).one()
            assert local.payload["documents"][0]["sha256"] == item["sha256"]
            assert local.id in decision.snapshot_ids
            assert (
                decide(input_from_json(json.dumps(decision.inputs))).inputs_hash
                == decision.inputs_hash
            )
            assert decision.features["revenue_source"] == "CLIENT_UPLOAD"
            assert decision.features["payers_in_6m_max"] is None
        assert world.count("credit_bureau:report") == 1
    finally:
        pipeline.set_consents_provider(None)
