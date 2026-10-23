"""T-259, T-340, T-341, T-263: решение клиенту, принятие, договор и подпись кодом (Соколова, оракул 30-17)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from pypdf import PdfReader
from sqlalchemy import text

from app.modules import disbursement, pipeline
from app.modules.applications import Application, ApplicationVersion
from app.modules.pipeline.consents import ConsentView
from app.shared import clock, db
from tests.fixtures import pipeline_world as pw
from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = pytest.mark.integration

SIGN = "SIGN_COMPANY_CONSENTS"
BANNED_WORDS = re.compile(r"грейд|балл|скоринг|\bPD\b|DSCR|стоп-фактор|флаг", re.IGNORECASE)
BANNED_KEYS = {"score", "grade", "pd", "dscr", "stressDscr", "snapshots", "explain", "features"}

FIRMS = [
    Firm(
        "sokolova",
        pw.SOKOLOVA_INN,
        "ИП Соколова",
        kind="IP",
        is_bank_customer=None,
        members=[
            Member("sokolova", "Соколова", "DIRECTOR", pw.SOKOLOVA_INN),
            Member("petrova", "Петрова", "ACCOUNTANT", "001310000501", (SIGN,)),
        ],
    ),
    Firm(
        "stankoprom",
        "0017654322",
        "СтанкоПром",
        members=[Member("kuznetsov", "Кузнецов", "DIRECTOR", "001310000115")],
    ),
]


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    with make_stand(postgres_url, redis_url, monkeypatch, FIRMS) as s:
        yield s
    pipeline.set_consents_provider(None)


def approve_sokolova(stand: dict[str, Any]) -> str:
    """Заявка Соколовой (500 000 ₽, 12 мес.) → конвейер на подставном мире → `APPROVED`."""
    pipeline.set_consents_provider(
        lambda _s, _a: [
            ConsentView(
                "cns_1",
                pw.SOKOLOVA_INN,
                "COMPANY",
                clock.now() - timedelta(minutes=10),
                date(2027, 4, 21),
                "LOAN_APPLICATION",
            )
        ]
    )
    world = pw.sokolova_world()
    director = stand["principals"]["sokolova:sokolova"]
    with db.transaction() as s:
        application = Application(
            number="АЗ-2026-000001",
            company_id=stand["companies"]["sokolova"],
            created_by=director.user_id,
            status="SUBMITTED",
            version=2,
            product_code="EXPRESS",
            amount_rub=500_000,
            term_months=12,
            draft={},
            flags=[],
        )
        s.add(application)
        s.flush()
        data = {"productCode": "EXPRESS", "amountRub": 500_000, "termMonths": 12, "draft": {}}
        version = ApplicationVersion(
            application_id=application.id, number=1, reason="SUBMIT", data=data, data_hash="h1"
        )
        s.add(version)
        s.flush()
        application.current_version_id = version.id
        application_id = application.id
    result = pipeline.run_pipeline(application_id, integrations=pw.build_integrations(world))
    assert result == pipeline.RunResult.DONE
    return str(application_id)


def sql(query: str, **params: Any) -> list[Any]:
    with db.transaction() as s:
        return list(s.execute(text(query), params).all())


def status_of(app_id: str) -> str:
    return str(sql("SELECT status FROM applications WHERE id = :i", i=app_id)[0][0])


async def accept(c: httpx.AsyncClient, app_id: str) -> httpx.Response:
    offer = (await c.get(f"/applications/{app_id}/offer")).json()
    return await c.post(f"/offers/{offer['id']}/accept", json={})


async def start_signing(c: httpx.AsyncClient, contract_id: str, **extra: Any) -> httpx.Response:
    return await c.post(
        f"/contracts/{contract_id}/sign/request",
        json={"agree": True, "acceptPepRules": True, **extra},
    )


def walk(node: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


async def test_sokolova_decision_accept_sign_and_disbursement_handoff(
    stand: dict[str, Any],
) -> None:
    app_id = approve_sokolova(stand)
    async with (
        client_for(stand, "sokolova:sokolova") as boss,
        client_for(stand, "sokolova:petrova") as clerk,
    ):
        # --- решение простым языком (T-259)
        decision = (await boss.get(f"/applications/{app_id}/decision")).json()
        assert decision["outcome"] == "APPROVED"
        assert decision["headline"] == "Одобрено на запрошенных условиях"
        terms = decision["terms"]
        assert (terms["amountRub"], terms["termMonths"], terms["ratePercent"]) == (
            500_000,
            12,
            21.5,
        )
        assert abs(terms["paymentRub"] - 46_677) <= 1
        assert terms["overpaymentRub"] == 60_126
        assert [r["number"] for r in terms["schedulePreview"]] == [1, 2, 3, 12]
        assert decision["whatHelped"] == ["чистая кредитная история", "стабильная выручка"]
        assert sum(p["percent"] for p in decision["rateBreakdown"]) == pytest.approx(21.5)
        assert not {k for k, _ in walk(decision)} & BANNED_KEYS
        assert not BANNED_WORDS.search(json.dumps(decision, ensure_ascii=False))
        assert decision["offer"]["status"] == "OPEN"
        assert decision["offer"]["variantsStatus"] == "READY"

        # --- принятие (T-340)
        accepted = await accept(boss, app_id)
        assert accepted.status_code == 200
        body = accepted.json()
        assert body["applicationStatus"] == "OFFER_ACCEPTED"
        contract = body["contract"]
        contract_id = contract["id"]
        assert contract["progress"] == {"signed": 0, "required": 1}
        assert re.fullmatch(r"[0-9a-f-]{36}-[0-9a-f]", contract["contractUid"])
        document = await boss.get(f"/contracts/{contract_id}/document")
        assert document.headers["x-content-sha256"] == contract["contentHash"]
        assert document.headers["content-type"] == "application/pdf"
        assert hashlib.sha256(document.content).hexdigest() == contract["contentHash"]
        pdf_text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(document.content)).pages)
        assert "500000₽" in re.sub(r"\s", "", pdf_text)
        assert "Соколова" in pdf_text

        # --- бухгалтер не подписывает, но передаёт руководителю (D-014)
        assert (await start_signing(clerk, contract_id)).status_code == 403
        denied = await clerk.post(
            f"/contracts/{contract_id}/sign", json={"requestId": "otp_x", "code": "123456"}
        )
        assert (denied.status_code, denied.json()["code"]) == (403, "ROLE_CANNOT_SIGN")
        view = (await clerk.get(f"/contracts/{contract_id}")).json()
        assert (view["canSign"], view["canPassToDirector"]) == (False, True)
        passed = await clerk.post(f"/contracts/{contract_id}/request-signature")
        assert passed.status_code == 200
        assert passed.json()["repeated"] is False
        again = await clerk.post(f"/contracts/{contract_id}/request-signature")
        assert again.json()["repeated"] is True
        assert (await boss.post(f"/contracts/{contract_id}/request-signature")).status_code == 409

        # --- руководитель подписывает кодом (T-263)
        challenge = await start_signing(boss, contract_id)
        assert challenge.status_code == 200
        wrong = await boss.post(
            f"/contracts/{contract_id}/sign",
            json={"requestId": challenge.json()["requestId"], "code": "000000"},
        )
        assert wrong.status_code in (422, 429) or wrong.json()["code"] == "CODE_INVALID"
        sign_body = {
            "requestId": challenge.json()["requestId"],
            "code": challenge.json()["demoCode"],
        }
        signed = await boss.post(f"/contracts/{contract_id}/sign", json=sign_body)
        assert signed.status_code == 200
        assert signed.json()["justSigned"] is True
        assert signed.json()["contract"]["status"] == "SIGNED"
        assert signed.json()["contract"]["applicationStatus"] == "SIGNED"
        # двойное «Подписать»: вторая подпись и второй запуск выдачи не создаются
        repeat = await boss.post(f"/contracts/{contract_id}/sign", json=sign_body)
        assert repeat.status_code == 200
        assert repeat.json()["justSigned"] is False

    assert status_of(app_id) == "SIGNED"
    rows = sql("SELECT proof, method, content_hash, signer_role, attempt_id FROM signatures")
    assert len(rows) == 1
    proof, method, content_hash, role, attempt = rows[0]
    assert re.fullmatch(r"[0-9a-f]{64}", proof)
    assert sign_body["code"] not in proof
    assert (method, role, content_hash) == ("SIMPLE_ESIGN", "DIRECTOR", contract["contentHash"])
    assert attempt == sign_body["requestId"]
    assert stand["sent"] == [("disbursement.run", {"application_id": app_id})]
    transitions = sql(
        "SELECT to_status FROM application_events WHERE kind = 'TRANSITION' ORDER BY id"
    )
    assert [t[0] for t in transitions][-2:] == ["OFFER_ACCEPTED", "SIGNED"]
    # после SIGNED отозвать нельзя
    async with client_for(stand, "sokolova:sokolova") as boss:
        assert (await boss.post(f"/applications/{app_id}/withdraw")).status_code == 409
    assert disbursement.run(UUID(app_id)) == "STARTED"
    funding = sql(
        "SELECT amount_rub, term_months, rate_percent, contract_number, contract_uid "
        "FROM disbursements WHERE application_id = :i",
        i=app_id,
    )[0]
    assert funding[:3] == (500_000, 12, 21.5)
    assert funding[3:] == (contract["number"], contract["contractUid"])
    assert status_of(app_id) == "DISBURSING"


async def test_parallel_sign_gives_one_signature_and_one_task(stand: dict[str, Any]) -> None:
    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        contract_id = (await accept(boss, app_id)).json()["contract"]["id"]
        challenge = (await start_signing(boss, contract_id)).json()
        body = {"requestId": challenge["requestId"], "code": challenge["demoCode"]}
        results = await asyncio.gather(
            boss.post(f"/contracts/{contract_id}/sign", json=body),
            boss.post(f"/contracts/{contract_id}/sign", json=body),
        )
    assert [r.status_code for r in results] == [200, 200]
    assert sorted(r.json()["justSigned"] for r in results) == [False, True]
    assert len(sql("SELECT 1 FROM signatures")) == 1
    assert len(stand["sent"]) == 1
    assert status_of(app_id) == "SIGNED"


async def test_foreign_company_sees_nothing(stand: dict[str, Any]) -> None:
    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        offer = (await boss.get(f"/applications/{app_id}/offer")).json()
        contract_id = (await accept(boss, app_id)).json()["contract"]["id"]
    async with client_for(stand, "stankoprom:kuznetsov") as other:
        for method, path in [
            ("GET", f"/applications/{app_id}/decision"),
            ("GET", f"/applications/{app_id}/offer"),
            ("POST", f"/offers/{offer['id']}/accept"),
            ("POST", f"/offers/{offer['id']}/decline"),
            ("GET", f"/contracts/{contract_id}"),
            ("GET", f"/contracts/{contract_id}/document"),
            ("POST", f"/contracts/{contract_id}/request-signature"),
        ]:
            response = await other.request(method, path)
            assert (method, path, response.status_code) == (method, path, 404)
        sign = await other.post(
            f"/contracts/{contract_id}/sign/request", json={"agree": True, "acceptPepRules": True}
        )
        assert sign.status_code == 404
    assert status_of(app_id) == "OFFER_ACCEPTED"


async def test_decline_withdraws_application(stand: dict[str, Any]) -> None:
    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        offer = (await boss.get(f"/applications/{app_id}/offer")).json()
        declined = await boss.post(f"/offers/{offer['id']}/decline")
        assert declined.status_code == 200
        assert declined.json()["applicationStatus"] == "WITHDRAWN"
        assert declined.json()["offer"]["status"] == "DECLINED"
        assert (await boss.post(f"/offers/{offer['id']}/decline")).status_code == 200
        late = await boss.post(f"/offers/{offer['id']}/accept", json={})
        assert (late.status_code, late.json()["code"]) == (409, "OFFER_NOT_OPEN")
    assert status_of(app_id) == "WITHDRAWN"


async def test_double_accept_makes_one_transition_and_one_contract(stand: dict[str, Any]) -> None:
    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        offer = (await boss.get(f"/applications/{app_id}/offer")).json()
        results = await asyncio.gather(
            boss.post(f"/offers/{offer['id']}/accept", json={}),
            boss.post(f"/offers/{offer['id']}/accept", json={}),
        )
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json()["contract"]["id"] == results[1].json()["contract"]["id"]
    accepted = sql(
        "SELECT 1 FROM application_events WHERE kind = 'TRANSITION' AND to_status = 'OFFER_ACCEPTED'"
    )
    assert len(accepted) == 1
    assert len(sql("SELECT 1 FROM contracts")) == 1


async def test_expired_offer_cannot_be_accepted(stand: dict[str, Any]) -> None:
    app_id = approve_sokolova(stand)
    clock.get_clock().advance(timedelta(days=11))
    async with client_for(stand, "sokolova:sokolova") as boss:
        response = await accept(boss, app_id)
    assert (response.status_code, response.json()["code"]) == (409, "OFFER_EXPIRED")
    assert status_of(app_id) == "APPROVED"


async def test_pending_variants_are_marked_and_not_acceptable(stand: dict[str, Any]) -> None:
    app_id = approve_sokolova(stand)
    sql_update = "UPDATE offers SET variants_status = 'PENDING' WHERE application_id = :i"
    with db.transaction() as s:
        s.execute(text(sql_update), {"i": app_id})
    async with client_for(stand, "sokolova:sokolova") as boss:
        offer = (await boss.get(f"/applications/{app_id}/offer")).json()
        response = await boss.post(f"/offers/{offer['id']}/accept", json={})
    assert offer["variantsStatus"] == "PENDING"
    assert (response.status_code, response.json()["code"]) == (409, "OFFER_VARIANTS_PENDING")


@pytest.mark.parametrize("repair_hash", [False, True])
async def test_tampered_document_is_not_signed(stand: dict[str, Any], repair_hash: bool) -> None:
    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        contract_id = (await accept(boss, app_id)).json()["contract"]["id"]
        challenge = (await start_signing(boss, contract_id)).json()
        with db.transaction() as s:
            s.execute(text("UPDATE contracts SET body = replace(body, '500000', '900000')"))
            if repair_hash:
                body = s.execute(
                    text("SELECT body FROM contracts WHERE id=:id"), {"id": contract_id}
                ).scalar_one()
                s.execute(
                    text("UPDATE contracts SET content_hash=:digest WHERE id=:id"),
                    {
                        "id": contract_id,
                        "digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    },
                )
        response = await boss.post(
            f"/contracts/{contract_id}/sign",
            json={"requestId": challenge["requestId"], "code": challenge["demoCode"]},
        )
    assert (response.status_code, response.json()["code"]) == (409, "CONTRACT_TAMPERED")
    assert sql("SELECT 1 FROM signatures") == []
    assert status_of(app_id) == "OFFER_ACCEPTED"
    assert stand["sent"] == []


async def test_signatures_and_variants_are_immutable(stand: dict[str, Any]) -> None:
    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        contract_id = (await accept(boss, app_id)).json()["contract"]["id"]
        challenge = (await start_signing(boss, contract_id)).json()
        await boss.post(
            f"/contracts/{contract_id}/sign",
            json={"requestId": challenge["requestId"], "code": challenge["demoCode"]},
        )
    for statement in (
        "UPDATE signatures SET proof = repeat('0', 64)",
        "DELETE FROM signatures",
        "UPDATE offer_variants SET amount_rub = 1",
    ):
        with pytest.raises(Exception, match="(?i)immutable|запрещ|journal"), db.transaction() as s:
            s.execute(text(statement))
    assert UUID(contract_id)


@pytest.mark.parametrize("replacement", ["offer_application", "pdf_original"])
async def test_signed_original_cannot_be_rebound_before_issuance(
    stand: dict[str, Any], replacement: str
) -> None:
    """Even consistent mutable references cannot change the terms already signed."""
    from app.modules import documents
    from app.modules.offers import contracts
    from app.modules.offers.models import Contract, Offer
    from app.shared.errors import AppError

    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        contract_id = (await accept(boss, app_id)).json()["contract"]["id"]
        challenge = (await start_signing(boss, contract_id)).json()
        signed = await boss.post(
            f"/contracts/{contract_id}/sign",
            json={"requestId": challenge["requestId"], "code": challenge["demoCode"]},
        )
        assert signed.status_code == 200
        with db.transaction() as session:
            contract = session.get(Contract, UUID(contract_id))
            assert contract is not None
            application = session.get(Application, UUID(app_id))
            assert application is not None
            if replacement == "offer_application":
                other = Application(
                    number="АЗ-2026-999999",
                    company_id=application.company_id,
                    created_by=application.created_by,
                    status="REJECTED",
                    version=1,
                    product_code="EXPRESS",
                    amount_rub=900_000,
                    term_months=12,
                    draft={},
                    flags=[],
                )
                session.add(other)
                session.flush()
                offer = session.get(Offer, contract.offer_id)
                assert offer is not None
                offer.application_id = other.id
            else:
                body = json.loads(contract.body)
                body["amountRub"] = 700_000
                contract.body = json.dumps(body, ensure_ascii=False)
                contract.content_hash = contracts.content_hash_of(contract.body)
                original = documents.store_generated(
                    session,
                    documents.UploadContext(application.company_id, application.id),
                    application.created_by,
                    content=documents.render_credit(contract.body),
                    kind="CREDIT_AGREEMENT",
                    filename="replacement.pdf",
                    template_version=contract.template_version,
                )
                contract.document_id = original.id
        if replacement == "pdf_original":
            response = await boss.get(f"/contracts/{contract_id}/document")
            assert (response.status_code, response.json()["code"]) == (409, "CONTRACT_TAMPERED")
    with db.transaction() as session:
        if replacement == "offer_application":
            assert contracts.signed_terms(session, UUID(app_id)) is None
        else:
            with pytest.raises(AppError, match="сохранённой подписи"):
                contracts.signed_terms(session, UUID(app_id))
    assert not sql("SELECT id FROM disbursements WHERE application_id = :i", i=app_id)


async def test_legacy_json_original_can_still_be_read_signed_and_issued(
    stand: dict[str, Any],
) -> None:
    """Deploying PDF support must not replace an existing JSON original or invalidate its OTP."""
    from app.modules.offers.contracts import content_hash_of
    from app.modules.offers.models import Contract

    app_id = approve_sokolova(stand)
    async with client_for(stand, "sokolova:sokolova") as boss:
        contract_id = (await accept(boss, app_id)).json()["contract"]["id"]
        with db.transaction() as session:
            contract = session.get(Contract, UUID(contract_id))
            assert contract is not None
            contract.template_version = "credit-agreement-json-v1"
            body = json.loads(contract.body)
            body["template"] = contract.template_version
            contract.body = json.dumps(body, ensure_ascii=False, sort_keys=True)
            contract.content_hash = content_hash_of(contract.body)
            contract.document_id = None
            expected = contract.body.encode("utf-8")
        original = await boss.get(f"/contracts/{contract_id}/document")
        assert original.headers["content-type"] == "application/json"
        assert original.content == expected
        challenge = (await start_signing(boss, contract_id)).json()
        signed = await boss.post(
            f"/contracts/{contract_id}/sign",
            json={"requestId": challenge["requestId"], "code": challenge["demoCode"]},
        )
        assert signed.status_code == 200
        assert signed.json()["contract"]["status"] == "SIGNED"
        assert (await boss.get(f"/contracts/{contract_id}/document")).content == expected
    assert disbursement.run(UUID(app_id)) == "STARTED"
