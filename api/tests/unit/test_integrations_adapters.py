"""T-232..T-235: адаптеры реестра, налоговой/ЕИС, АБС (чтение) и БКИ на respx, без сети и Docker."""

# ruff: noqa: PT018 — короткие составные assert читаются лучше, чем разбитые
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.modules.integrations import (
    BkiConsent,
    BureauEvent,
    BureauEventType,
    BureauSubject,
    EventApplication,
    EventObligation,
    IntegrationClient,
    Integrations,
    Ok,
    Reason,
    ScreeningSubject,
    SourceUnavailable,
    build_integrations,
    report_idempotency_key,
    submission_idempotency_key,
)
from app.shared import clock
from tests.unit import integration_samples as samples
from tests.unit.conftest import ListJournal

pytestmark = pytest.mark.unit

REGISTRY = "http://mock-registry:8000/api/v1"
TAX = "http://mock-tax:8000/api/v1"
BANK = "http://mock-bank-core:8000/api/v1"
BKI = "http://mock-credit-bureau:8000/api/v1"


@pytest.fixture
def router() -> Iterator[Any]:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def adapters(client: IntegrationClient) -> Integrations:
    return build_integrations(client)


@pytest.fixture(autouse=True)
def _today() -> Iterator[None]:
    clock.configure(date(2026, 10, 21))
    yield
    clock.configure(None)


def ok(payload: dict[str, Any], **headers: str) -> httpx.Response:
    return httpx.Response(200, json=payload, headers=headers)


def not_found(code: str) -> httpx.Response:
    return httpx.Response(404, json=samples.problem(code, 404))


# --- registry ----------------------------------------------------------------------------------


def test_registry_company_llc_is_mapped(adapters: Integrations, router: Any) -> None:
    router.get(f"{REGISTRY}/companies/0017654322").mock(return_value=ok(samples.COMPANY_LLC))
    result = adapters.registry.get_company("0017654322")
    assert isinstance(result, Ok)
    company = result.data
    assert company is not None
    assert (company.kind, company.name, company.ogrn, company.kpp) == (
        "LEGAL_ENTITY",
        "ООО «СтанкоПром»",
        "1170000004569",
        "001701001",
    )
    assert company.status_code == "LIQUIDATING"
    assert company.okved_main == "25.62" and company.okved_additional == ("28.41",)
    assert company.director is not None and company.director.inn == "001310000115"
    assert [(f.inn, f.share_percent) for f in company.founders] == [("001310000115", 100)]
    assert (
        company.address_unreliable is not None and company.address_unreliable.grn == "2260000987651"
    )
    assert company.pending_exclusion is not None
    assert company.pending_exclusion.objections_deadline == date(2026, 12, 10)
    assert company.region_code == "66" and company.tax_authority_code == "0017"
    assert result.snapshot_meta.source == "EGRUL"
    assert result.snapshot_meta.data_actual_at == date(2026, 10, 20)


def test_registry_company_ip_is_mapped(adapters: Integrations, router: Any) -> None:
    router.get(f"{REGISTRY}/companies/001234567887").mock(return_value=ok(samples.COMPANY_IP))
    result = adapters.registry.get_company("001234567887")
    assert isinstance(result, Ok) and result.data is not None
    ip = result.data
    assert (ip.kind, ip.name, ip.ogrn, ip.kpp) == (
        "INDIVIDUAL_ENTREPRENEUR",
        "Соколова Анна Сергеевна",
        "323000000123450",
        None,
    )
    assert ip.region_code == "16" and ip.director is None and ip.founders == ()


def test_registry_company_not_found_is_normal(adapters: Integrations, router: Any) -> None:
    router.get(f"{REGISTRY}/companies/005779025784").mock(
        return_value=not_found("ENTITY_NOT_FOUND")
    )
    result = adapters.registry.get_company("005779025784")
    assert isinstance(result, Ok) and result.data is None


