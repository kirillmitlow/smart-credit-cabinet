"""T-260, T-261: согласия заявки — набор, полномочия, один код на пакет, срок, привязка к заявке."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.modules import applications
from app.shared import clock, db
from app.shared.errors import AppError
from tests.integration.support import Firm, Member, client_for, make_stand

pytestmark = pytest.mark.integration

SIGN = "SIGN_COMPANY_CONSENTS"
KUZNETSOV, BELOVA, IVANOVA = "001310000115", "001310000299", "001310000400"
SOKOLOVA, PETROVA = "001234567887", "001310000501"
OWNER, GUARANTOR = "001310000999", "001310000777"
TERMS = {"productCode": "INVESTMENT", "amountRub": 15_000_000, "termMonths": 60}

FIRMS = [
    Firm(
        "sokolova",
        SOKOLOVA,
        "ИП Соколова",
        kind="IP",
        registered_on=date(2023, 4, 12),
        is_bank_customer=True,
        members=[
            Member("sokolova", "Соколова", "DIRECTOR", SOKOLOVA),
            Member("petrova", "Петрова", "ACCOUNTANT", PETROVA, (SIGN,)),
        ],
    ),
    Firm(
        "stankoprom",
        "0017654322",
        "СтанкоПром",
        is_bank_customer=False,
        members=[
            Member("kuznetsov", "Кузнецов", "DIRECTOR", KUZNETSOV),
            Member("belova", "Белова", "ACCOUNTANT", BELOVA, (SIGN,)),
            Member("ivanova", "Иванова", "ACCOUNTANT", IVANOVA),
        ],
    ),
    Firm(
        "quick",
        "0019991114",
        "Быстрый старт",
        registered_on=date(2026, 7, 21),
        is_bank_customer=True,
        members=[
            Member("owner", "Соколов", "DIRECTOR", OWNER),
            Member("guarantor", "Смирнов", "GUARANTOR", GUARANTOR),
        ],
    ),
    Firm(
        "expired",
        "0010000007",
        "Просрочка",
        is_bank_customer=False,
        members=[
            Member("boss", "Директор", "DIRECTOR", "001310000800"),
            Member("clerk", "Бухгалтер", "ACCOUNTANT", "001310000801", (SIGN,), date(2026, 10, 20)),
        ],
    ),
]


@pytest.fixture
def stand(
    postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    with make_stand(postgres_url, redis_url, monkeypatch, FIRMS) as s:
        yield s


async def draft(c: httpx.AsyncClient) -> str:
    response = await c.post("/applications", json=TERMS)
    assert response.status_code == 201
    return str(response.json()["id"])


def refs(
    view: dict[str, Any], *, kinds: set[str] | None = None, only_mine: bool = False
) -> list[dict[str, str]]:
    return [
        {"kind": i["kind"], "subjectInn": i["subjectInn"]}
        for i in view["items"]
        if (kinds is None or i["kind"] in kinds) and (i["canSign"] or not only_mine)
    ]


async def sign(
    c: httpx.AsyncClient, app_id: str, items: list[dict[str, str]], *, accept: bool = True
) -> httpx.Response:
    """Два шага: галочки → код (демо-режим отдаёт его в ответе) → подпись."""
    challenge = await c.post(
        f"/applications/{app_id}/consents", json={"items": items, "acceptPepRules": accept}
    )
    if challenge.status_code != 200:
        return challenge
    body = challenge.json()
    return await c.post(
        f"/applications/{app_id}/consents/sign",
        json={"requestId": body["requestId"], "code": body["demoCode"], "items": items},
    )


async def view(c: httpx.AsyncClient, app_id: str) -> dict[str, Any]:
    response = await c.get(f"/applications/{app_id}/consents")
    assert response.status_code == 200
    return dict(response.json())


async def test_set_for_ip_and_for_llc_where_director_is_owner(stand: dict[str, Any]) -> None:
    async with (
        client_for(stand, "sokolova:sokolova") as sok,
        client_for(stand, "stankoprom:kuznetsov") as stp,
    ):
        ip = await view(sok, await draft(sok))
        llc = await view(stp, await draft(stp))
    # ИП — человек: одно БКИ и одно ПДн на личный ИНН + обороты (клиент банка)
    assert sorted((i["kind"], i["role"]) for i in ip["items"]) == [
        ("BKI", "IP"),
        ("PERSONAL_DATA", "IP"),
        ("TURNOVER", "COMPANY"),
    ]
    # ООО, директор = владелец: БКИ компании, БКИ директора и ПДн директора — по одному на человека
    assert sorted((i["kind"], i["role"]) for i in llc["items"]) == [
        ("BKI", "COMPANY"),
        ("BKI", "DIRECTOR"),
        ("PERSONAL_DATA", "DIRECTOR"),
    ]
    # предзаполненных галочек нет, ПДн — отдельным текстом
    assert all(i["status"] == "PENDING" for i in ip["items"] + llc["items"])
    texts = {i["kind"]: i["textHash"] for i in llc["items"]}
    assert texts["BKI"] != texts["PERSONAL_DATA"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", i["textHash"]) and i["text"] for i in llc["items"])
    assert llc["pepRules"]["accepted"] is False
    assert llc["allSigned"] is False


async def test_one_code_signs_the_whole_bundle_with_hmac_proof(stand: dict[str, Any]) -> None:
    async with client_for(stand, "stankoprom:kuznetsov") as c:
        app_id = await draft(c)
        items = refs(await view(c, app_id))
        challenge = await c.post(
            f"/applications/{app_id}/consents", json={"items": items, "acceptPepRules": True}
        )
        assert challenge.status_code == 200
        code = challenge.json()["demoCode"]
        signed = await c.post(
            f"/applications/{app_id}/consents/sign",
            json={"requestId": challenge.json()["requestId"], "code": code, "items": items},
        )
        assert signed.status_code == 200
        assert signed.json()["allSigned"] is True
        assert len(signed.json()["signed"]) == 3
        after = await view(c, app_id)
        assert after["pepRules"]["accepted"] is True
    with db.transaction() as s:
        rows = s.execute(
            text(
                "SELECT kind, text_hash, signed_at, valid_until, proof, bundle_id, signer_inn FROM consents"
            )
        ).all()
        events = s.execute(
            text("SELECT step_code, payload FROM application_events WHERE kind = 'STEP'")
        ).all()
        audit = s.execute(
            text("SELECT action FROM audit_log WHERE action = 'PEP_RULES_ACCEPTED'")
        ).all()
    assert len(rows) == 3
    assert len({r.bundle_id for r in rows}) == 1
    for r in rows:
        assert re.fullmatch(r"[0-9a-f]{64}", r.proof)
        assert r.proof not in (hashlib.sha256(code.encode()).hexdigest(), code)
        assert code not in str(tuple(r))
        assert r.signer_inn == KUZNETSOV
        assert r.signed_at.date() == date(2026, 10, 21)  # из clock, APP_TODAY
        assert r.valid_until == date(2027, 4, 21)  # 6 месяцев
    assert len({r.proof for r in rows}) == 3
    assert [e.step_code for e in events] == ["CONSENT_SIGNED"]
    assert KUZNETSOV not in str(events[0].payload)
    assert len(audit) == 1


async def test_pep_rules_must_be_accepted_once(stand: dict[str, Any]) -> None:
    async with client_for(stand, "stankoprom:kuznetsov") as c:
        app_id = await draft(c)
        items = refs(await view(c, app_id), kinds={"BKI"})
        refused = await c.post(f"/applications/{app_id}/consents", json={"items": items})
        assert refused.status_code == 422
        assert refused.json()["code"] == "PEP_RULES_NOT_ACCEPTED"
        assert (await sign(c, app_id, items[:1])).status_code == 200
        # правила приняты один раз: следующий пакет без галочки
        assert (await sign(c, app_id, items[1:], accept=False)).status_code == 200


async def test_accountant_signs_company_consents_but_not_personal(stand: dict[str, Any]) -> None:
    async with (
        client_for(stand, "stankoprom:belova") as clerk,
        client_for(stand, "stankoprom:kuznetsov") as boss,
    ):
        app_id = await draft(boss)
        v = await view(clerk, app_id)
        mine = {(i["kind"], i["role"]) for i in v["items"] if i["canSign"]}
        assert mine == {("BKI", "COMPANY")}
        personal = [i for i in refs(v) if i["subjectInn"] == KUZNETSOV]
        denied = await clerk.post(
            f"/applications/{app_id}/consents", json={"items": personal, "acceptPepRules": True}
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "SIGNER_MISMATCH"
        company = [i for i in refs(v) if i["subjectInn"] == "0017654322"]
        ok = await sign(clerk, app_id, company)
        assert ok.status_code == 200
        # директор после бухгалтера подписывает свои личные согласия (его пакет)
        mine_boss = [
            i
            for i in refs(await view(boss, app_id), only_mine=True)
            if i["subjectInn"] == KUZNETSOV
        ]
        assert {i["kind"] for i in mine_boss} == {"BKI", "PERSONAL_DATA"}
        assert (await sign(boss, app_id, mine_boss)).json()["allSigned"] is True


async def test_accountant_without_power_of_attorney_cannot_sign_company_consents(
    stand: dict[str, Any],
) -> None:
    async with (
        client_for(stand, "stankoprom:ivanova") as clerk,
        client_for(stand, "stankoprom:kuznetsov") as boss,
    ):
        app_id = await draft(boss)
        v = await view(clerk, app_id)
        assert not any(i["canSign"] for i in v["items"])
        company = [i for i in refs(v) if i["subjectInn"] == "0017654322"]
        denied = await sign(clerk, app_id, company)
        assert denied.status_code == 403
        assert denied.json()["code"] == "ROLE_CANNOT_SIGN"


async def test_expired_power_of_attorney_does_not_sign(stand: dict[str, Any]) -> None:
    async with (
        client_for(stand, "expired:clerk") as clerk,
        client_for(stand, "expired:boss") as boss,
    ):
        app_id = await draft(boss)
        company = [i for i in refs(await view(clerk, app_id)) if i["subjectInn"] == "0010000007"]
        denied = await sign(clerk, app_id, company)
        assert denied.status_code == 403
        assert denied.json()["code"] == "ROLE_CANNOT_SIGN"


async def test_code_of_one_person_does_not_sign_for_another(stand: dict[str, Any]) -> None:
    async with (
        client_for(stand, "stankoprom:kuznetsov") as boss,
        client_for(stand, "stankoprom:belova") as clerk,
    ):
        app_id = await draft(boss)
        company = [i for i in refs(await view(boss, app_id)) if i["subjectInn"] == "0017654322"]
        challenge = (
            await boss.post(
                f"/applications/{app_id}/consents", json={"items": company, "acceptPepRules": True}
            )
        ).json()
        stolen = await clerk.post(
            f"/applications/{app_id}/consents/sign",
            json={
                "requestId": challenge["requestId"],
                "code": challenge["demoCode"],
                "items": company,
            },
        )
        assert stolen.status_code == 403
        assert stolen.json()["code"] == "SIGNER_MISMATCH"
        # тот же код с другим составом пакета тоже не подписывает
        fresh = (
            await boss.post(
                f"/applications/{app_id}/consents", json={"items": company, "acceptPepRules": True}
            )
        ).json()
        other = refs(await view(boss, app_id), kinds={"PERSONAL_DATA"})
        swapped = await boss.post(
            f"/applications/{app_id}/consents/sign",
            json={"requestId": fresh["requestId"], "code": fresh["demoCode"], "items": other},
        )
        assert swapped.status_code == 403
        assert swapped.json()["code"] == "SIGNER_MISMATCH"
        assert (await view(boss, app_id))["items"][0]["status"] == "PENDING"


async def test_three_wrong_codes_block_the_bundle(stand: dict[str, Any]) -> None:
    async with client_for(stand, "stankoprom:kuznetsov") as c:
        app_id = await draft(c)
        items = refs(await view(c, app_id))
        challenge = (
            await c.post(
                f"/applications/{app_id}/consents", json={"items": items, "acceptPepRules": True}
            )
        ).json()
        wrong = "000000" if challenge["demoCode"] != "000000" else "111111"
        statuses = []
        for _ in range(3):
            r = await c.post(
                f"/applications/{app_id}/consents/sign",
                json={"requestId": challenge["requestId"], "code": wrong, "items": items},
            )
            statuses.append((r.status_code, r.json()["code"]))
        assert statuses == [
            (422, "CODE_INVALID"),
            (422, "CODE_INVALID"),
            (429, "CODE_ATTEMPTS_EXCEEDED"),
        ]
        right = await c.post(
            f"/applications/{app_id}/consents/sign",
            json={
                "requestId": challenge["requestId"],
                "code": challenge["demoCode"],
                "items": items,
            },
        )
        assert right.status_code == 429
        assert (await view(c, app_id))["allSigned"] is False


async def test_repeat_sign_does_not_create_second_signature(stand: dict[str, Any]) -> None:
    async with client_for(stand, "stankoprom:kuznetsov") as c:
        app_id = await draft(c)
        items = refs(await view(c, app_id))
        ch = (
            await c.post(
                f"/applications/{app_id}/consents", json={"items": items, "acceptPepRules": True}
            )
        ).json()
        body = {"requestId": ch["requestId"], "code": ch["demoCode"], "items": items}
        first = await c.post(f"/applications/{app_id}/consents/sign", json=body)
        again = await c.post(f"/applications/{app_id}/consents/sign", json=body)
        assert first.status_code == again.status_code == 200
        assert sorted(i["consentId"] for i in first.json()["signed"]) == sorted(
            i["consentId"] for i in again.json()["signed"]
        )
        # и новый запрос на уже подписанное отклоняется
        repeat = await c.post(
            f"/applications/{app_id}/consents", json={"items": items, "acceptPepRules": True}
        )
        assert repeat.status_code == 409
        assert repeat.json()["code"] == "CONSENT_ALREADY_SIGNED"
    with db.transaction() as s:
        assert s.execute(text("SELECT count(*) FROM consents")).scalar_one() == 3


async def test_submit_requires_all_consents(stand: dict[str, Any]) -> None:
    async with (
        client_for(stand, "stankoprom:kuznetsov") as boss,
        client_for(stand, "stankoprom:belova") as clerk,
    ):
        app_id = await draft(boss)
        none = await boss.post(f"/applications/{app_id}/submit")
        assert none.status_code == 422
        assert none.json()["code"] == "CONSENT_REQUIRED"
        assert {e["kind"] for e in none.json()["errors"]} == {"BKI", "PERSONAL_DATA"}
        company = [i for i in refs(await view(clerk, app_id)) if i["subjectInn"] == "0017654322"]
        await sign(clerk, app_id, company)
        partial = await boss.post(f"/applications/{app_id}/submit")
        assert partial.status_code == 422
        assert partial.json()["code"] == "CONSENT_REQUIRED"
        await sign(boss, app_id, refs(await view(boss, app_id), only_mine=True))
        done = await boss.post(f"/applications/{app_id}/submit")
        assert done.status_code == 200
        assert done.json()["status"] == "SUBMITTED"


async def test_expired_consent_blocks_submit_and_can_be_resigned(stand: dict[str, Any]) -> None:
    async with client_for(stand, "stankoprom:kuznetsov") as c:
        app_id = await draft(c)
        items = refs(await view(c, app_id))
        assert (await sign(c, app_id, items)).status_code == 200
        clock.get_clock().advance(timedelta(days=200))  # больше 6 месяцев
        blocked = await c.post(f"/applications/{app_id}/submit")
        assert blocked.status_code == 422
        assert blocked.json()["code"] == "CONSENT_EXPIRED"
        assert {i["status"] for i in (await view(c, app_id))["items"]} == {"EXPIRED"}
        with db.transaction() as s, pytest.raises(AppError) as caught:
            applications.get_valid_consent(s, _uuid(app_id), "0017654322", "BKI")
        assert caught.value.code == "CONSENT_EXPIRED"
        assert (await sign(c, app_id, items)).status_code == 200  # подписано заново
        assert (await c.post(f"/applications/{app_id}/submit")).status_code == 200
    with db.transaction() as s:
        total, revoked = s.execute(text("SELECT count(*), count(revoked_at) FROM consents")).one()
    assert (total, revoked) == (6, 3)


async def test_consent_belongs_to_one_application(stand: dict[str, Any]) -> None:
    async with client_for(stand, "stankoprom:kuznetsov") as c:
        first = await draft(c)
        assert (await sign(c, first, refs(await view(c, first)))).status_code == 200
        second = await draft(c)
        assert all(i["status"] == "PENDING" for i in (await view(c, second))["items"])
        denied = await c.post(f"/applications/{second}/submit")
        assert denied.json()["code"] == "CONSENT_REQUIRED"
        with db.transaction() as s, pytest.raises(AppError) as caught:
            applications.get_valid_consent(s, _uuid(second), "0017654322", "BKI")
        assert caught.value.code == "CONSENT_REQUIRED"


async def test_guarantor_signs_only_own_and_sees_only_own(stand: dict[str, Any]) -> None:
    async with (
        client_for(stand, "quick:owner") as owner,
        client_for(stand, "quick:guarantor") as guarantor,
    ):
        app_id = await draft(owner)
        full = await view(owner, app_id)
        assert {(i["kind"], i["role"]) for i in full["items"]} == {
            ("BKI", "COMPANY"),
            ("BKI", "DIRECTOR"),
            ("BKI", "GUARANTOR"),
            ("TURNOVER", "COMPANY"),
            ("PERSONAL_DATA", "DIRECTOR"),
            ("PERSONAL_DATA", "GUARANTOR"),
        }
        own = await view(guarantor, app_id)
        assert {i["subjectInn"] for i in own["items"]} == {GUARANTOR}
        # директор не подписывает за поручителя, поручитель — за директора и компанию
        theirs = [i for i in refs(full) if i["subjectInn"] == GUARANTOR]
        assert (await sign(owner, app_id, theirs)).json()["code"] == "SIGNER_MISMATCH"
        foreign = [i for i in refs(full) if i["subjectInn"] != GUARANTOR]
        assert (await sign(guarantor, app_id, foreign)).status_code == 403
        assert (await sign(guarantor, app_id, theirs)).status_code == 200


async def test_stranger_gets_404_and_unknown_item_is_422(stand: dict[str, Any]) -> None:
    async with (
        client_for(stand, "stankoprom:kuznetsov") as boss,
        client_for(stand, "sokolova:sokolova") as other,
    ):
        app_id = await draft(boss)
        assert (await other.get(f"/applications/{app_id}/consents")).status_code == 404
        assert (
            await sign(other, app_id, [{"kind": "BKI", "subjectInn": "0017654322"}])
        ).status_code == 404
        bogus = await boss.post(
            f"/applications/{app_id}/consents",
            json={
                "items": [{"kind": "TURNOVER", "subjectInn": "0017654322"}],
                "acceptPepRules": True,
            },
        )
        assert bogus.status_code == 422
        assert bogus.json()["code"] == "VALIDATION_ERROR"


async def test_pipeline_interface_returns_signed_bki_consents(stand: dict[str, Any]) -> None:
    async with client_for(stand, "stankoprom:kuznetsov") as c:
        app_id = await draft(c)
        with db.transaction() as s:
            assert applications.bki_consents(s, _uuid(app_id)) == []
        await sign(c, app_id, refs(await view(c, app_id)))
    with db.transaction() as s:
        found = applications.bki_consents(s, _uuid(app_id))
        company = applications.get_valid_consent(s, _uuid(app_id), "0017654322", "BKI")
    assert [(b.role, b.subject_kind, b.subject_inn) for b in found] == [
        ("COMPANY", "COMPANY", "0017654322"),
        ("DIRECTOR", "PERSON", KUZNETSOV),
    ]
    first = found[0]
    assert first.purpose == "LOAN_APPLICATION"
    assert first.consent_id.startswith("cns_")
    assert first.valid_until == date(2027, 4, 21)
    assert first.signed_at.date() == date(2026, 10, 21)
    assert first.text_version == "bki-consent-v1"
    assert first.sign_method == "SIMPLE_ESIGN"
    assert company.consent_id == first.consent_id


def _uuid(value: str) -> Any:
    import uuid

    return uuid.UUID(value)
