"""T-125: ЕФРСБ и БКИ разделяют дела, прочие моки получают согласованные тела."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.common.accounts import make_account
from app.common.inn import inn_is_valid
from app.roles.bank_core.admin import BankCoreAdminHandler
from app.roles.bank_core.schemas import BankCoreBody
from app.roles.bki.admin import BkiAdminHandler
from app.roles.bki.schemas import BkiSubjectBody
from app.roles.registry.admin import RegistryHandler
from app.roles.registry.schemas import RegistryBody
from app.roles.scenarios.expand import resolved_spec
from app.roles.scenarios.identity import expand_identity
from app.roles.scenarios.other_expand import expand_other
from app.roles.scenarios.schemas import ScenarioSpec
from app.roles.tax.admin import TaxHandler
from app.roles.tax.schemas import TaxBody

TODAY = date(2026, 10, 21)


def scenario(**overrides: Any) -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {
            "code": "other-test",
            "title": "Прочие системы",
            "company": {"form": "LLC", "ageMonths": 120},
            "people": {
                "director": {"ref": "boss"},
                "founders": [
                    {"ref": "owner", "sharePercent": 60},
                    {"ref": "minority", "sharePercent": 40},
                ],
            },
            **overrides,
        }
    )


def base(spec: ScenarioSpec, bik: str = "040000999") -> dict[str, Any]:
    result = expand_identity(resolved_spec(spec), spec.code or "other-test", TODAY, set())
    identity = result["identity"]
    result["tax"] = TaxBody().model_dump(mode="json", by_alias=True)
    result["bankCore"] = BankCoreBody().model_dump(mode="json", by_alias=True)
    result["bki"] = []
    if spec.bank and spec.bank.is_customer:
        individual = identity["form"] == "IP"
        result["bankCore"].update(
            {
                "customer": {
                    "type": "INDIVIDUAL_ENTREPRENEUR" if individual else "LEGAL_ENTITY",
                    "name": identity["shortName"],
                    "customerSince": "2020-01-01",
                },
                "accounts": [
                    {
                        "number": make_account(bik, "40802" if individual else "40702", 100),
                        "type": "SETTLEMENT",
                        "status": "OPEN",
                        "openedAt": "2020-01-01",
                        "balanceRub": 10,
                    }
                ],
            }
        )
    return result


def checked(
    spec: ScenarioSpec, before: dict[str, Any] | None = None, bik: str = "040000999"
) -> dict[str, Any]:
    original = before if before is not None else base(spec, bik)
    result = expand_other(resolved_spec(spec), original, spec.code or "other-test", TODAY, bik)
    inn = result["identity"]["inn"]
    RegistryHandler().check(inn, RegistryBody.model_validate(result["registry"]))
    TaxHandler().check(inn, TaxBody.model_validate(result["tax"]))
    if bik == "040000999":
        BankCoreAdminHandler().check(inn, BankCoreBody.model_validate(result["bankCore"]))
    for entry in result["bki"]:
        BkiAdminHandler().check(entry["inn"], BkiSubjectBody.model_validate(entry["body"]))
    for entry in result["bankSubjects"]:
        BankCoreAdminHandler().check(entry["inn"], BankCoreBody.model_validate(entry["body"]))
    return result


def test_minority_founder_bankruptcy_reuses_person_and_preserves_other_data() -> None:
    spec = scenario(
        bankruptcies=[
            {
                "subject": "founder:minority",
                "stage": "COMPLETED",
                "startedYearsAgo": 4,
                "completedYearsAgo": 2,
            }
        ]
    )
    before = base(spec)
    saved = deepcopy(before)
    result = checked(spec, before)
    assert before == saved
    assert result == checked(spec, before)
    minority = before["identity"]["subjectRefs"]["founder:minority"]
    case = result["registry"]["bankruptcies"][0]
    assert case["subjectInn"] == minority
    assert minority not in {
        before["identity"]["subjectRefs"]["director"],
        before["identity"]["subjectRefs"]["owner"],
    }
    body = next(x["body"] for x in result["bki"] if x["inn"] == minority)
    assert body["subject"]["inn"] == minority
    assert body["bankruptcies"] == [
        {k: case[k] for k in ("caseNumber", "stage", "startedAt", "completedAt")}
    ]
    assert case["startedAt"] == "2022-10-21"
    assert case["completedAt"] == "2024-10-21"
    assert case["caseNumber"].startswith("А00-")
    assert case["caseNumber"].endswith("/2022")
    assert result["registry"]["entity"]["status"]["code"] == "ACTIVE"


@pytest.mark.parametrize("form", ["LLC", "IP"])
def test_ongoing_company_case_changes_company_status(form: str) -> None:
    spec = scenario(
        company={"form": form},
        people=None,
        bankruptcies=[
            {
                "subject": "company",
                "stage": "PROPERTY_REALIZATION",
                "startedYearsAgo": 0.5,
            }
        ],
    )
    result = checked(spec)
    assert result["identity"]["status"] == "BANKRUPT"
    assert result["registry"]["entity"]["status"] == {
        "code": "BANKRUPT",
        "name": "Банкротство",
        "since": "2026-04-21",
    }
    assert result["bki"][0]["body"]["subject"]["type"] == (
        "PERSON" if form == "IP" else "LEGAL_ENTITY"
    )


def test_aliases_share_one_bki_subject_and_keep_existing_history() -> None:
    spec = scenario(
        people=None,
        bankruptcies=[
            {
                "subject": "director",
                "stage": "COMPLETED",
                "startedYearsAgo": 3,
                "completedYearsAgo": 2,
            },
            {"subject": "owner", "stage": "RESTRUCTURING", "startedYearsAgo": 0.5},
        ],
    )
    before = base(spec)
    person = before["identity"]["director"]
    subject = {
        "type": "PERSON",
        **{k: person[k] for k in ("inn", "lastName", "firstName", "middleName", "birthDate")},
    }
    body = BkiSubjectBody.model_validate(
        {"subject": subject, "inquiries": [{"date": "2026-10-01"}]}
    ).model_dump(mode="json", by_alias=True)
    before["bki"] = [{"inn": person["inn"], "body": body}]
    result = checked(spec, before)
    assert len(result["bki"]) == 1
    assert len(result["bki"][0]["body"]["bankruptcies"]) == 2
    assert result["bki"][0]["body"]["inquiries"] == body["inquiries"]
    assert result == checked(spec, result)


@pytest.mark.parametrize(
    "case",
    [
        {"subject": "founder:missing", "stage": "RESTRUCTURING", "startedYearsAgo": 1},
        {"subject": "company", "stage": "COMPLETED", "startedYearsAgo": 1},
        {
            "subject": "company",
            "stage": "RESTRUCTURING",
            "startedYearsAgo": 1,
            "completedYearsAgo": 0.5,
        },
        {"subject": "company", "stage": "COMPLETED", "startedYearsAgo": 1, "completedYearsAgo": 2},
        {"subject": "company", "stage": "UNKNOWN", "startedYearsAgo": 1},
        {"subject": "company", "stage": "RESTRUCTURING", "startedYearsAgo": float("inf")},
    ],
)
def test_invalid_cases_are_rejected_without_partial_mutation(case: dict[str, Any]) -> None:
    spec = scenario(bankruptcies=[case])
    before = base(spec)
    saved = deepcopy(before)
    with pytest.raises(ValueError, match="bankruptcies|заверш|completedAt|stage|YearsAgo"):
        checked(spec, before)
    assert before == saved


def test_snabkontrakt_contract_and_executed_default_are_consistent() -> None:
    spec = scenario(
        contracts=[
            {
                "customer": {"name": "Демо-больница"},
                "subject": "Поставка",
                "priceRub": 12000000,
                "concluded": "-2M",
                "executionIn": "+2M",
                "paymentIn": "+3M",
                "paidRub": 0,
            },
            {
                "customer": {"name": "Демо-школа"},
                "subject": "Исполнено",
                "priceRub": 100000,
                "status": "EXECUTED",
            },
        ]
    )
    contracts = checked(spec)["tax"]["contracts"]
    first, second = contracts
    assert first["concludedAt"] == "2026-08-21"
    assert first["paymentDeadline"] == "2027-01-21"
    assert first["priceRub"] == 12000000
    assert first["paidRub"] == 0
    assert second["paidRub"] == second["priceRub"]
    assert second["executionDeadline"] < TODAY.isoformat()
    assert len({c["registryNumber"] for c in contracts}) == 2
    assert all(len(c["registryNumber"]) == 19 and c["registryNumber"].isdigit() for c in contracts)
    assert all(
        inn_is_valid(c["customer"]["inn"]) and c["customer"]["inn"].startswith("00")
        for c in contracts
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"paidRub": 12000001},
        {"concluded": "2027-01-01", "executionIn": "2026-01-01"},
        {"status": "UNKNOWN"},
        {"concluded": "bad-date"},
        {"customer": {"name": "Ошибка", "inn": "7707083893"}},
    ],
)
def test_invalid_contracts_rejected(overrides: dict[str, Any]) -> None:
    spec = scenario(
        contracts=[
            {"customer": {"name": "Демо"}, "subject": "Поставка", "priceRub": 12000000, **overrides}
        ]
    )
    with pytest.raises(ValueError, match="Оплачено|Срок|status|Неверная|ИНН"):
        checked(spec)


def test_blocking_creates_paired_tax_decision_and_bank_status_with_configured_bik() -> None:
    spec = scenario(bank={"isCustomer": True}, tax={"accountBlocked": True, "taxDebtRub": 12345})
    result = checked(spec, bik="040000111")
    block = result["tax"]["accountBlocks"][0]
    assert block["bik"] == "040000111"
    assert block["taxAuthorityCode"] == result["identity"]["inn"][:4]
    assert block["reason"] == "TAX_DEBT_COLLECTION"
    assert result["bankCore"]["accounts"][0]["status"] == "BLOCKED"
    assert result["tax"]["taxProfile"]["debts"]["taxDebtRub"] == 12345


def test_non_customer_and_closed_accounts_cannot_be_blocked() -> None:
    spec = scenario(tax={"accountBlocked": True})
    with pytest.raises(ValueError, match="клиент"):
        checked(spec)
    spec = scenario(bank={"isCustomer": True}, tax={"accountBlocked": True})
    before = base(spec)
    before["bankCore"]["accounts"][0]["status"] = "CLOSED"
    with pytest.raises(ValueError, match="действующим"):
        checked(spec, before)


def test_unblocking_preserves_foreign_decisions_and_closed_accounts() -> None:
    spec = scenario(bank={"isCustomer": True}, tax={"accountBlocked": False})
    before = base(spec)
    before["bankCore"]["accounts"][0]["status"] = "BLOCKED"
    decision = {
        "number": "1",
        "date": "2026-01-01",
        "taxAuthorityCode": "0001",
        "bik": "040000111",
        "reason": "OTHER",
        "liftedAt": None,
    }
    before["tax"]["accountBlocks"] = [decision, {**decision, "number": "2", "bik": "040000999"}]
    result = checked(spec, before)
    assert result["tax"]["accountBlocks"] == [decision]
    assert result["bankCore"]["accounts"][0]["status"] == "OPEN"


def test_tax_flags_and_director_aml_use_existing_identities() -> None:
    spec = scenario(
        tax={"massAddress": True, "massDirector": True, "disqualifiedManagement": True},
        compliance={"amlListed": "DIRECTOR", "zsk": "RED", "internalStopList": True},
    )
    result = checked(spec)
    flags = result["tax"]["taxProfile"]["riskFlags"]
    assert flags["massAddress"]
    assert flags["massDirector"]
    assert flags["disqualifiedManagement"]
    company = result["bankCore"]["compliance"]
    assert company["aml"] is None
    assert company["zsk"]["riskLevel"] == "RED"
    assert company["internalStopList"] is not None
    subjects = {x["inn"]: x["body"]["compliance"] for x in result["bankSubjects"]}
    director = result["identity"]["director"]["inn"]
    assert subjects[director]["aml"]["listName"] == "ROSFINMONITORING_TERRORISM_EXTREMISM"
    assert all(body["zsk"] is None for body in subjects.values())
    assert set(subjects) == {director}
    assert all(body["aml"] is None for inn, body in subjects.items() if inn != director)


@pytest.mark.parametrize("form", ["IP", "SELF_EMPLOYED"])
def test_director_aml_requires_director(form: str) -> None:
    spec = scenario(company={"form": form}, people=None, compliance={"amlListed": "DIRECTOR"})
    with pytest.raises(ValueError, match="director"):
        checked(spec)


def test_company_aml_and_no_compliance_request_still_generate_clear_participant_bodies() -> None:
    spec = scenario(compliance={"amlListed": "COMPANY"})
    result = checked(spec)
    assert result["bankCore"]["compliance"]["aml"] is not None
    assert all(x["body"]["compliance"]["aml"] is None for x in result["bankSubjects"])
    plain = checked(scenario())
    assert plain["bankCore"]["compliance"]["zsk"]["riskLevel"] == "GREEN"
    assert plain["bankSubjects"] == []


@given(started=st.integers(0, 120), completed=st.integers(0, 120))
def test_completed_case_dates_and_mirrors_agree_for_random_months(
    started: int, completed: int
) -> None:
    old, recent = max(started, completed), min(started, completed)
    spec = scenario(
        bankruptcies=[
            {
                "subject": "owner",
                "stage": "COMPLETED",
                "startedYearsAgo": old / 12,
                "completedYearsAgo": recent / 12,
            }
        ]
    )
    result = checked(spec)
    case = result["registry"]["bankruptcies"][0]
    assert case["startedAt"] <= case["completedAt"] <= TODAY.isoformat()
    mirrored = result["bki"][0]["body"]["bankruptcies"][0]
    assert all(case[key] == mirrored[key] for key in mirrored)
