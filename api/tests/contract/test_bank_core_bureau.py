"""T-234, T-235: адаптеры АБС (чтение) и БКИ против живых mock-bank-core и mock-credit-bureau."""

# ruff: noqa: PT018 — короткие составные assert читаются лучше, чем разбитые
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.modules.integrations import (
    BkiConsent,
    BureauEvent,
    BureauEventType,
    BureauSubject,
    EventApplication,
    Integrations,
    Ok,
    Reason,
    ScreeningSubject,
    SourceUnavailable,
)
from app.shared import clock
from tests.contract.conftest import ListJournal, Persona

pytestmark = pytest.mark.contract

PersonaFactory = Callable[[str], Persona]


def ref() -> str:
    """Своя заявка на каждый тест: ключ идемпотентности не пересекается с прошлыми прогонами."""
    return f"APP-CT-{uuid4().hex[:10]}"


def consent_for(inn: str, signer_inn: str) -> BkiConsent:
    return BkiConsent(
        consent_id=f"cns_{uuid4().hex[:10]}",
        subject_inn=inn,
        signed_at=clock.now() - timedelta(minutes=1),
        valid_until=clock.today() + timedelta(days=180),
        purpose="LOAN_APPLICATION",
        sign_method="SIMPLE_ESIGN",
        signer_inn=signer_inn,
        text_version="bki-consent-v1",
    )


def company_subject(p: Persona) -> BureauSubject:
    return BureauSubject(
        "LEGAL_ENTITY", p.inn, name=p.identity["shortName"], ogrn=p.identity["ogrn"]
    )


def person_subject(person: dict[str, str]) -> BureauSubject:
    birth = person.get("birthDate")
    return BureauSubject(
        "PERSON",
        person["inn"],
        last_name=person["lastName"],
        first_name=person["firstName"],
        middle_name=person.get("middleName"),
        birth_date=date.fromisoformat(birth) if birth else None,
    )


def report(live: Integrations, p: Persona, subject: BureauSubject, signer: str | None = None):  # type: ignore[no-untyped-def]
    director = p.identity.get("director")
    signer_inn = signer or (director["inn"] if director else p.inn)
    return live.credit_bureau.request_report(consent_for(subject.inn, signer_inn), subject, ref())


# --- bank-core ---------------------------------------------------------------------------------