def test_registry_company_schema_drift(adapters: Integrations, router: Any) -> None:
    broken = samples.copy(samples.COMPANY_LLC)
    del broken["status"]
    router.get(f"{REGISTRY}/companies/0017654322").mock(return_value=ok(broken))
    result = adapters.registry.get_company("0017654322")
    assert isinstance(result, SourceUnavailable) and result.reason is Reason.SCHEMA_ERROR


def test_registry_unavailable_has_masked_resource(adapters: Integrations, router: Any) -> None:
    router.get(f"{REGISTRY}/companies/0017654322").mock(return_value=httpx.Response(503))
    result = adapters.registry.get_company("0017654322")
    assert isinstance(result, SourceUnavailable)
    assert result.reason is Reason.HTTP_5XX and result.attempts == 3
    assert result.resource == "registry:company"


def test_registry_roles_and_bankruptcies(adapters: Integrations, router: Any) -> None:
    router.get(f"{REGISTRY}/persons/001310000115/roles").mock(return_value=ok(samples.PERSON_ROLES))
    router.get(f"{REGISTRY}/bankruptcies/001310000820").mock(return_value=ok(samples.BANKRUPTCIES))
    roles = adapters.registry.get_person_roles("001310000115")
    assert isinstance(roles, Ok)
    assert [(r.role, r.share_percent) for r in roles.data.roles] == [
        ("DIRECTOR", None),
        ("FOUNDER", 100),
    ]
    cases = adapters.registry.get_bankruptcies("001310000820")
    assert isinstance(cases, Ok)
    (case,) = cases.data
    assert (case.case_number, case.stage, case.is_completed) == (
        "А00-45012/2022",
        "COMPLETED",
        True,
    )
    assert case.completed_at == date(2024, 10, 15)


def test_registry_empty_lists_are_ok(adapters: Integrations, router: Any) -> None:
    router.get(f"{REGISTRY}/bankruptcies/0017654322").mock(
        return_value=ok(
            {"meta": samples.meta("FEDRESURS"), "inn": "0017654322", "bankruptcies": []}
        )
    )
    result = adapters.registry.get_bankruptcies("0017654322")
    assert isinstance(result, Ok) and result.data == ()


# --- tax ---------------------------------------------------------------------------------------


def test_tax_profile_is_mapped(adapters: Integrations, router: Any) -> None:
    router.get(f"{TAX}/tax-profile/0015557771").mock(return_value=ok(samples.TAX_PROFILE))
    result = adapters.tax.get_tax_profile("0015557771")
    assert isinstance(result, Ok) and result.data is not None
    p = result.data
    assert (p.tax_debt_rub, p.penalties_rub, p.fines_rub) == (1_150_000, 42_000, 0)
    assert p.regimes[0].code == "USN_INCOME_MINUS_EXPENSES"
    assert (p.income_rub, p.avg_headcount, p.offenses_count) == (95_000_000, 12, 1)
    assert p.mass_address is False and p.no_reports_over_year is False


def test_tax_profile_of_ip_has_no_income_block(adapters: Integrations, router: Any) -> None:
    ip = samples.copy(samples.TAX_PROFILE)
    ip["incomeExpenses"] = None
    ip["avgHeadcount"] = None
    router.get(f"{TAX}/tax-profile/0015557771").mock(return_value=ok(ip))
    result = adapters.tax.get_tax_profile("0015557771")
    assert isinstance(result, Ok) and result.data is not None
    assert result.data.income_rub is None and result.data.avg_headcount is None


def test_financials_year_param_and_lines(adapters: Integrations, router: Any) -> None:
    route = router.get(f"{TAX}/financials/0017654322").mock(return_value=ok(samples.FINANCIALS))
    result = adapters.tax.get_financials("0017654322", year=2025)
    assert route.calls[0].request.url.params["year"] == "2025"
    assert isinstance(result, Ok) and result.data is not None
    f = result.data
    assert f.available_years == (2025, 2024)
    assert f.line("2110") == 420_000_000 and f.line("2400") == 30_700_000 and f.line("9999") is None
    assert f.lines["2330"].previous == 3_100_000
    assert f.summary.revenue_rub == 420_000_000 and f.form_type == "FULL"


