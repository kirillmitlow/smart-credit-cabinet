"""TS-001: Соколова от входа до «Мои кредиты» по API на живом стенде (T-391, 10-05).

Вход → мастер → заявка → согласия → конвейер → `APPROVED` → решение клиенту → принятие →
подпись → выдача → кредит с графиком. Числа сверяются с оракулом 30-17: ставка 21,5%, платёж
46 677 ₽ (±1 ₽). Тест повторяем: после `DISBURSED` заявка закрыта, новая подаётся заново.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest

from tests.personas.harness import (
    check,
    expected,
    login,
    require_clean_persona,
    sign_all_consents,
    stand_url,
    wait_status,
)

pytestmark = pytest.mark.persona

RATE = Decimal("21.5")
PAYMENT = 46_677
HIDDEN = ("score", "grade", "dscr", "points", "pd", "AML")


@pytest.fixture
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=stand_url(), timeout=30) as c:
        yield c


def test_ts001_sokolova_thin_path(client: httpx.Client) -> None:
    """TS-001."""
    want = expected("sokolova")
    assert want.outcome == "APPROVED"
    amount, term = want.amount_rub, want.term_months

    login(client, want.inn)
    require_clean_persona(client, want.code)

    wizard = check(
        client.post(
            "/wizard/recommendations",
            json={
                "answers": {
                    "purpose": "EQUIPMENT",
                    "amountRub": amount,
                    "frequency": "ONCE",
                    "paybackHorizon": "MONTHS_3_12",
                    "govContract": "NO",
                }
            },
        )
    )
    assert wizard["primary"], wizard
    application_id = wizard["applicationId"]
    assert application_id, "мастер должен создать черновик заявки"

    draft = check(client.get(f"/applications/{application_id}"))
    draft = check(
        client.patch(
            f"/applications/{application_id}/draft",
            json={
                "version": draft["version"],
                "productCode": want.product_code,
                "amountRub": amount,
                "termMonths": term,
            },
        )
    )

    consents = sign_all_consents(client, application_id)
    assert consents["allSigned"], consents

    submitted = check(client.post(f"/applications/{application_id}/submit"))
    assert submitted["submittedAt"]

    decided = wait_status(
        client,
        application_id,
        {"APPROVED", "COUNTER_OFFER", "REJECTED", "MANUAL_REVIEW", "NEEDS_INFO"},
    )
    assert decided["status"] == want.outcome

    decision_response = client.get(f"/applications/{application_id}/decision")
    decision = check(decision_response)
    assert decision["outcome"] == "APPROVED"
    terms = decision["terms"]
    assert terms["amountRub"] == amount
    assert terms["termMonths"] == term
    assert Decimal(str(terms["ratePercent"])) == RATE
    assert abs(terms["paymentRub"] - PAYMENT) <= 1
    lowered = decision_response.text.lower()
    for word in HIDDEN:
        assert f'"{word.lower()}' not in lowered, f"во внешнем ответе внутреннее поле {word}"

    offer = decision["offer"] or check(client.get(f"/applications/{application_id}/offer"))
    variant = next(v for v in offer["variants"] if v["recommended"])
    accepted = check(
        client.post(f"/offers/{offer['id']}/accept", json={"variantId": variant["id"]})
    )
    contract_id = accepted["contract"]["id"]

    challenge = check(
        client.post(
            f"/contracts/{contract_id}/sign/request", json={"agree": True, "acceptPepRules": True}
        )
    )
    signed = check(
        client.post(
            f"/contracts/{contract_id}/sign",
            json={"requestId": challenge["requestId"], "code": challenge["demoCode"]},
        )
    )
    assert signed["contract"]["status"] == "SIGNED"

    wait_status(client, application_id, {"DISBURSED"})

    loans = check(client.get("/loans"))["items"]
    loan = next(item for item in loans if item["applicationId"] == application_id)
    assert loan["amountRub"] == amount
    assert abs(loan["paymentRub"] - PAYMENT) <= 1

    schedule = check(client.get(f"/loans/{loan['id']}/schedule"))
    assert len(schedule) == term
    assert sum(row["principalRub"] for row in schedule) == amount
    assert all(row["totalRub"] == row["principalRub"] + row["interestRub"] for row in schedule)
