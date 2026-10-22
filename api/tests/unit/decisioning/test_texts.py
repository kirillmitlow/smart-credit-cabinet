"""Справочник текстов (T-298, 30-12): полнота, подстановка, язык клиента, AML, форматтер."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.modules.decisioning import decide
from app.modules.decisioning import texts_ru as tx
from app.modules.decisioning.reasons import CODE_KINDS, make, order_reasons
from app.modules.decisioning.types import Grade, ReasonCode, ReasonKind
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal
FORBIDDEN_FOR_CLIENT = ("грейд", "балл", "скоринг", "pd", "dscr", "стоп-фактор", "флаг")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def sample_params(code: str) -> dict[str, str | int | Decimal]:
    out: dict[str, str | int | Decimal] = {}
    for name in tx.TEXTS[code].params:
        if name.endswith("_rub"):
            out[name] = 1_150_000
        elif name in {"share", "pd", "shock", "p_def12"}:
            out[name] = D("0.1453")
        elif name in {"dscr", "stress_dscr", "threshold", "value", "zone_from", "zone_to"}:
            out[name] = D("1.25")
        elif "date" in name or name in {
            "apply_after",
            "completed_at",
            "available_from",
            "payment_deadline",
        }:
            out[name] = "2026-10-21"
        elif name.endswith(("_months", "months", "_days", "days", "points", "attempts")):
            out[name] = 6
        else:
            out[name] = "значение"
    return out


def test_catalog_covers_exactly_the_reason_codes() -> None:
    assert set(tx.TEXTS) == set(CODE_KINDS)


@pytest.mark.parametrize("code", sorted(tx.TEXTS))
def test_every_code_has_all_three_texts(code: str) -> None:
    entry = tx.TEXTS[code]
    assert entry.underwriter.strip()
    assert entry.action.strip()
    if entry.client_visible:
        assert entry.client.strip()
    else:
        assert code == "GRADE_CAPPED"  # единственный код, который клиенту не показывается


@pytest.mark.parametrize("code", sorted(tx.TEXTS))
def test_placeholders_are_declared_and_all_get_filled(code: str) -> None:
    entry = tx.TEXTS[code]
    used = {
        name
        for template in (entry.client, entry.underwriter, entry.action)
        for name in PLACEHOLDER.findall(template)
    }
    assert used <= set(entry.params), f"{code}: не объявлены {used - set(entry.params)}"
    explanation = tx.render(ReasonCode(code, CODE_KINDS[code], sample_params(code)))
    for text in (explanation.client, explanation.underwriter, explanation.action):
        assert not {"{", "}"} & set(text), f"{code}: незаполненная скобка в «{text}»"


@pytest.mark.parametrize("code", sorted(tx.TEXTS))
def test_client_text_avoids_banking_jargon(code: str) -> None:
    client = tx.render(ReasonCode(code, CODE_KINDS[code], sample_params(code))).client.lower()
    assert not any(word in client for word in FORBIDDEN_FOR_CLIENT), client


def test_aml_client_text_does_not_reveal_the_reason() -> None:
    explanation = tx.render(make("AML_LIST", subject="DIRECTOR"))
    assert explanation.client == "Не можем предложить кредит по внутренним правилам банка"
    lowered = explanation.client.lower()
    assert "аml" not in lowered
    assert "список" not in lowered
    assert "директор" not in lowered
    assert "DIRECTOR" in explanation.underwriter  # андеррайтеру причина видна


def test_flags_say_a_specialist_looks_and_promise_one_working_day() -> None:
    for code in ("MASS_REGISTRATION", "TURNOVER_ANOMALY", "GRADE_NEEDS_REVIEW", "NEAR_THRESHOLD"):
        assert "Заявку смотрит специалист" in tx.TEXTS[code].client
        assert "Обычно до 1 рабочего дня" in tx.TEXTS[code].client


def test_all_emitted_reasons_carry_the_declared_params() -> None:
    """Каждый код, который ядро выдало на персонах, несёт параметры, нужные его шаблонам."""
    seen: set[str] = set()
    for name, build in cp.PERSONAS.items():
        for reason in decide(build()).reasons:
            seen.add(reason.code)
            needed = {
                n
                for t in (
                    tx.TEXTS[reason.code].client,
                    tx.TEXTS[reason.code].underwriter,
                    tx.TEXTS[reason.code].action,
                )
                for n in PLACEHOLDER.findall(t)
            }
            assert needed <= set(reason.params), (
                f"{name}/{reason.code}: нет {needed - set(reason.params)}"
            )
    assert {"TAX_ARREARS_HIGH", "DSCR_LOW", "REVENUE_UNKNOWN", "COLLATERAL_REVIEW"} <= seen


def test_persona_texts_match_the_oracle_wording() -> None:
    """Формулировки 30-17 для романтичных клиентов: деньги в формате «1 150 000 ₽»."""
    nbsp = " "
    romashka = decide(cp.romashka()).explanations
    assert romashka[0].client.startswith(f"У вас есть долг по налогам 1{nbsp}150{nbsp}000{nbsp}₽")
    assert f"358{nbsp}334{nbsp}₽" in romashka[0].action
    assert f"791{nbsp}666{nbsp}₽" in romashka[0].action
    assert "14,53%" in romashka[0].underwriter
    assert "просрочка больше трёх месяцев" in romashka[1].client
    vektor = decide(cp.vektor()).explanations[0].client
    assert (
        vektor
        == "По данным реестра компания не действует (в стадии ликвидации). Кредит даём только действующему бизнесу"
    )
    orlov = decide(cp.orlov()).explanations[0]
    assert orlov.client.startswith("Вы зарегистрированы как самозанятый")
    snab = decide(cp.snabkontrakt()).explanations[0].client
    assert f"739{nbsp}163{nbsp}₽" in snab
    assert f"360{nbsp}000{nbsp}₽" in snab
    bankrupt = decide(cp.t_bankrupt()).explanations[0]
    assert "компании" not in bankrupt.client
    assert "учредителя" in bankrupt.client
    assert "21.10.2029" in bankrupt.action  # подать заявку после 21.10.2029 (30-17)


def test_risk_too_high_names_the_biggest_weaknesses_in_client_words() -> None:
    phrase = tx.top_deficit_phrases(
        _score_with_deficits({"SC_AGE": 12, "SC_TREND": 10, "SC_TAX": 8, "SC_CLIENT": 6})
    )
    assert phrase.count(";") == 2  # не больше трёх
    assert "выручка снижается" in phrase
    assert "бизнесу пока немного лет" in phrase


def _score_with_deficits(deficits: dict[str, int]):  # type: ignore[no-untyped-def]
    from app.modules.decisioning.scoring import ScoreResult
    from app.modules.decisioning.types import FactorScore

    factors = tuple(
        FactorScore(code, "x", 0 if code in deficits else 5, deficits.get(code, 5))
        for code in tx.FACTOR_CLIENT_PHRASES
    )
    return ScoreResult(10, Grade.E, D("0.3"), factors, None)


def test_top_deficit_phrases_without_big_gaps() -> None:
    result = _score_with_deficits({})
    assert tx.top_deficit_phrases(result) == "общая картина"


# ---------------------------------------------------------------- форматтер


def test_formatters() -> None:
    nbsp = " "
    assert tx.format_money(1_150_000) == f"1{nbsp}150{nbsp}000{nbsp}₽"
    assert tx.format_money(-500) == f"-500{nbsp}₽"
    assert tx.format_money(0) == f"0{nbsp}₽"
    assert tx.format_percent(D("0.1453")) == "14,53%"
    assert tx.format_percent(D("0.2")) == "20%"
    assert tx.format_decimal(D("1.2500")) == "1,25"
    assert tx.format_decimal(D("0.8960")) == "0,896"
    assert tx.format_decimal(D("74")) == "74"
    assert tx.format_value("x", "2026-10-21") == "21.10.2026"
    assert tx.format_value("x", None) == "—"
    assert tx.format_value("x", True) == "да"
    assert tx.format_value("x", False) == "нет"
    assert tx.format_value("count", 5) == "5"
    assert tx.format_value("amount_rub", 5) == f"5{nbsp}₽"
    assert tx.format_value("note", "текст") == "текст"


def test_missing_parameter_degrades_to_a_dash_not_a_crash() -> None:
    reason = ReasonCode("DUPLICATE_APPLICATION", ReasonKind.STOP, {})
    assert "№—" in tx.render(reason).client


def test_reason_ordering_keeps_first_catalog_code_and_exact_duplicates_only() -> None:
    a = make("DSCR_LOW", payment_rub=1)
    ordered = order_reasons(
        [make("COLLATERAL_REVIEW"), a, make("TAX_ARREARS_HIGH"), a, make("GRADE_CAPPED")]
    )
    assert [r.code for r in ordered] == [
        "TAX_ARREARS_HIGH",
        "DSCR_LOW",
        "COLLATERAL_REVIEW",
        "GRADE_CAPPED",
    ]
    two = order_reasons(
        [make("NEAR_THRESHOLD", metric="DSCR"), make("NEAR_THRESHOLD", metric="STRESS_DSCR")]
    )
    assert len(two) == 2
    assert (
        order_reasons([make("RISK_TOO_HIGH", points=1), make("DSCR_LOW")])[0].code
        == "RISK_TOO_HIGH"
    )