def test_financials_without_year_sends_no_param_and_404_is_normal(
    adapters: Integrations, router: Any
) -> None:
    route = router.get(f"{TAX}/financials/001234567887").mock(
        return_value=not_found("STATEMENTS_NOT_FOUND")
    )
    result = adapters.tax.get_financials("001234567887")
    assert "year" not in route.calls[0].request.url.params
    assert isinstance(result, Ok) and result.data is None


def test_sme_status(adapters: Integrations, router: Any) -> None:
    router.get(f"{TAX}/sme-status/0012221117").mock(return_value=ok(samples.SME))
    result = adapters.tax.get_sme_status("0012221117")
    assert isinstance(result, Ok)
    assert (result.data.in_registry, result.data.category, result.data.is_newly_created) == (
        True,
        "MICRO",
        True,
    )
    router.get(f"{TAX}/sme-status/0099999999").mock(
        return_value=ok(
            {
                "meta": samples.meta("FNS_RMSP"),
                "inn": "0099999999",
                "inRegistry": False,
                "category": None,
            }
        )
    )
    absent = adapters.tax.get_sme_status("0099999999")
    assert isinstance(absent, Ok) and absent.data.in_registry is False


def test_self_employed_status_has_no_meta_and_is_retried(
    adapters: Integrations, router: Any
) -> None:
    route = router.post(f"{TAX}/self-employed/status")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json=samples.NPD_TRUE, headers={"X-Mock-Simulated": "true"}),
    ]
    result = adapters.tax.get_self_employed_status("001211122200")
    assert route.call_count == 2
    assert json.loads(route.calls[0].request.content) == {
        "inn": "001211122200",
        "requestDate": "2026-10-21",
    }
    assert isinstance(result, Ok)
    assert result.data.is_self_employed is True
    assert result.snapshot_meta.simulated is True and result.snapshot_meta.source is None


def test_account_blocks_and_contracts(adapters: Integrations, router: Any) -> None:
    blocks = router.get(f"{TAX}/account-blocks/0015557771").mock(return_value=ok(samples.BLOCKS))
    contracts = router.get(f"{TAX}/contracts").mock(return_value=ok(samples.CONTRACTS))
    b = adapters.tax.get_account_blocks("0015557771", bik="040000999")
    assert blocks.calls[0].request.url.params["bik"] == "040000999"
    assert isinstance(b, Ok)
    assert (b.data[0].reason, b.data[0].bik, b.data[0].decided_on) == (
        "TAX_DEBT_COLLECTION",
        "040000111",
        date(2026, 9, 15),
    )
    c = adapters.tax.get_gov_contracts("0012345673", status="IN_PROGRESS")
    params = contracts.calls[0].request.url.params
    assert (params["supplierInn"], params["status"]) == ("0012345673", "IN_PROGRESS")
    assert isinstance(c, Ok)
    contract = c.data[0]
    assert (contract.price_rub, contract.paid_rub, contract.payment_deadline) == (
        12_000_000,
        0,
        date(2027, 1, 15),
    )
    assert contract.customer_inn == "0015000028"


def test_one_tax_endpoint_down_does_not_affect_others(adapters: Integrations, router: Any) -> None:
    router.get(f"{TAX}/tax-profile/0015557771").mock(return_value=httpx.Response(503))
    router.get(f"{TAX}/sme-status/0015557771").mock(return_value=ok(samples.SME))
    profile = adapters.tax.get_tax_profile("0015557771")
    sme = adapters.tax.get_sme_status("0015557771")
    assert isinstance(profile, SourceUnavailable) and profile.resource == "tax:profile"
    assert isinstance(sme, Ok)


# --- bank-core ---------------------------------------------------------------------------------


