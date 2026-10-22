"""T-132, T-134: vektor, orlov, romashka, garipov и quick-start от входа до первого решения.

Каждая персона подаёт заявку с условиями из своего сценария (`application`) и приходит к исходу
и кодам причин `expectedOutcome` / `expectedReasonCodes` из мока (оракул 30-17). Тест идёт по API
на поднятом стенде и закрывает за собой заявку (отзыв), чтобы его можно было повторять без сброса.

Не покрыто, потому что в коде этого ещё нет: второй проход Гарипова (загрузка выписки, T-130 и
приём файла в api) и второй шаг quick-start (поручитель после принятия встречного).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import httpx
import pytest

from tests.personas.harness import (
    Expected,
    check,
    expected,
    login,
    require_clean_persona,
    scenario,
    sign_all_consents,
    stand_url,
    wait_status,
)

pytestmark = pytest.mark.persona

DECIDED = {"APPROVED", "COUNTER_OFFER", "REJECTED", "MANUAL_REVIEW", "NEEDS_INFO"}
HIDDEN = ("score", "grade", "dscr", "points", "pd", "AML")


@pytest.fixture
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=stand_url(), timeout=30) as c:
        yield c


@contextmanager
def submit_and_decide(
    client: httpx.Client, code: str
) -> Iterator[tuple[Expected, dict[str, Any], dict[str, Any]]]:
    """Вход → черновик с условиями сценария → согласия → отправка → решение; в конце отзыв."""
    want = expected(code)
    login(client, want.inn)
    require_clean_persona(client, code)
    draft = check(
        client.post(
            "/applications",
            json={
                "productCode": want.product_code,
                "amountRub": want.amount_rub,
                "termMonths": want.term_months,
            },
        ),
        201,
    )
    application_id = draft["id"]
    try:
        consents = sign_all_consents(client, application_id)
        assert consents["allSigned"], consents
        check(client.post(f"/applications/{application_id}/submit"))
        decided = wait_status(client, application_id, DECIDED)
        response = client.get(f"/applications/{application_id}/decision")
        decision = check(response)
        lowered = response.text.lower()
        for word in HIDDEN:
            assert f'"{word.lower()}' not in lowered, f"во внешнем ответе внутреннее поле {word}"
        yield want, decided, decision
    finally:
        # Заявка в работе мешала бы повтору (require_clean_persona); отзыв делает её терминальной
        current = client.get(f"/applications/{application_id}")
        if current.status_code == 200 and "WITHDRAW" in current.json()["allowedActions"]:
            client.post(f"/applications/{application_id}/withdraw")


def plain(text: str) -> str:
    """Тексты решения пишут суммы с неразрывным пробелом: «1\u00a0150\u00a0000\u00a0₽»."""
    return text.replace("\u00a0", " ")


def reason_codes(decision: dict[str, Any]) -> list[str]:
    return [reason["code"] for reason in decision["reasons"]]


def assert_codes(want: Expected, decision: dict[str, Any]) -> None:
    """Главный код первый, остальные входят в набор (30-17, «Сводка»)."""
    got = reason_codes(decision)
    assert got[:1] == want.reason_codes[:1], got
    assert set(want.reason_codes) <= set(got), got


@pytest.mark.parametrize("code", ["vektor", "romashka"])
def test_rejected_personas_get_oracle_reasons(client: httpx.Client, code: str) -> None:
    with submit_and_decide(client, code) as (want, decided, decision):
        assert decided["status"] == want.outcome == "REJECTED"
        assert decision["outcome"] == "REJECTED"
        assert decision["terms"] is None
        assert decision["offer"] is None
        assert_codes(want, decision)


def test_vektor_reason_text_names_liquidation(client: httpx.Client) -> None:
    with submit_and_decide(client, "vektor") as (_want, _decided, decision):
        assert reason_codes(decision) == ["COMPANY_NOT_ACTIVE"]
        assert "ликвидации" in decision["reasons"][0]["text"]


def test_romashka_tax_debt_is_the_main_reason_with_exact_amounts(client: httpx.Client) -> None:
    """30-17: долг 1 150 000 больше десятой части 7 916 667; погасить 358 334 до 791 666."""
    with submit_and_decide(client, "romashka") as (want, _decided, decision):
        assert (
            reason_codes(decision)
            == want.reason_codes
            == ["TAX_ARREARS_HIGH", "CURRENT_OVERDUE_90"]
        )
        main, second = decision["reasons"]
        assert "1 150 000" in plain(main["text"])
        assert "358 334" in plain(main["action"])
        assert "791 666" in plain(main["action"])
        assert "больше трёх месяцев" in second["text"]


def test_orlov_is_explained_at_login_and_has_nobody_to_log_in(client: httpx.Client) -> None:
    want = expected("orlov")
    assert want.outcome == "NOT_ELIGIBLE"
    assert want.reason_codes == ["SELF_EMPLOYED"]
    assert want.product_code is None
    assert want.term_months is None
    roles = check(client.get(f"/auth/roles/{want.inn}"))
    assert roles["kind"] == "NOT_ELIGIBLE"
    assert roles["reasonCode"] == want.reason_codes[0]
    assert roles["people"] == []
    assert roles["companies"] == []
    assert roles["company"]["inn"] == want.inn


def test_garipov_first_pass_asks_for_a_statement(client: httpx.Client) -> None:
    with submit_and_decide(client, "garipov") as (want, decided, decision):
        assert want.final_outcome == "APPROVED"
        assert decided["status"] == want.outcome == "NEEDS_INFO"
        assert decision["outcome"] == "NEEDS_INFO"
        assert_codes(want, decision)
        assert "выписк" in decision["reasons"][0]["action"].lower()
        assert decision["terms"] is None


@pytest.mark.skip(
    reason="Второй проход Гарипова: генератор выписки T-130 и приём файла в api ещё не сделаны"
)
def test_garipov_second_pass_with_statement_is_approved() -> None:
    """Ожидание 30-17: выписка 12 × 700 000 → APPROVED, B (84), 22,5%, 57 674 ₽."""


def test_quick_start_first_answer_is_a_conditional_counter_offer(client: httpx.Client) -> None:
    with submit_and_decide(client, "quick-start") as (want, decided, decision):
        assert want.final_outcome == "APPROVED"
        assert decided["status"] == want.outcome == "COUNTER_OFFER"
        assert decision["outcome"] == "COUNTER_OFFER"
        assert_codes(want, decision)
        offer = decision["offer"]
        assert offer is not None
        assert offer["variantsStatus"] == "READY"
        variant = offer["variants"][0]
        # те же условия, но с поручительством владельца или залогом (30-17, quick-start)
        assert variant["kind"] == "CONDITIONAL_SECURITY"
        assert variant["collateralRequired"] is True
        assert (variant["amountRub"], variant["termMonths"]) == (1_000_000, 24)
        assert Decimal(str(variant["ratePercent"])) == Decimal("24.0")
        assert abs(variant["paymentRub"] - 52_871) <= 1
        assert abs(variant["overpaymentRub"] - 268_907) <= 1


def test_quick_start_owner_logs_in_by_personal_inn_as_future_guarantor(
    client: httpx.Client,
) -> None:
    """Директор, владелец и будущий поручитель — один человек; по личному ИНН он видит компанию."""
    want = expected("quick-start")
    body = scenario(want.code)
    assert body["application"]["guarantor"] is None
    (user,) = body["users"]
    roles = check(client.get(f"/auth/roles/{user['inn']}"))
    assert roles["kind"] == "PERSON"
    assert [c["company"]["inn"] for c in roles["companies"]] == [want.inn]
    assert roles["companies"][0]["role"] == "DIRECTOR"
