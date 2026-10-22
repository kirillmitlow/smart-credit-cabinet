"""T-259, T-340, T-341: чистые части предложения — УИд, хеш, платёж карточки, варианты и тексты клиенту."""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.modules.decisioning import client_factor_phrases, decide, payment_for
from app.modules.decisioning.types import Outcome
from app.modules.offers import contracts, terms
from app.modules.pipeline import decision_view, hooks
from tests.fixtures.core_personas import quick_start, snabkontrakt, sokolova, t_base

pytestmark = pytest.mark.unit

APP_ID = uuid.UUID("018f0000-0000-7000-8000-000000000001")
BANNED_WORDS = re.compile(r"грейд|балл|скоринг|\bPD\b|DSCR|стоп-фактор|флаг", re.IGNORECASE)


def _uid_is_valid(value: str) -> bool:
    """Контроль УИд как в моках (758-П): UUID и контрольный символ через дефис."""
    if len(value) != 38 or value[-2] != "-":
        return False
    uid = uuid.UUID(value[:-2])
    check = sum(int(char, 16) * (i % 10 + 1) for i, char in enumerate(uid.hex)) % 16
    return value.lower() == f"{uid}-{check:x}"


def test_contract_uid_is_stable_valid_and_new_per_revision() -> None:
    first = contracts.contract_uid(APP_ID, 1)

    assert first == contracts.contract_uid(APP_ID, 1)
    assert _uid_is_valid(first)
    assert contracts.contract_uid(APP_ID, 2) != first
    assert contracts.contract_uid(uuid.uuid4(), 1) != first


def test_contract_number_follows_application_number() -> None:
    assert contracts.contract_number("АЗ-2026-000001", 1) == "КД-2026-000001"
    assert contracts.contract_number("АЗ-2026-000001", 2) == "КД-2026-000001/2"


def test_content_hash_depends_only_on_body() -> None:
    body = '{"a":1}'

    assert contracts.content_hash_of(body) == contracts.content_hash_of(body)
    assert contracts.content_hash_of(body) != contracts.content_hash_of('{"a":2}')
    assert re.fullmatch(r"[0-9a-f]{64}", contracts.content_hash_of(body))


def test_card_payment_equals_schedule_and_calculator_math() -> None:
    card = terms.loan_terms("EXPRESS", 500_000, Decimal("0.215"), 12)

    assert card.payment_rub == payment_for("ANNUITY", 500_000, Decimal("0.215"), 12)
    assert abs(card.payment_rub - 46_677) <= 1  # оракул 30-17
    assert card.last_payment_rub == 46_679
    assert card.overpayment_rub == 60_126
    assert card.total_rub == 500_000 + card.overpayment_rub
    assert [r.number for r in terms.preview(card.schedule)] == [1, 2, 3, 12]
    assert card.schedule[-1].balance == 0


def test_contract_product_without_amortization_pays_interest_only() -> None:
    card = terms.loan_terms("CONTRACT", 1_200_000, Decimal("0.24"), 6)

    assert card.payment_rub == 24_000
    assert card.last_payment_rub == 1_224_000
    assert card.overpayment_rub == 144_000


def test_approved_draft_is_the_request_as_it_was_asked() -> None:
    inp = sokolova()
    result = decide(inp)

    drafts = hooks._drafts(inp, result)

    assert [d.kind for d in drafts] == ["AS_REQUESTED"]
    assert drafts[0].recommended
    assert not drafts[0].collateral_required
    assert (drafts[0].amount_rub, drafts[0].term_months) == (500_000, 12)
    assert drafts[0].annual_rate == Decimal("0.215")


def test_conditional_security_variant_is_marked_and_explained() -> None:
    inp = quick_start()
    result = decide(inp)

    drafts = hooks._drafts(inp, result)

    assert result.outcome == Outcome.COUNTER_OFFER
    assert len(drafts) == 1
    assert drafts[0].collateral_required
    assert drafts[0].recommended
    assert drafts[0].what_changed.get("security") is True


def test_counter_offer_from_the_optimizer_gives_three_labelled_drafts() -> None:
    inp = snabkontrakt()
    result = decide(inp)

    drafts = hooks._drafts(inp, result)

    assert result.outcome == Outcome.COUNTER_OFFER
    assert [d.label for d in drafts] == [
        "Ваша сумма, дольше срок",
        "Ваш срок, меньше сумма",
        "Другой продукт или с залогом",
    ]
    assert [d.recommended for d in drafts] == [True, False, False]
    assert [(d.product_code, d.amount_rub, d.term_months) for d in drafts] == [
        ("WORKING_CAPITAL", 8_000_000, 36),
        ("WORKING_CAPITAL", 3_400_000, 12),
        ("CONTRACT", 8_000_000, 4),
    ]
    assert all(d.note for d in drafts)  # «почему» одной фразой
    assert drafts[0].what_changed == {"termMonths": {"from": 12, "to": 36}}
    assert drafts[1].what_changed == {"amountRub": {"from": 8_000_000, "to": 3_400_000}}
    contract_change = drafts[2].what_changed
    assert contract_change["productCode"] == {"from": "WORKING_CAPITAL", "to": "CONTRACT"}
    assert "1001500002826000127" in contract_change["requirements"][0]  # что нужно от клиента