def test_bank_customer_turnover_loans(adapters: Integrations, router: Any) -> None:
    router.get(f"{BANK}/customers/001234567887").mock(return_value=ok(samples.CUSTOMER))
    turnover_route = router.get(f"{BANK}/customers/001234567887/turnover").mock(
        return_value=ok(samples.TURNOVER)
    )
    router.get(f"{BANK}/customers/001234567887/loans").mock(return_value=ok(samples.LOANS))
    customer = adapters.bank_core.get_customer("001234567887")
    assert isinstance(customer, Ok) and customer.data is not None
    assert customer.data.accounts[0].balance_rub == 412_300
    turnover = adapters.bank_core.get_turnover("001234567887", months=2)
    assert turnover_route.calls[0].request.url.params["months"] == "2"
    assert isinstance(turnover, Ok) and turnover.data is not None
    assert [m.incoming_net_rub for m in turnover.data.months] == [905_000, 905_000]
    assert turnover.data.months[0].counterparties_out == 25
    loans = adapters.bank_core.get_loans("001234567887")
    assert isinstance(loans, Ok) and loans.data is not None
    assert loans.data[0].contract_uid == "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4"


def test_bank_not_a_customer_is_ok_none(adapters: Integrations, router: Any) -> None:
    router.get(url__regex=rf"{BANK}/customers/006110088070.*").mock(
        return_value=not_found("CUSTOMER_NOT_FOUND")
    )
    assert adapters.bank_core.get_customer("006110088070").data is None  # type: ignore[union-attr]
    assert adapters.bank_core.get_turnover("006110088070").data is None  # type: ignore[union-attr]
    assert adapters.bank_core.get_loans("006110088070").data is None  # type: ignore[union-attr]


def test_bank_turnover_unavailable_is_a_result(adapters: Integrations, router: Any) -> None:
    router.get(url__regex=rf"{BANK}/customers/.*/turnover").mock(side_effect=httpx.ReadTimeout("x"))
    result = adapters.bank_core.get_turnover("001234567887", months=12)
    assert isinstance(result, SourceUnavailable)
    assert result.reason is Reason.TIMEOUT and result.resource == "bank_core:turnover"


@pytest.mark.parametrize("months", [0, 25])
def test_bank_turnover_months_range(adapters: Integrations, months: int) -> None:
    with pytest.raises(ValueError, match="months"):
        adapters.bank_core.get_turnover("001234567887", months=months)


def test_screening_maps_hits(adapters: Integrations, router: Any) -> None:
    route = router.post(f"{BANK}/compliance/screening").mock(return_value=ok(samples.SCREENING))
    result = adapters.bank_core.screen(
        [ScreeningSubject("0017654322", "COMPANY"), ScreeningSubject("001310000115", "DIRECTOR")]
    )
    assert json.loads(route.calls[0].request.content) == {
        "subjects": [
            {"inn": "0017654322", "role": "COMPANY"},
            {"inn": "001310000115", "role": "DIRECTOR"},
        ]
    }
    assert isinstance(result, Ok)
    assert result.data.overall == "HIT"
    (hit,) = result.data.aml_hits
    assert (hit.inn, hit.aml_list_name, hit.zsk_risk_level) == (
        "001310000115",
        "ROSFINMONITORING_TERRORISM_EXTREMISM",
        None,
    )
    assert result.data.results[0].zsk_risk_level == "GREEN"


@pytest.mark.parametrize(
    "subjects",
    [
        [],
        [ScreeningSubject("001310000115", "DIRECTOR")],
        [ScreeningSubject("0017654322", "COMPANY")],
        [ScreeningSubject("0017654322", "BOSS")],
    ],
    ids=["пусто", "нет компании", "нет директора", "неизвестная роль"],
)
def test_screening_is_not_called_without_required_subjects(
    adapters: Integrations, router: Any, subjects: list[ScreeningSubject]
) -> None:
    route = router.post(f"{BANK}/compliance/screening").mock(return_value=ok(samples.SCREENING))
    with pytest.raises(ValueError, match="Проверка по спискам"):
        adapters.bank_core.screen(subjects)
    assert route.call_count == 0


def test_screening_for_ip_needs_only_the_entrepreneur(adapters: Integrations, router: Any) -> None:
    router.post(f"{BANK}/compliance/screening").mock(return_value=ok(samples.SCREENING))
    assert isinstance(adapters.bank_core.screen([ScreeningSubject("001234567887", "IE")]), Ok)


