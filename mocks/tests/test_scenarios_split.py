"""Пустое тело — SKIPPED; комплаенс не-клиента нельзя молча потерять."""

from datetime import date

from app.roles.scenarios.expand import expand
from app.roles.scenarios.schemas import ScenarioSpec
from app.roles.scenarios.split import System, split


def test_non_customer_keeps_zsk_without_opening_customer_account() -> None:
    expanded = expand(
        ScenarioSpec(title="Не-клиент", preset="LLC_HEALTHY"), date(2026, 10, 21), set()
    )
    bank = split(expanded)[System.BANK_CORE]
    assert len(bank) == 1
    assert bank[0].body["customer"] is None
    assert bank[0].body["accounts"] == []
    assert bank[0].body["compliance"]["zsk"]["riskLevel"] == "GREEN"


def test_self_employed_empty_bki_and_bank_are_skipped() -> None:
    expanded = expand(ScenarioSpec(title="НПД", preset="SELF_EMPLOYED"), date(2026, 10, 21), set())
    parts = split(expanded)
    assert parts[System.BANK_CORE] == []
    assert parts[System.BKI] == []
    assert parts[System.TAX][0].body["npd"] is not None