def test_client_factors_for_approved_name_strengths_only() -> None:
    phrases = client_factor_phrases(decide(sokolova()).numbers.factors)

    assert phrases["whatHelped"] == ["чистая кредитная история", "стабильная выручка"]
    assert phrases["whatAffected"] == []


def test_client_headlines_use_no_internal_words() -> None:
    assert all(not BANNED_WORDS.search(text) for text in decision_view.HEADLINES.values())


def test_aml_reason_is_not_disclosed_to_client() -> None:
    explain: dict[str, Any] = {
        "explanations": [
            {
                "code": "AML_LIST",
                "client": "Не можем предложить кредит по внутренним правилам банка",
                "underwriter": "Совпадение со списком X",
                "action": "Обратиться в отделение банка",
            },
            {"code": "GRADE_CAPPED", "client": "", "underwriter": "служебное", "action": "—"},
        ]
    }

    reasons = decision_view._reasons(explain)

    assert [r.code for r in reasons] == [decision_view.GENERIC_CODE]  # служебный код отброшен
    assert "AML" not in reasons[0].text
    assert "список" not in reasons[0].text.lower()


def _flagged_young_input():  # type: ignore[no-untyped-def]
    """T-BASE с массовым адресом и директором в анкете, которого нет в реестре."""
    base = t_base()
    tax = replace(base.snapshot.tax, mass_address=True)
    return replace(
        base,
        application=replace(base.application, director_name_in_form="Иванов Иван Иванович"),
        snapshot=replace(base.snapshot, tax=tax),
    )


def test_antifraud_flags_are_not_disclosed_to_client_but_data_mismatch_is() -> None:
    """Правило антифрода не подсказываем: ни код, ни шаг андеррайтера. Расхождение клиент уточнит сам."""
    specialist = "Заявку смотрит специалист. Обычно до 1 рабочего дня"
    result = decide(_flagged_young_input())  # настоящие тексты ядра: флаг массовости и расхождение
    explain: dict[str, Any] = {
        "reasons": [{"code": r.code, "kind": r.kind.value} for r in result.reasons],
        "explanations": [
            {"code": e.code, "client": e.client, "underwriter": e.underwriter, "action": e.action}
            for e in result.explanations
        ],
    }
    assert [r.code for r in result.reasons][:2] == ["MASS_REGISTRATION", "DATA_MISMATCH"]

    reasons = decision_view._reasons(explain)

    by_code = {r.code: r for r in reasons}
    assert specialist in by_code[decision_view.GENERIC_CODE].text
    assert by_code[decision_view.GENERIC_CODE].action == ""
    assert by_code["DATA_MISMATCH"].text.startswith("Мы нашли расхождение")
    assert by_code["DATA_MISMATCH"].action == ""  # «Запросить выписку» — шаг андеррайтера
    blob = " ".join(r.code + r.text + r.action for r in reasons)
    assert not re.search(r"MASS|ANOMALY|накачк|транзит|договор|Запросить", blob)


def test_stop_factor_action_is_still_shown_to_the_client() -> None:
    explain: dict[str, Any] = {
        "reasons": [{"code": "TAX_ARREARS_HIGH", "kind": "STOP"}],
        "explanations": [
            {
                "code": "TAX_ARREARS_HIGH",
                "client": "Долг по налогам",
                "action": "Погасить 358 334 ₽",
            }
        ],
    }
    (reason,) = decision_view._reasons(explain)
    assert reason.action == "Погасить 358 334 ₽"


def test_client_sees_one_line_per_distinct_text_when_a_code_repeats() -> None:
    line = {"code": "TURNOVER_ANOMALY", "client": "Заявку смотрит специалист", "action": "x"}
    other = {"code": "DATA_MISMATCH", "client": "Мы нашли расхождение", "action": ""}
    reasons = decision_view._reasons({"explanations": [line, line, other, other]})
    assert [r.code for r in reasons] == [decision_view.GENERIC_CODE, "DATA_MISMATCH"]


def test_rate_breakdown_adds_up_to_the_rate() -> None:
    numbers = decide(sokolova()).numbers
    breakdown = numbers.rate_breakdown
    assert breakdown is not None
    assert numbers.rate is not None
    keys = ("key_rate", "spread", "expected_loss", "expenses", "capital_charge", "raw_rate", "rate")
    explain = {"numbers": {"rate_breakdown": {k: str(getattr(breakdown, k)) for k in keys}}}

    parts = decision_view._rate_breakdown(explain)

    assert sum(p.percent for p in parts) == numbers.rate * 100 == Decimal("21.5")
    assert parts[0].label.startswith("Ключевая")