# --- credit bureau -----------------------------------------------------------------------------

SUBJECT = BureauSubject("LEGAL_ENTITY", "0015557771", name="ООО «Ромашка»", ogrn="1190000007890")
PERSON = BureauSubject(
    "PERSON",
    "001310000436",
    last_name="Морозов",
    first_name="Олег",
    middle_name="Викторович",
    birth_date=date(1981, 5, 14),
)


def consent(subject_inn: str = "0015557771", **kw: Any) -> BkiConsent:
    base: dict[str, Any] = {
        "consent_id": "cns_01JAK8M2W7",
        "subject_inn": subject_inn,
        "signed_at": datetime(2026, 10, 20, 9, 5, 41, tzinfo=UTC),
        "valid_until": date(2027, 4, 20),
        "purpose": "LOAN_APPLICATION",
        "sign_method": "SIMPLE_ESIGN",
        "signer_inn": "001310000436",
        "text_version": "bki-consent-v1",
    }
    return BkiConsent(**{**base, **kw})


def test_report_request_body_key_and_mapping(
    adapters: Integrations, router: Any, journal: ListJournal
) -> None:
    route = router.post(f"{BKI}/credit-reports").mock(return_value=ok(samples.REPORT))
    result = adapters.credit_bureau.request_report(consent(), SUBJECT, "APP-2026-000123")
    request = route.calls[0].request
    assert request.headers["Idempotency-Key"] == "bki-report:APP-2026-000123:0015557771"
    assert request.headers["X-Api-Key"] == "dev-bki-key"
    body = json.loads(request.content)
    assert body["subject"] == {
        "type": "LEGAL_ENTITY",
        "inn": "0015557771",
        "ogrn": "1190000007890",
        "name": "ООО «Ромашка»",
    }
    assert body["consent"] == {
        "consentId": "cns_01JAK8M2W7",
        "subjectInn": "0015557771",
        "signedAt": "2026-10-20T09:05:41Z",
        "validUntil": "2027-04-20",
        "purpose": "LOAN_APPLICATION",
        "signMethod": "SIMPLE_ESIGN",
        "signerInn": "001310000436",
        "textVersion": "bki-consent-v1",
    }
    assert (body["purpose"], body["applicationRef"]) == ("LOAN_APPLICATION", "APP-2026-000123")
    assert isinstance(result, Ok)
    h = result.data
    assert (h.report_id, h.match_status, h.has_history) == ("rep_01JAK9ZQ1R", "MATCHED", True)
    assert h.summary.current_overdue_days == 94
    assert h.summary.inquiries_30d == 7 and h.summary.inquiries_30d_excluding_own == 6
    assert h.summary.rejected_applications_90d_excluding_own == 2
    (loan,) = h.obligations
    assert (loan.uid, loan.overdue_days, loan.payment_history[-1]) == (
        "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4",
        94,
        ("2026-09", "D60_89"),
    )
    assert [(i.on, i.is_own) for i in h.inquiries] == [
        (date(2026, 10, 21), True),
        (date(2026, 10, 14), False),
    ]
    assert h.applications[0].decision == "REJECTED"
    assert h.bankruptcies[0].case_number == "А00-45012/2022"
    assert h.bureau_score is not None and h.bureau_score.value == 512
    assert result.snapshot_meta.replayed is False
    assert "0015557771" not in repr(journal.records)


def test_report_for_person_sends_name_and_birth_date(adapters: Integrations, router: Any) -> None:
    route = router.post(f"{BKI}/credit-reports").mock(return_value=ok(samples.REPORT))
    adapters.credit_bureau.request_report(consent("001310000436"), PERSON, "APP-1")
    assert json.loads(route.calls[0].request.content)["subject"] == {
        "type": "PERSON",
        "inn": "001310000436",
        "lastName": "Морозов",
        "firstName": "Олег",
        "middleName": "Викторович",
        "birthDate": "1981-05-14",
    }


