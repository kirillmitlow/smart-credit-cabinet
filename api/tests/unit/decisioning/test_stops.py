"""Семь стоп-факторов (T-289, 30-04): границы «чуть ниже / ровно / чуть выше», приоритет кодов."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.modules.decisioning import decide
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.stops import evaluate_stop_factors, okved_matches
from app.modules.decisioning.types import (
    ApplicantKind,
    BankruptcyCase,
    BkiReport,
    DecisionInput,
    Outcome,
    SourceMeta,
    SourceStatus,
    SubjectRole,
    TaxData,
)
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal


def stops(inp: DecisionInput) -> list[str]:
    return [r.code for r in evaluate_stop_factors(inp, compute_features(inp))]


def with_tax_debt(debt: int) -> DecisionInput:
    inp = cp.t_base()  # выручка 5 000 000 в месяц
    return cp.with_snapshot(inp, tax=replace(inp.snapshot.tax, tax_debt_rub=debt))


# ---------------------------------------------------------------- налоговый долг 10%


@pytest.mark.parametrize(
    ("debt", "triggered"),
    [
        (495_000, False),  # 9,9%
        (500_000, False),  # ровно 10% — не больше порога
        (500_001, True),  # чуть выше
        (505_000, True),  # 10,1%
        (0, False),
    ],
)
def test_tax_arrears_boundary(debt: int, triggered: bool) -> None:
    assert (stops(with_tax_debt(debt)) == ["TAX_ARREARS_HIGH"]) is triggered


def test_penalties_and_fines_do_not_count() -> None:
    inp = cp.t_base()
    tax = replace(inp.snapshot.tax, tax_debt_rub=0, penalties_rub=5_000_000, fines_rub=1_000_000)
    assert stops(cp.with_snapshot(inp, tax=tax)) == []


def test_tax_check_waits_for_revenue() -> None:
    """Выручка неизвестна → проверка откладывается (а решение уйдёт в NEEDS_INFO)."""
    inp = cp.garipov(second_pass=False)
    tax = replace(inp.snapshot.tax, tax_debt_rub=9_999_999)
    assert stops(cp.with_snapshot(inp, tax=tax)) == []


def test_tax_arrears_params_for_client_text() -> None:
    inp = cp.romashka()
    reason = evaluate_stop_factors(inp, compute_features(inp))[0]
    assert reason.params["debt_rub"] == 1_150_000
    assert reason.params["repay_min_rub"] == 358_334  # 1 150 000 − 791 666


# ---------------------------------------------------------------- просрочка 90 дней


@pytest.mark.parametrize(
    ("days", "rub", "triggered"),
    [
        (89, 154_200, False),
        (90, 154_200, True),
        (95, 154_200, True),
        (95, 9_999, False),  # ниже порога существенности 10 000 ₽
        (95, 10_000, True),
    ],
)
def test_current_overdue_boundary(days: int, rub: int, triggered: bool) -> None:
    inp = cp.with_company_report(
        cp.t_base(),
        replace(
            cp.t_overdue_95().snapshot.bki[0].report,
            current_overdue_days=days,
            current_overdue_rub=rub,
        ),
    )  # type: ignore[type-var]
    assert ("CURRENT_OVERDUE_90" in stops(inp)) is triggered


def test_overdue_of_director_and_guarantor_counts_too() -> None:
    inp = cp.quick_start(with_guarantor=True)
    bad = replace(cp.clean_person(), current_overdue_days=100, current_overdue_rub=50_000)
    for role in (SubjectRole.DIRECTOR, SubjectRole.GUARANTOR):
        subjects = tuple(replace(s, report=bad) if s.role == role else s for s in inp.snapshot.bki)
        found = evaluate_stop_factors(
            replace(inp, snapshot=replace(inp.snapshot, bki=subjects)),
            compute_features(inp),
        )
        assert [r.code for r in found] == ["CURRENT_OVERDUE_90"]
        assert found[0].params["subject"] == role.value


# ---------------------------------------------------------------- банкротство 60 мес., доля 25%


def bankrupt_input(
    completed: date | None, stage: str = "COMPLETED", share: str = "40"
) -> DecisionInput:
    inp = cp.t_bankrupt()
    case = BankruptcyCase("А00-1/2022", stage, date(2022, 3, 10), completed)
    checks = tuple(
        replace(c, cases=(case,), share_percent=D(share)) if c.role == SubjectRole.FOUNDER else c
        for c in inp.snapshot.bankruptcies
    )
    no_bki_cases = tuple(
        replace(s, report=replace(s.report, bankruptcies=()))
        if s.role == SubjectRole.FOUNDER
        else s
        for s in inp.snapshot.bki
    )  # type: ignore[type-var]
    return cp.with_snapshot(inp, bankruptcies=checks, bki=no_bki_cases)


@pytest.mark.parametrize(
    ("completed", "triggered"),
    [
        (date(2021, 10, 22), True),  # завершено 59 мес. 30 дн. назад
        (date(2021, 10, 21), False),  # ровно 60 мес. назад
        (date(2021, 10, 20), False),
        (date(2026, 9, 1), True),
    ],
)
def test_bankruptcy_sixty_month_window(completed: date, triggered: bool) -> None:
    assert ("BANKRUPTCY" in stops(bankrupt_input(completed))) is triggered


def test_unfinished_bankruptcy_always_blocks() -> None:
    assert "BANKRUPTCY" in stops(bankrupt_input(None, stage="PROPERTY_REALIZATION"))


@pytest.mark.parametrize(
    ("share", "triggered"), [("24", False), ("24.99", False), ("25", True), ("40", True)]
)
def test_founder_share_threshold(share: str, triggered: bool) -> None:
    assert ("BANKRUPTCY" in stops(bankrupt_input(date(2024, 10, 21), share=share))) is triggered


def test_bankruptcy_params_tell_when_to_come_back() -> None:
    inp = cp.t_bankrupt()
    reason = evaluate_stop_factors(inp, compute_features(inp))[0]
    assert reason.params["apply_after"] == "2029-10-21"  # завершение + 60 мес. (30-17)
    assert reason.params["case_number"] == "А00-45012/2022"


def test_bankruptcy_found_only_in_bki_is_enough() -> None:
    inp = cp.t_base()
    case = BankruptcyCase("А00-9/2023", "OBSERVATION", date(2026, 1, 1))
    director = next(s for s in inp.snapshot.bki if s.role == SubjectRole.DIRECTOR)
    rep = replace(director.report, bankruptcies=(case,))  # type: ignore[type-var]
    subjects = tuple(replace(s, report=rep) if s is director else s for s in inp.snapshot.bki)
    assert stops(cp.with_snapshot(inp, bki=subjects)) == ["BANKRUPTCY"]


def test_unavailable_efrsb_does_not_trigger_anything() -> None:
    inp = cp.t_base()
    checks = tuple(
        replace(c, meta=SourceMeta(SourceStatus.UNAVAILABLE)) for c in inp.snapshot.bankruptcies
    )
    assert stops(cp.with_snapshot(inp, bankruptcies=checks)) == []


# ---------------------------------------------------------------- реестр, ПОД/ФТ, отрасль, дубль


@pytest.mark.parametrize(
    ("kind", "status", "triggered"),
    [
        (ApplicantKind.LEGAL_ENTITY, "LIQUIDATING", True),
        (ApplicantKind.LEGAL_ENTITY, "LIQUIDATED", True),
        (ApplicantKind.LEGAL_ENTITY, "BANKRUPT", True),
        (ApplicantKind.LEGAL_ENTITY, "REORGANIZING", False),  # автомат не уверен
        (ApplicantKind.LEGAL_ENTITY, "ACTIVE", False),
        (ApplicantKind.LEGAL_ENTITY, "CEASED", False),  # статус ИП у ЮЛ не стоп
        (ApplicantKind.INDIVIDUAL_ENTREPRENEUR, "CEASED", True),
        (ApplicantKind.INDIVIDUAL_ENTREPRENEUR, "BANKRUPT", True),
        (ApplicantKind.INDIVIDUAL_ENTREPRENEUR, "LIQUIDATING", False),
    ],
)
def test_company_not_active(kind: ApplicantKind, status: str, triggered: bool) -> None:
    inp = cp.t_base()
    reg = replace(inp.snapshot.registry, kind=kind, status_code=status)
    assert ("COMPANY_NOT_ACTIVE" in stops(cp.with_snapshot(inp, registry=reg))) is triggered


@pytest.mark.parametrize("role", [SubjectRole.COMPANY, SubjectRole.DIRECTOR, SubjectRole.FOUNDER])
def test_aml_list_for_company_director_or_founder(role: SubjectRole) -> None:
    inp = cp.t_base()
    results = tuple(
        replace(r, aml_listed=(r.role == role)) for r in inp.snapshot.compliance.results
    )
    results = (
        *results,
        replace(results[0], role=SubjectRole.FOUNDER, aml_listed=(role == SubjectRole.FOUNDER)),
    )
    data = replace(inp.snapshot.compliance, results=results)
    assert stops(cp.with_snapshot(inp, compliance=data)) == ["AML_LIST"]


@pytest.mark.parametrize(
    ("code", "triggered"),
    [
        ("92", True),
        ("92.00", True),
        ("92.11", True),
        ("25.40", True),
        ("25.4", True),
        ("25.62", False),  # «25.4» не ловит «25.62» (30-04)
        ("25.41", True),
        ("64.92", True),
        ("64.92.1", True),
        ("64.91", False),
        ("64.9", False),
        ("62.01", False),
        ("9", False),
        ("", False),
    ],
)
def test_forbidden_industry_matches_whole_segments(code: str, triggered: bool) -> None:
    inp = cp.t_base()
    reg = replace(inp.snapshot.registry, okved_main=code)
    assert ("FORBIDDEN_INDUSTRY" in stops(cp.with_snapshot(inp, registry=reg))) is triggered


def test_okved_matches_helper() -> None:
    assert okved_matches("92.00", "92")
    assert not okved_matches("93.00", "92")
    assert not okved_matches("25", "25.4")
    assert okved_matches("25.40", "25.4")


def test_duplicate_application_protects_from_the_race_of_two_submits() -> None:
    inp = cp.t_base()
    dup = replace(inp, context=replace(inp.context, other_active_applications=("APP-2026-000042",)))
    assert stops(dup) == ["DUPLICATE_APPLICATION"]
    result = decide(dup)
    assert result.outcome == Outcome.REJECTED
    assert result.reasons[0].params["application"] == "APP-2026-000042"
    assert "APP-2026-000042" in result.explanations[0].client


# ---------------------------------------------------------------- порядок, приоритет, выключенные правила


def test_all_triggered_stops_are_recorded_in_catalog_order() -> None:
    inp = cp.romashka()
    # добавим ещё и запрещённую отрасль, и список ПОД/ФТ: порядок — как в 30-04
    reg = replace(inp.snapshot.registry, okved_main="92.00", status_code="LIQUIDATING")
    results = tuple(replace(r, aml_listed=True) for r in inp.snapshot.compliance.results)
    snap = replace(
        inp.snapshot, registry=reg, compliance=replace(inp.snapshot.compliance, results=results)
    )
    found = stops(replace(inp, snapshot=snap))
    assert found == [
        "COMPANY_NOT_ACTIVE",
        "AML_LIST",
        "FORBIDDEN_INDUSTRY",
        "TAX_ARREARS_HIGH",
        "CURRENT_OVERDUE_90",
    ]
    assert decide(replace(inp, snapshot=snap)).reason_codes == tuple(found)


def test_disabled_rule_is_present_in_config_but_silent() -> None:
    inp = cp.t_gambling()
    rule = inp.policy.stop_factors.forbidden_industry.model_copy(update={"enabled": False})
    policy = inp.policy.model_copy(
        update={
            "stop_factors": inp.policy.stop_factors.model_copy(update={"forbidden_industry": rule})
        }
    )
    assert stops(replace(inp, policy=policy)) == []


def test_stop_factor_overrides_everything_else_inv_60() -> None:
    """Стоп сильнее NEEDS_INFO, залога, хороших цифр и недоступных источников."""
    inp = cp.garipov(second_pass=False)  # выручки нет → NEEDS_INFO
    reg = replace(inp.snapshot.registry, status_code="CEASED")  # у ИП это стоп
    broken_tax = TaxData(SourceMeta(SourceStatus.UNAVAILABLE))
    result = decide(replace(inp, snapshot=replace(inp.snapshot, registry=reg, tax=broken_tax)))
    assert result.outcome == Outcome.REJECTED
    assert result.reason_codes == ("COMPANY_NOT_ACTIVE",)
    assert result.numbers.score_points is None  # скоринг не считается


def test_bki_report_with_all_clear_triggers_nothing() -> None:
    inp = cp.sokolova()
    assert stops(inp) == []
    assert isinstance(cp.company_subject(inp).report, BkiReport)