def test_sokolova_is_customer_with_exact_turnover(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("sokolova")
    customer = live.bank_core.get_customer(p.inn)
    assert isinstance(customer, Ok) and customer.data is not None
    assert customer.data.customer_since == date(2023, 5, 2)
    assert customer.data.accounts[0].balance_rub == 412_300
    assert customer.data.accounts[0].number.startswith("40802810")
    turnover = live.bank_core.get_turnover(p.inn, months=12)
    assert isinstance(turnover, Ok) and turnover.data is not None
    assert len(turnover.data.months) == 12
    assert {m.incoming_net_rub for m in turnover.data.months} == {905_000}
    assert {m.incoming_net_rub - m.outgoing_rub for m in turnover.data.months} == {110_000}
    assert {m.counterparties_in for m in turnover.data.months} == {2}
    assert [m.month for m in turnover.data.months] == sorted(m.month for m in turnover.data.months)


def test_snabkontrakt_customer_with_long_turnover(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("snabkontrakt")
    customer = live.bank_core.get_customer(p.inn)
    assert isinstance(customer, Ok) and customer.data is not None
    assert customer.data.kind == "LEGAL_ENTITY"
    turnover = live.bank_core.get_turnover(p.inn, months=24)
    assert isinstance(turnover, Ok) and turnover.data is not None
    assert 20 <= len(turnover.data.months) <= 24
    last = turnover.data.months[-1]
    assert last.incoming_net_rub == 18_300_000  # 15 млн + НДС 22%, ряд без шума
    assert last.incoming_rub >= last.incoming_net_rub
    twelve = live.bank_core.get_turnover(p.inn, months=12)
    assert isinstance(twelve, Ok) and twelve.data is not None and len(twelve.data.months) == 12


def test_garipov_is_not_a_customer(live: Integrations, persona: PersonaFactory) -> None:
    p = persona("garipov")
    for result in (
        live.bank_core.get_customer(p.inn),
        live.bank_core.get_turnover(p.inn),
        live.bank_core.get_loans(p.inn),
    ):
        assert isinstance(result, Ok) and result.data is None


def test_quick_start_has_three_months_of_turnover(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("quick-start")
    turnover = live.bank_core.get_turnover(p.inn, months=12)
    assert isinstance(turnover, Ok) and turnover.data is not None
    assert 2 <= len(turnover.data.months) <= 3  # обслуживается 3 месяца: больше не вернётся


def test_t_aml_director_hits_the_list(live: Integrations, persona: PersonaFactory) -> None:
    p = persona("t-aml")
    director = p.person("director")
    result = live.bank_core.screen(
        [ScreeningSubject(p.inn, "COMPANY"), ScreeningSubject(director["inn"], "DIRECTOR")]
    )
    assert isinstance(result, Ok)
    assert result.data.overall == "HIT"
    (hit,) = result.data.aml_hits
    assert (hit.inn, hit.role) == (director["inn"], "DIRECTOR")
    assert hit.aml_list_name == "ROSFINMONITORING_TERRORISM_EXTREMISM"
    company = next(r for r in result.data.results if r.role == "COMPANY")
    assert company.aml_listed is False and company.zsk_risk_level in {"GREEN", "YELLOW", "RED"}


def test_clean_company_screening_is_clear(live: Integrations, persona: PersonaFactory) -> None:
    p = persona("sokolova")
    result = live.bank_core.screen([ScreeningSubject(p.inn, "IE")])
    assert isinstance(result, Ok) and result.data.overall == "CLEAR"


def test_our_loan_shares_uid_with_bureau_report(
    live: Integrations, persona: PersonaFactory
) -> None:
    """contractUid в АБС = uid в БКИ: по нему признаки не считают один кредит дважды (7.5)."""
    p = persona("our-loan")
    loans = live.bank_core.get_loans(p.inn)
    assert isinstance(loans, Ok) and loans.data
    our = loans.data[0]
    assert our.status == "ACTIVE" and our.outstanding_rub == our.amount_rub
    result = report(live, p, company_subject(p))
    assert isinstance(result, Ok)
    assert our.contract_uid in {o.uid for o in result.data.obligations}


# --- credit bureau -----------------------------------------------------------------------------


def test_romashka_report_has_94_days_overdue(live: Integrations, persona: PersonaFactory) -> None:
    p = persona("romashka")
    result = report(live, p, company_subject(p))
    assert isinstance(result, Ok)
    h = result.data
    assert (h.match_status, h.has_history, h.subject_inn) == ("MATCHED", True, p.inn)
    assert h.summary.current_overdue_days == 94
    assert h.summary.max_overdue_days_24m >= 94
    assert h.summary.current_overdue_rub > 0
    assert h.summary.inquiries_30d_excluding_own == 6
    assert (
        h.summary.inquiries_30d >= h.summary.inquiries_30d_excluding_own + 1
    )  # наш запрос виден, но отдельно
    assert h.summary.rejected_applications_90d_excluding_own == 2
    active = [o for o in h.obligations if o.status == "ACTIVE"]
    assert any(o.overdue_days == 94 and o.payment_history[-1][1] == "D90_119" for o in active)
    assert any(i.is_own for i in h.inquiries) and not all(i.is_own for i in h.inquiries)
    assert h.bureau_score is not None  # только для показа
    assert result.snapshot_meta.source == "CREDIT_BUREAU" and result.snapshot_meta.replayed is False


def test_quick_start_company_not_found_owner_clean(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("quick-start")
    company = report(live, p, company_subject(p))
    assert isinstance(company, Ok)
    assert (company.data.match_status, company.data.has_history) == ("NOT_FOUND", False)
    assert company.data.obligations == () and company.data.bureau_score is None
    assert (
        company.data.summary.total_debt_rub == 0 and company.data.summary.current_overdue_days == 0
    )

    owner = p.person("owner")
    person = report(live, p, person_subject(owner), signer=owner["inn"])
    assert isinstance(person, Ok)
    assert (person.data.match_status, person.data.has_history) == ("MATCHED", True)
    assert person.data.summary.current_overdue_days == 0
    assert person.data.summary.total_debt_rub == 0
    assert {o.kind for o in person.data.obligations} >= {"CREDIT_CARD"}
    assert person.data.bankruptcies == ()


def test_t_overdue_45_has_current_overdue(live: Integrations, persona: PersonaFactory) -> None:
    p = persona("t-overdue-45")
    result = report(live, p, company_subject(p))
    assert isinstance(result, Ok)
    assert result.data.summary.current_overdue_days == 45
    assert any(o.overdue_days == 45 and o.status == "ACTIVE" for o in result.data.obligations)
    assert result.data.summary.current_overdue_rub > 0


def test_t_bankrupt_case_is_in_bureau_too(live: Integrations, persona: PersonaFactory) -> None:
    p = persona("t-bankrupt")
    founder = p.person("founder:second")
    result = report(live, p, person_subject(founder), signer=founder["inn"])
    assert isinstance(result, Ok)
    (case,) = result.data.bankruptcies
    registry = live.registry.get_bankruptcies(founder["inn"])
    assert isinstance(registry, Ok)
    assert (registry.data[0].case_number, registry.data[0].started_at) == (
        case.case_number,
        case.started_at,
    )


def test_same_application_and_subject_returns_same_report(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("sokolova")
    application = ref()
    subject = person_subject(p.person("owner"))
    consent = consent_for(subject.inn, subject.inn)
    first = live.credit_bureau.request_report(consent, subject, application)
    second = live.credit_bureau.request_report(consent, subject, application)
    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert second.data.report_id == first.data.report_id
    assert second.snapshot_meta.replayed is True and first.snapshot_meta.replayed is False


def test_expired_consent_never_reaches_the_bureau(
    live: Integrations, persona: PersonaFactory, journal: ListJournal
) -> None:
    p = persona("sokolova")
    subject = person_subject(p.person("owner"))
    expired = BkiConsent(
        "cns_old", subject.inn, clock.now() - timedelta(days=200), clock.today() - timedelta(days=1),
        "LOAN_APPLICATION", "SIMPLE_ESIGN", subject.inn, "bki-consent-v1",
    )  # fmt: skip
    result = live.credit_bureau.request_report(expired, subject, ref())
    assert isinstance(result, SourceUnavailable)
    assert (result.reason, result.error_code) == (Reason.REJECTED, "CONSENT_EXPIRED")
    assert journal.records == []


def test_submit_events_are_accepted_and_deduplicated_by_event_id(
    live: Integrations, persona: PersonaFactory
) -> None:
    p = persona("romashka")
    application = ref()
    subject = BureauSubject("LEGAL_ENTITY", p.inn)
    registered = BureauEvent(
        event_id=f"evt_{uuid4().hex[:10]}",
        event_type=BureauEventType.APPLICATION_REGISTERED,
        occurred_at=clock.now(),
        subject=subject,
        application=EventApplication(application, kind="LOAN", amount_rub=3_000_000, term_months=6),
    )
    first = live.credit_bureau.submit_event(registered)
    assert isinstance(first, Ok) and first.data.status == "ACCEPTED"
    again = live.credit_bureau.submit_event(registered)  # тот же eventId и ключ: исходный ответ
    assert isinstance(again, Ok) and again.data.submission_id == first.data.submission_id
    assert again.snapshot_meta.replayed is True

    decided = BureauEvent(
        event_id=f"evt_{uuid4().hex[:10]}",
        event_type=BureauEventType.APPLICATION_DECIDED,
        occurred_at=clock.now(),
        subject=subject,
        application=EventApplication(application, decision="REJECTED"),
    )
    result = live.credit_bureau.submit_event(decided)
    assert isinstance(result, Ok) and result.data.submission_id != first.data.submission_id


def test_decision_for_unregistered_application_is_rejected_not_retried(
    live: Integrations, persona: PersonaFactory, journal: ListJournal
) -> None:
    p = persona("romashka")
    event = BureauEvent(
        event_id=f"evt_{uuid4().hex[:10]}",
        event_type=BureauEventType.APPLICATION_DECIDED,
        occurred_at=clock.now(),
        subject=BureauSubject("LEGAL_ENTITY", p.inn),
        application=EventApplication(ref(), decision="APPROVED"),
    )
    result = live.credit_bureau.submit_event(event)
    assert isinstance(result, SourceUnavailable)
    assert (result.status_code, result.error_code) == (404, "APPLICATION_NOT_FOUND")
    assert len(journal.records) == 1