def test_report_lost_response_replay_is_visible(
    adapters: Integrations, router: Any, journal: ListJournal
) -> None:
    route = router.post(f"{BKI}/credit-reports")
    route.side_effect = [
        httpx.RemoteProtocolError(
            "Server disconnected"
        ),  # LOST_RESPONSE: мок выполнил запрос и оборвал связь
        httpx.Response(200, json=samples.REPORT, headers={"Idempotent-Replayed": "true"}),
    ]
    result = adapters.credit_bureau.request_report(consent(), SUBJECT, "APP-1")
    assert isinstance(result, Ok) and result.snapshot_meta.replayed is True
    keys = {c.request.headers["Idempotency-Key"] for c in route.calls}
    assert keys == {report_idempotency_key("APP-1", "0015557771")}
    assert [r.idempotent_replayed for r in journal.records] == [False, True]
    assert [r.error_code for r in journal.records] == ["CONNECTION_ERROR", None]


def test_report_not_found_subject_is_still_ok(adapters: Integrations, router: Any) -> None:
    empty = samples.copy(samples.REPORT)
    empty.update(
        matchStatus="NOT_FOUND",
        hasHistory=False,
        obligations=[],
        inquiries=[],
        applications=[],
        bankruptcies=[],
        bureauScore=None,
    )
    empty["summary"] = dict.fromkeys(empty["summary"], 0)
    router.post(f"{BKI}/credit-reports").mock(return_value=ok(empty))
    result = adapters.credit_bureau.request_report(consent(), SUBJECT, "APP-1")
    assert isinstance(result, Ok)
    assert (result.data.match_status, result.data.has_history, result.data.obligations) == (
        "NOT_FOUND",
        False,
        (),
    )


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"valid_until": date(2026, 10, 20)}, "CONSENT_EXPIRED"),
        ({"subject_inn": "0099999999"}, "CONSENT_SUBJECT_MISMATCH"),
        (
            {"signed_at": datetime(2026, 10, 21, 23, 59, tzinfo=UTC) + timedelta(days=1)},
            "CONSENT_NOT_YET_VALID",
        ),
        ({"purpose": "OTHER"}, "CONSENT_PURPOSE_MISMATCH"),
    ],
)
def test_report_refused_locally_without_network(
    adapters: Integrations, router: Any, journal: ListJournal, override: dict[str, Any], code: str
) -> None:
    route = router.post(f"{BKI}/credit-reports").mock(return_value=ok(samples.REPORT))
    result = adapters.credit_bureau.request_report(consent(**override), SUBJECT, "APP-1")
    assert isinstance(result, SourceUnavailable)
    assert (result.reason, result.error_code) == (Reason.REJECTED, code)
    assert result.retryable_later is False
    assert route.call_count == 0 and journal.records == []


def test_report_requires_a_consent_argument(adapters: Integrations) -> None:
    with pytest.raises(TypeError):
        adapters.credit_bureau.request_report(SUBJECT, "APP-1")  # type: ignore[call-arg]


def test_report_consent_rejected_by_bureau(adapters: Integrations, router: Any) -> None:
    router.post(f"{BKI}/credit-reports").mock(
        return_value=httpx.Response(403, json=samples.problem("CONSENT_EXPIRED", 403))
    )
    result = adapters.credit_bureau.request_report(consent(), SUBJECT, "APP-1")
    assert isinstance(result, SourceUnavailable)
    assert (result.status_code, result.error_code) == (403, "CONSENT_EXPIRED")


@pytest.mark.parametrize(
    ("kind", "inn"),
    [("LEGAL_ENTITY", "001310000436"), ("PERSON", "0015557771"), ("PERSON", "12345")],
)
def test_subject_type_must_match_inn_length(kind: Any, inn: str) -> None:
    with pytest.raises(ValueError, match="ИНН"):
        BureauSubject(kind, inn)


