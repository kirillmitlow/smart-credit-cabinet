"""T-232, T-233: адаптеры реестра, налоговой и ЕИС против живых mock-registry и mock-tax."""

# ruff: noqa: PT018 — короткие составные assert читаются лучше, чем разбитые
from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from app.modules.integrations import Integrations, Ok, SourceUnavailable
from app.shared import clock
from tests.contract.conftest import ListJournal, Persona

pytestmark = pytest.mark.contract

PersonaFactory = Callable[[str], Persona]


def data(result: object) -> object:
    assert isinstance(result, Ok), result
    return result.data


# --- registry ----------------------------------------------------------------------------------


def test_sokolova_is_active_individual_entrepreneur(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("sokolova")
    result = live.registry.get_company(p.inn)
    assert isinstance(result, Ok) and result.data is not None
    company = result.data
    assert company.kind == "INDIVIDUAL_ENTREPRENEUR"
    assert company.status_code == "ACTIVE"
    assert company.name == "Соколова Анна Сергеевна"
    assert company.registration_date == date(2023, 4, 12)
    assert company.okved_main == "56.10"
    assert company.director is None and company.founders == ()
    assert result.snapshot_meta.source == "EGRIP" and result.snapshot_meta.simulated is True
    assert result.snapshot_meta.request_id


def test_sokolova_has_no_bankruptcies_and_has_role(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("sokolova")
    assert data(live.registry.get_bankruptcies(p.inn)) == ()
    roles = data(live.registry.get_person_roles(p.inn))
    assert [r.role for r in roles.roles] == ["INDIVIDUAL_ENTREPRENEUR"]  # type: ignore[attr-defined]


def test_vektor_is_liquidating_with_unreliable_address(
    live: Integrations, persona: PersonaFactory
) -> None:
    company = data(live.registry.get_company(persona("vektor").inn))
    assert company is not None
    assert company.status_code == "LIQUIDATING"  # type: ignore[attr-defined]
    assert company.address_unreliable is not None  # type: ignore[attr-defined]
    assert company.director is not None and company.founders  # type: ignore[attr-defined]


def test_orlov_self_employed_is_404_normal_answer(
    live: Integrations, persona: PersonaFactory
) -> None:
    result = live.registry.get_company(persona("orlov").inn)
    assert isinstance(result, Ok) and result.data is None


def test_t_bankrupt_second_founder_has_completed_case(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("t-bankrupt")
    company = data(live.registry.get_company(p.inn))
    assert [f.inn for f in company.founders if f.share_percent == 40.0]  # type: ignore[attr-defined]
    founder = p.person("founder:second")
    cases = data(live.registry.get_bankruptcies(founder["inn"]))
    assert len(cases) == 1  # type: ignore[arg-type]
    case = cases[0]  # type: ignore[index]
    assert case.is_completed and case.subject_type == "PERSON"
    assert case.completed_at is not None and case.started_at < case.completed_at
    assert data(live.registry.get_bankruptcies(p.inn)) == ()  # у самой компании дел нет


def test_invalid_inn_is_rejected_not_retried(live: Integrations, journal: ListJournal) -> None:
    result = live.registry.get_company("0017654321")  # контрольная сумма не сходится
    assert isinstance(result, SourceUnavailable)
    assert (result.status_code, result.error_code) == (400, "INN_INVALID")
    assert len(journal.records) == 1


def test_calls_are_journaled_with_masked_inn(
    live: Integrations, persona: PersonaFactory, journal: ListJournal
) -> None:
    p = persona("sokolova")
    live.registry.get_company(p.inn)
    (row,) = journal.records
    assert row.system == "registry" and row.status_code == 200
    assert row.subject_inn_masked == f"{p.inn[:4]}******{p.inn[-2:]}"
    assert p.inn not in row.path


# --- tax ---------------------------------------------------------------------------------------


def test_romashka_tax_debt_and_simplified_statements(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("romashka")
    profile = data(live.tax.get_tax_profile(p.inn))
    assert profile.tax_debt_rub == 1_150_000  # type: ignore[attr-defined]
    assert profile.regimes[0].code == "USN_INCOME_MINUS_EXPENSES"  # type: ignore[attr-defined]
    financials = data(live.tax.get_financials(p.inn))
    assert financials is not None
    assert financials.form_type == "SIMPLIFIED"  # type: ignore[attr-defined]
    revenue = financials.line("2110")  # type: ignore[attr-defined]
    assert revenue is not None
    if p.builtin:
        assert revenue == 95_000_000
    else:
        assert (
            85_000_000 < revenue < 105_000_000
        )  # 7,9 млн в месяц × 12, без точных цифр встроенной персоны
    sme = data(live.tax.get_sme_status(p.inn))
    assert sme.in_registry  # type: ignore[attr-defined]


def test_snabkontrakt_statements_two_years_and_eis_contract(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("snabkontrakt")
    financials = data(live.tax.get_financials(p.inn))
    assert financials is not None
    assert {2024, 2025} <= set(financials.available_years)  # type: ignore[attr-defined]
    previous_year = data(live.tax.get_financials(p.inn, year=2024))
    assert previous_year is not None and previous_year.year == 2024  # type: ignore[attr-defined]
    if p.builtin:
        assert financials.line("2110") == 180_000_000  # type: ignore[attr-defined]
        assert financials.line("2400") == 13_200_000  # type: ignore[attr-defined]
        assert financials.line("2330") == 1_200_000  # type: ignore[attr-defined]
    contracts = data(live.tax.get_gov_contracts(p.inn))
    active = [c for c in contracts if c.status == "IN_PROGRESS"]  # type: ignore[attr-defined]
    assert len(active) == 1
    contract = active[0]
    assert contract.price_rub == 12_000_000 and contract.paid_rub == 0
    assert contract.payment_deadline > clock.today()
    assert len(contract.registry_number) == 19
    only_executed = data(live.tax.get_gov_contracts(p.inn, status="EXECUTED"))
    assert all(c.status == "EXECUTED" for c in only_executed)  # type: ignore[attr-defined]


def test_garipov_has_no_statements_but_has_profile(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("garipov")
    result = live.tax.get_financials(p.inn)
    assert isinstance(result, Ok) and result.data is None  # 404 — нормальный ответ для ИП
    profile = data(live.tax.get_tax_profile(p.inn))
    assert profile is not None and profile.income_rub is None  # type: ignore[attr-defined]
    assert data(live.tax.get_gov_contracts(p.inn)) == ()


def test_orlov_is_self_employed(live: Integrations, persona: PersonaFactory) -> None:
    orlov = data(live.tax.get_self_employed_status(persona("orlov").inn))
    assert orlov.is_self_employed is True  # type: ignore[attr-defined]
    not_npd = live.tax.get_self_employed_status(persona("sokolova").inn)
    assert isinstance(not_npd, Ok) and not_npd.data.is_self_employed is False
    assert not_npd.snapshot_meta.source is None  # у НПД блока meta нет


def test_account_blocks_are_empty_for_clean_company(
    live: Integrations, persona: PersonaFactory
) -> None:
    assert data(live.tax.get_account_blocks(persona("sokolova").inn)) == ()
    assert data(live.tax.get_account_blocks(persona("sokolova").inn, bik="040000999")) == ()


def test_each_tax_resource_answers_independently(
    live: Integrations, persona: PersonaFactory, journal: ListJournal
) -> None:
    p = persona("romashka")
    results = [
        live.tax.get_tax_profile(p.inn),
        live.tax.get_financials(p.inn),
        live.tax.get_sme_status(p.inn),
        live.tax.get_account_blocks(p.inn),
        live.tax.get_gov_contracts(p.inn),
    ]
    assert all(isinstance(r, Ok) for r in results)
    assert {r.system for r in journal.records} == {"tax"}
