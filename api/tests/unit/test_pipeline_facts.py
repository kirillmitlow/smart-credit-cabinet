"""T-272: перевод моделей адаптеров во вход `decide()` (pipeline/facts.py, R4).

Каждый источник → поля `DecisionInput`; недоступность → `UNAVAILABLE`, `Ok(None)` → `NOT_FOUND`.
Ответы собраны заглушками «как у мока» (`pipeline_world.py`), без сети и базы.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.decisioning import DecisionInput, decide
from app.modules.decisioning.types import (
    ApplicantKind,
    Context,
    Outcome,
    Product,
    Snapshot,
    SourceStatus,
    SubjectRole,
)
from app.modules.integrations import Ok, SourceUnavailable
from app.modules.integrations.credit_bureau import map_report
from app.modules.integrations.registry import map_company
from app.modules.pipeline import facts
from tests.fixtures import pipeline_world as pw
from tests.fixtures.core_personas import load_policy

pytestmark = pytest.mark.unit


def records_of(world: pw.World, inn: str, *, bki: bool = True) -> facts.Records:
    """Опросить заглушки так же, как конвейер, и положить ответы в записи для facts."""
    ports = pw.build_integrations(world)
    results = {
        facts.REGISTRY: ports.registry.get_company(inn),
        facts.TAX_PROFILE: ports.tax.get_tax_profile(inn),
        facts.FINANCIALS: ports.tax.get_financials(inn),
        facts.SME: ports.tax.get_sme_status(inn),
        facts.BLOCKS: ports.tax.get_account_blocks(inn),
        facts.CUSTOMER: ports.bank_core.get_customer(inn),
        facts.TURNOVER: ports.bank_core.get_turnover(inn),
        facts.LOANS: ports.bank_core.get_loans(inn),
    }
    card = results[facts.REGISTRY]
    subjects = facts.screening_subjects(inn, card.data if isinstance(card, Ok) else None)
    for s in subjects:
        results[f"{facts.BANKRUPTCIES}|{s.inn}"] = ports.registry.get_bankruptcies(s.inn)
    if inn in world.screening:
        request = [pw.ScreeningSubject(s.inn, s.compliance_role) for s in subjects]
        results[facts.COMPLIANCE] = ports.bank_core.screen(request)
    if bki:
        bki_list = facts.bki_subjects(inn, card.data if isinstance(card, Ok) else None, None)
        for s in bki_list:
            results[f"{facts.BKI_REPORT}|{s.inn}"] = _bki(world, s)
    return facts.Records(_record(key, inn, res) for key, res in results.items())


def _bki(world: pw.World, subject: facts.Subject) -> Ok[object] | SourceUnavailable:
    world.calls.append(("credit_bureau:report", subject.inn))
    if "credit_bureau:report" in world.down:
        return SourceUnavailable(pw.System.CREDIT_BUREAU, pw.Reason.TIMEOUT)
    payload = world.bki[subject.inn]
    return Ok(map_report(payload), pw._meta(pw.System.CREDIT_BUREAU), raw=payload)


def _record(key: str, applicant_inn: str, result: object) -> facts.SourceRecord:
    resource, _, subject = key.partition("|")
    inn = subject or applicant_inn
    if isinstance(result, SourceUnavailable):
        return facts.SourceRecord(resource, inn, SourceStatus.UNAVAILABLE)
    assert isinstance(result, Ok)
    status = SourceStatus.OK if result.data is not None else SourceStatus.NOT_FOUND
    return facts.SourceRecord(
        resource, inn, status, f"snap-{resource}-{inn}", pw.DATA_DATE, result.data
    )


def snapshot_for(world: pw.World, inn: str, product: Product = Product.EXPRESS) -> Snapshot:
    records = records_of(world, inn)
    card_rec = records.get(facts.REGISTRY, inn)
    card = card_rec.data if card_rec and card_rec.usable else None
    subjects = facts.bki_subjects(inn, card, None)
    return facts.build_snapshot(
        records, applicant_inn=inn, product=product, bki_subject_list=subjects
    )


# ---------------------------------------------------------------- Соколова: каждый источник


def test_sokolova_registry_and_tax_fields() -> None:
    snap = snapshot_for(pw.sokolova_world(), pw.SOKOLOVA_INN)

    assert snap.registry.meta.status == SourceStatus.OK
    assert snap.registry.meta.snapshot_id == f"snap-registry:company-{pw.SOKOLOVA_INN}"
    assert snap.registry.meta.data_as_of == date(2026, 10, 20)
    assert snap.registry.kind == ApplicantKind.INDIVIDUAL_ENTREPRENEUR
    assert snap.registry.registration_date == date(2023, 4, 12)
    assert snap.registry.okved_main == "56.10"
    assert snap.registry.status_code == "ACTIVE"
    assert snap.tax.regimes == ("USN_INCOME",)
    assert (snap.tax.tax_debt_rub, snap.tax.account_block_active, snap.tax.sme_category) == (
        0,
        False,
        None,
    )
    assert snap.npd.meta.status == SourceStatus.NOT_REQUESTED  # НПД нужен только при 404 реестра
    assert snap.contracts.meta.status == SourceStatus.NOT_REQUESTED  # не CONTRACT


def test_sokolova_bank_core_fields() -> None:
    snap = snapshot_for(pw.sokolova_world(), pw.SOKOLOVA_INN)

    assert snap.customer.is_customer
    assert snap.customer.customer_since == date(2023, 5, 2)
    assert snap.customer.our_loans == ()
    assert len(snap.turnover.months) == 12
    first, last = snap.turnover.months[0], snap.turnover.months[-1]
    assert (first.month, last.month) == (date(2025, 10, 1), date(2026, 9, 1))
    assert (last.incoming_net_rub, last.outgoing_rub, last.counterparties_in) == (
        905_000,
        795_000,
        2,
    )
    assert snap.compliance.meta.status == SourceStatus.OK
    assert [(r.inn, r.role, r.aml_listed) for r in snap.compliance.results] == [
        (pw.SOKOLOVA_INN, SubjectRole.COMPANY, False)  # роль IE в АБС → COMPANY в ядре
    ]
    assert [(b.inn, b.role, b.meta.status) for b in snap.bankruptcies] == [
        (pw.SOKOLOVA_INN, SubjectRole.COMPANY, SourceStatus.OK)
    ]


def test_sokolova_bki_report_fields() -> None:
    snap = snapshot_for(pw.sokolova_world(), pw.SOKOLOVA_INN)

    (subject,) = snap.bki
    assert subject.role == SubjectRole.COMPANY
    assert subject.meta.status == SourceStatus.OK
    report = subject.report
    assert report is not None
    assert (report.history_months, report.active_obligations, report.closed_obligations) == (
        30,
        1,
        1,
    )
    assert (report.total_debt_rub, report.monthly_payments_rub) == (60_000, 3_000)
    assert [(o.uid, o.kind, o.status, o.monthly_payment_rub) for o in report.obligations] == [
        ("card-sok", "CREDIT_CARD", "ACTIVE", 3_000),
        ("loan-sok", "LOAN", "CLOSED", 0),
    ]


def test_sokolova_input_decides_like_the_oracle() -> None:
    snap = snapshot_for(pw.sokolova_world(), pw.SOKOLOVA_INN)
    app = facts.build_application(
        "APP", {"productCode": "EXPRESS", "amountRub": 500_000, "termMonths": 12, "draft": {}}
    )
    result = decide(DecisionInput(app, snap, Context(date(2026, 10, 21)), load_policy()))

    assert result.outcome == Outcome.APPROVED
    assert (result.numbers.score_points, result.numbers.rate) == (92, Decimal("0.215"))


# ---------------------------------------------------------------- Ромашка: ООО, директор, отчётность


def test_romashka_legal_entity_fields() -> None:
    snap = snapshot_for(pw.romashka_world(), pw.ROMASHKA_INN, Product.WORKING_CAPITAL)

    assert snap.registry.kind == ApplicantKind.LEGAL_ENTITY
    assert snap.registry.director_inn == pw.ROMASHKA_DIRECTOR
    assert [(f.inn, f.share_percent, f.is_person) for f in snap.registry.founders] == [
        (pw.ROMASHKA_DIRECTOR, Decimal(100), True)
    ]
    assert (snap.tax.tax_debt_rub, snap.tax.penalties_rub, snap.tax.offenses_count) == (
        1_150_000,
        42_000,
        1,
    )
    assert [
        (y.year, y.revenue_rub, y.net_profit_rub, y.interest_paid_rub)
        for y in snap.financials.years
    ] == [(2025, 95_000_000, 4_000_000, 600_000)]
    # не клиент банка: 404 → NOT_FOUND, а не «недоступно»
    assert snap.customer.meta.status == SourceStatus.NOT_FOUND
    assert not snap.customer.is_customer
    assert snap.turnover.meta.status == SourceStatus.NOT_FOUND
    # человек — директор и учредитель сразу: одна проверка с ролью DIRECTOR
    assert [(b.inn, b.role) for b in snap.bankruptcies] == [
        (pw.ROMASHKA_INN, SubjectRole.COMPANY),
        (pw.ROMASHKA_DIRECTOR, SubjectRole.DIRECTOR),
    ]
    assert [(b.role, b.meta.status) for b in snap.bki] == [
        (SubjectRole.COMPANY, SourceStatus.OK),
        (SubjectRole.DIRECTOR, SourceStatus.OK),
    ]
    company_report = snap.bki[0].report
    assert company_report is not None
    assert (company_report.current_overdue_days, company_report.inquiries_30d_excl_own) == (94, 6)
    assert (company_report.rejected_90d_excl_own, company_report.monthly_payments_rub) == (
        2,
        318_500,
    )


# ---------------------------------------------------------------- недоступность и 404


def test_unavailable_registry_and_bureau_become_unavailable_status() -> None:
    world = pw.sokolova_world()
    world.down.update({"registry:company", "credit_bureau:report", "tax:profile"})

    snap = snapshot_for(world, pw.SOKOLOVA_INN)

    assert snap.registry.meta.status == SourceStatus.UNAVAILABLE
    assert snap.registry.meta.snapshot_id is None
    assert snap.tax.meta.status == SourceStatus.UNAVAILABLE
    assert [b.meta.status for b in snap.bki] == [SourceStatus.UNAVAILABLE]
    assert snap.bki[0].report is None
    # остальное читается: недоступность одного источника не роняет другие
    assert snap.customer.is_customer


def test_unavailable_optional_sources_do_not_break_tax_data() -> None:
    world = pw.romashka_world()
    world.down.update({"tax:financials", "tax:blocks"})

    snap = snapshot_for(world, pw.ROMASHKA_INN, Product.WORKING_CAPITAL)

    assert snap.financials.meta.status == SourceStatus.UNAVAILABLE
    assert snap.financials.years == ()
    assert snap.tax.meta.status == SourceStatus.OK
    assert snap.tax.account_block_active is False


def test_missing_consent_marks_subject_as_not_requested() -> None:
    world = pw.romashka_world()
    records = records_of(world, pw.ROMASHKA_INN)
    card = records.get(facts.REGISTRY, pw.ROMASHKA_INN)
    assert card is not None
    subjects = facts.bki_subjects(pw.ROMASHKA_INN, card.data, None)

    data = facts.bki_subject_data(records, subjects, frozenset({pw.ROMASHKA_DIRECTOR}))

    assert [(b.role, b.meta.status) for b in data] == [
        (SubjectRole.COMPANY, SourceStatus.OK),
        (SubjectRole.DIRECTOR, SourceStatus.NOT_REQUESTED),
    ]
    assert data[1].report is None


def test_bki_match_not_found_is_not_found_without_report() -> None:
    world = pw.sokolova_world()
    world.bki[pw.SOKOLOVA_INN] = pw.report(pw.SOKOLOVA_INN, "PERSON", match="NOT_FOUND")

    snap = snapshot_for(world, pw.SOKOLOVA_INN)

    assert snap.bki[0].meta.status == SourceStatus.NOT_FOUND
    assert snap.bki[0].report is None


def test_our_loan_payment_comes_from_bureau_by_contract_uid() -> None:
    world = pw.sokolova_world()
    world.loans[pw.SOKOLOVA_INN] = {
        "loans": [
            {
                "loanId": "l1",
                "contractUid": "card-sok",
                "kind": "LOAN",
                "outstandingRub": 40_000,
                "status": "ACTIVE",
                "disbursedAt": "2026-01-10",
            },
            {
                "loanId": "l2",
                "contractUid": "closed-1",
                "kind": "LOAN",
                "outstandingRub": 0,
                "status": "CLOSED",
                "disbursedAt": "2024-01-10",
            },
        ]
    }

    snap = snapshot_for(world, pw.SOKOLOVA_INN)

    assert [
        (x.contract_uid, x.monthly_payment_rub, x.balance_rub) for x in snap.customer.our_loans
    ] == [("card-sok", 3_000, 40_000)]


def test_our_loan_without_bureau_record_uses_core_schedule() -> None:
    world = pw.sokolova_world()
    world.loans[pw.SOKOLOVA_INN] = {
        "loans": [
            {
                "loanId": "l1",
                "contractUid": "only-ours",
                "kind": "LOAN",
                "amountRub": 500_000,
                "outstandingRub": 500_000,
                "termMonths": 12,
                "ratePercent": 24.0,
                "status": "ACTIVE",
                "disbursedAt": "2026-10-20",
            }
        ]
    }

    snap = snapshot_for(world, pw.SOKOLOVA_INN)

    (loan,) = snap.customer.our_loans
    assert (
        loan.monthly_payment_rub == 47_280
    )  # аннуитет 500 000 ₽, 24%, 12 мес. (500000·0,02 / (1 − 1,02^−12) ≈ 47 279,8)


# ---------------------------------------------------------------- субъекты и заявка


def test_screening_subjects_dedupe_person_with_director_priority() -> None:
    card = pw.romashka_world().registry[pw.ROMASHKA_INN]
    subjects = facts.screening_subjects(pw.ROMASHKA_INN, map_company(card))

    assert [(s.role, s.inn) for s in subjects] == [
        (SubjectRole.COMPANY, pw.ROMASHKA_INN),
        (SubjectRole.DIRECTOR, pw.ROMASHKA_DIRECTOR),
    ]


def test_subjects_without_registry_card_fall_back_to_applicant_only() -> None:
    (ie,) = facts.screening_subjects(pw.SOKOLOVA_INN, None)
    (company,) = facts.screening_subjects(pw.ROMASHKA_INN, None)

    assert (ie.is_person, ie.compliance_role) == (True, "IE")
    assert (company.is_person, company.compliance_role) == (False, "COMPANY")


def test_bki_subjects_add_guarantor_after_director() -> None:
    card = map_company(pw.romashka_world().registry[pw.ROMASHKA_INN])

    subjects = facts.bki_subjects(pw.ROMASHKA_INN, card, "001310000999")

    assert [s.role for s in subjects] == [
        SubjectRole.COMPANY,
        SubjectRole.DIRECTOR,
        SubjectRole.GUARANTOR,
    ]


def test_split_person_name() -> None:
    assert facts.split_person_name("Морозов Олег Викторович") == ("Морозов", "Олег", "Викторович")
    assert facts.split_person_name("Иванов Иван") == ("Иванов", "Иван", None)
    assert facts.split_person_name(None) == (None, None, None)


def test_application_from_version_data() -> None:
    data = {
        "productCode": "INVESTMENT",
        "amountRub": 15_000_000,
        "termMonths": 60,
        "draft": {
            "collateral": {"description": "линия", "valueRub": 25_000_000},
            "guarantor": {"inn": "001310000999"},
            "declaredMonthlyRevenueRub": 700_000,
        },
    }

    app = facts.build_application(
        "A1",
        data,
        unsigned_consents=["на запрос в БКИ (поручитель)"],
        guarantor_consent_signed=True,
    )

    assert app.product == Product.INVESTMENT
    assert app.amount_rub == 15_000_000
    assert app.collateral is not None
    assert app.collateral.value_rub == 25_000_000
    assert app.guarantor is not None
    assert app.guarantor.consent_signed
    assert app.declared_monthly_revenue_rub == 700_000
    assert app.unsigned_consents == ("на запрос в БКИ (поручитель)",)
    assert facts.guarantor_inn(data) == "001310000999"


def test_missing_application_terms_are_listed() -> None:
    app = facts.build_application("A1", {"draft": {}})

    assert app.missing_fields == ("product_code", "amount_rub", "term_months")