def test_submit_event_body_and_default_key(adapters: Integrations, router: Any) -> None:
    route = router.post(f"{BKI}/submissions").mock(
        return_value=httpx.Response(202, json=samples.RECEIPT)
    )
    event = BureauEvent(
        event_id="evt_01JAKA3",
        event_type=BureauEventType.OBLIGATION_OPENED,
        occurred_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
        subject=BureauSubject("LEGAL_ENTITY", "0012345673"),
        application=EventApplication(ref="APP-2026-000124"),
        obligation=EventObligation(
            uid="1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-7",
            kind="LOAN",
            role="BORROWER",
            opened_at=date(2026, 10, 21),
            planned_close_at=date(2029, 10, 21),
            amount_rub=8_000_000,
            monthly_payment_rub=295_274,
            secured=False,
        ),
    )
    result = adapters.credit_bureau.submit_event(event)
    request = route.calls[0].request
    assert request.headers["Idempotency-Key"] == "sub:APP-2026-000124:OBLIGATION_OPENED"
    assert json.loads(request.content) == {
        "eventId": "evt_01JAKA3",
        "eventType": "OBLIGATION_OPENED",
        "occurredAt": "2026-10-21T12:00:00Z",
        "subject": {"type": "LEGAL_ENTITY", "inn": "0012345673"},
        "application": {"ref": "APP-2026-000124"},
        "obligation": {
            "uid": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-7",
            "kind": "LOAN",
            "role": "BORROWER",
            "openedAt": "2026-10-21",
            "plannedCloseAt": "2029-10-21",
            "amountRub": 8000000,
            "monthlyPaymentRub": 295274,
            "secured": False,
        },
    }
    assert isinstance(result, Ok) and (result.data.submission_id, result.data.status) == (
        "sub_3372C171510F",
        "ACCEPTED",
    )


def test_submit_event_explicit_key_and_missing_key(adapters: Integrations, router: Any) -> None:
    route = router.post(f"{BKI}/submissions").mock(
        return_value=httpx.Response(202, json=samples.RECEIPT)
    )
    registered = BureauEvent(
        "evt_1",
        BureauEventType.APPLICATION_REGISTERED,
        datetime(2026, 10, 21, 9, tzinfo=UTC),
        BureauSubject("LEGAL_ENTITY", "0012345673"),
        application=EventApplication("APP-1", kind="LOAN", amount_rub=8_000_000, term_months=12),
    )
    adapters.credit_bureau.submit_event(registered, idempotency_key="outbox-17")
    assert route.calls[0].request.headers["Idempotency-Key"] == "outbox-17"
    no_ref = BureauEvent(
        "evt_2",
        BureauEventType.OBLIGATION_CLOSED,
        datetime(2026, 10, 21, 9, tzinfo=UTC),
        BureauSubject("LEGAL_ENTITY", "0012345673"),
        obligation=EventObligation("uid-1", closed_at=date(2026, 10, 21)),
    )
    with pytest.raises(ValueError, match="ключ"):
        adapters.credit_bureau.submit_event(no_ref)
    assert submission_idempotency_key("APP-1", BureauEventType.APPLICATION_DECIDED) == (
        "sub:APP-1:APPLICATION_DECIDED"
    )


def test_submit_event_in_progress_waits_then_returns_original(
    adapters: Integrations, router: Any, fake_time: Any
) -> None:
    route = router.post(f"{BKI}/submissions")
    route.side_effect = [
        httpx.Response(
            409, json=samples.problem("IDEMPOTENCY_IN_PROGRESS", 409), headers={"Retry-After": "1"}
        ),
        httpx.Response(202, json=samples.RECEIPT, headers={"Idempotent-Replayed": "true"}),
    ]
    event = BureauEvent(
        "evt_1",
        BureauEventType.APPLICATION_DECIDED,
        datetime(2026, 10, 21, 9, tzinfo=UTC),
        BureauSubject("LEGAL_ENTITY", "0012345673"),
        application=EventApplication("APP-1", decision="APPROVED"),
    )
    result = adapters.credit_bureau.submit_event(event)
    assert isinstance(result, Ok) and result.snapshot_meta.replayed is True
    assert fake_time.sleeps == [1.0]
