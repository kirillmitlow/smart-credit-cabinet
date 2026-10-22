"""Property-тесты ядра на реалистичных входах: INV-01…04, 32, 33, 42, 50…53, 60…63 (70-02).

Порядок строгости исходов: `APPROVED < COUNTER_OFFER < MANUAL_REVIEW < REJECTED`;
`NEEDS_INFO` в сравнения не входит (проверки идут на полных данных).
Нарушение инварианта чинится правилами в `policy/`, а не подгонкой теста.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.modules.decisioning import decide, input_from_json, input_to_json
from app.modules.decisioning import features as ft
from app.modules.decisioning.dates import add_months
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.reasons import CODE_KINDS, make
from app.modules.decisioning.scoring import score
from app.modules.decisioning.types import (
    BankruptcyCase,
    BankruptcyCheck,
    DecisionInput,
    DecisionResult,
    Mode,
    Outcome,
    SubjectRole,
)
from tests.fixtures import core_personas as cp
from tests.strategies.decisioning import RequestParams, healthy_params, request_params

pytestmark = pytest.mark.property

D = Decimal
STRICTNESS = {
    Outcome.APPROVED: 0,
    Outcome.COUNTER_OFFER: 1,
    Outcome.MANUAL_REVIEW: 2,
    Outcome.REJECTED: 3,
}
GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
POLICY = cp.load_policy()
no_deadline = settings(deadline=None)


def strictness(result: DecisionResult) -> int:
    """Строгость исхода. Ручной разбор строже того, что рекомендует ядро: у `MANUAL_REVIEW`
    с рекомендацией «отказать» (грейд C/D всегда идёт человеку, строка 4 таблицы 30-11) берём
    рекомендацию, иначе плохой клиент «смягчался» бы переходом из авто-отказа в ручной."""
    base = STRICTNESS[result.outcome]
    if result.recommendation is not None:
        return max(base, STRICTNESS[result.recommendation.outcome])
    return base


def run(params: RequestParams) -> int:
    return strictness(decide(params.to_input()))


def points(params: RequestParams) -> int:
    return score(compute_features(params.to_input()), POLICY, Mode.DECISION).points


# ---------------------------------------------------------------- INV-50, 51, 52, 53


@no_deadline
@given(request_params())
def test_inv_50_decide_twice_gives_the_same_result_including_reason_order(
    params: RequestParams,
) -> None:
    inp = params.to_input()
    first, second = decide(inp), decide(inp)
    assert first == second
    assert repr(first) == repr(second)
    assert first.reason_codes == second.reason_codes


@no_deadline
@given(request_params())
def test_inv_52_decision_is_reproducible_from_saved_inputs(params: RequestParams) -> None:
    inp = params.to_input()
    assert decide(input_from_json(input_to_json(inp))) == decide(inp)


@pytest.mark.usefixtures("no_network")
@no_deadline
@given(request_params())
def test_inv_51_decide_needs_neither_network_nor_clock(params: RequestParams) -> None:
    result = decide(params.to_input())  # сокеты закрыты; `datetime.now` в ядре запрещён линтером
    assert result.outcome in Outcome


@no_deadline
@given(request_params())
def test_inv_53_codes_come_from_catalog_and_rejection_always_has_a_reason(
    params: RequestParams,
) -> None:
    result = decide(params.to_input())
    assert all(r.code in CODE_KINDS for r in result.reasons)
    assert len({(r.code, repr(r.params)) for r in result.reasons}) == len(result.reasons)
    if result.outcome == Outcome.REJECTED:
        assert result.reasons
    assert len(result.explanations) == len(result.reasons)


# ---------------------------------------------------------------- INV-32: автоодобрение проходит все пределы


@no_deadline
@given(healthy_params())
def test_inv_32_any_auto_approval_satisfies_every_limit(params: RequestParams) -> None:
    result = decide(params.to_input())
    assume(result.outcome == Outcome.APPROVED)
    n, f = result.numbers, result.features
    assert f is not None
    assert n.dscr is not None
    assert n.stress_dscr is not None
    assert n.dscr >= D("1.25")
    assert n.stress_dscr >= D("1.0")
    assert n.debt_to_revenue_with_new is not None
    assert n.debt_to_revenue_with_new <= 1
    assert result.reasons == ()
    assert result.route.value == "AUTO"
    assert not f.account_block_active
    assert n.grade is not None
    assert n.grade.value in ("A", "B")
    assert result.variants == ()  # INV-42: запрос проходит → встречных нет
    limit = n.auto_limit_rub
    assert limit is None or params.amount_rub <= limit
    if params.product.value == "CREDIT_LINE":
        assert f.revenue_cautious_rub is not None
        assert params.amount_rub <= f.revenue_cautious_rub // 2 + 1
    # серые зоны автомат не отдаёт
    assert n.dscr >= D("1.30")
    assert n.stress_dscr >= D("1.05")


# ---------------------------------------------------------------- INV-33


@given(request_params())
def test_inv_33_cautious_revenue_not_above_averages_and_vat_does_not_change_net(
    params: RequestParams,
) -> None:
    inp = params.to_input()
    f = compute_features(inp)
    months = inp.snapshot.turnover.months
    series = ft.net_series(months, osno=False, policy=POLICY)
    assert f.revenue_cautious_rub is not None
    if len(series) >= 6 and f.revenue_source == "OWN_BANK" and not f.is_seasonal:
        assert f.revenue_cautious_rub <= round(ft.mean(series[-12:])) + 1
        assert f.revenue_cautious_rub <= round(ft.mean(series[-6:])) + 1
    # Добавили НДС к поступлениям и включили ОСНО: чистая выручка не изменилась (±1–2 ₽ на округлении)
    grossed = tuple(
        replace(m, incoming_net_rub=round(m.incoming_net_rub * (1 + ft.vat_rate(POLICY, m.month))))
        for m in months
    )
    osno_tax = replace(inp.snapshot.tax, regimes=("OSNO",))
    osno = replace(
        inp,
        snapshot=replace(
            inp.snapshot, tax=osno_tax, turnover=replace(inp.snapshot.turnover, months=grossed)
        ),
    )
    assert compute_features(osno).revenue_cautious_rub is not None
    assert abs((compute_features(osno).revenue_cautious_rub or 0) - f.revenue_cautious_rub) <= 2


# ---------------------------------------------------------------- INV-01…04: монотонность


@no_deadline
@given(request_params(), st.sampled_from([0, 15, 45, 75, 95]), st.sampled_from([0, 15, 45, 75, 95]))
def test_inv_01_more_overdue_days_never_soften_the_outcome(
    params: RequestParams, a: int, b: int
) -> None:
    low, high = sorted((a, b))
    softer = run(replace(params, overdue_days=low))
    harder = run(replace(params, overdue_days=high))
    assert softer <= harder


@no_deadline
@given(
    request_params(),
    st.sampled_from([0, 20_000, 150_000, 600_000]),
    st.sampled_from([0, 20_000, 150_000, 600_000]),
)
def test_inv_02_more_existing_payments_never_soften_outcome_or_improve_grade(
    params: RequestParams, a: int, b: int
) -> None:
    low, high = sorted((a, b))
    first = decide(replace(params, monthly_payments_rub=low).to_input())
    second = decide(replace(params, monthly_payments_rub=high).to_input())
    assert strictness(first) <= strictness(second)
    if first.numbers.grade is not None and second.numbers.grade is not None:
        assert GRADE_RANK[first.numbers.grade.value] <= GRADE_RANK[second.numbers.grade.value]


@given(request_params(), st.integers(0, 9), st.integers(0, 9), st.integers(0, 4), st.integers(0, 4))
def test_inv_03_more_inquiries_and_rejections_never_raise_points(
    params: RequestParams, i1: int, i2: int, r1: int, r2: int
) -> None:
    lo_i, hi_i = sorted((i1, i2))
    lo_r, hi_r = sorted((r1, r2))
    assert points(replace(params, inquiries=hi_i, rejected=hi_r)) <= points(
        replace(params, inquiries=lo_i, rejected=lo_r)
    )


@given(
    request_params(),
    st.sampled_from([0, 10_000, 200_000, 3_000_000]),
    st.sampled_from([0, 10_000, 200_000, 3_000_000]),
)
def test_inv_03_more_tax_debt_never_raises_points(params: RequestParams, a: int, b: int) -> None:
    low, high = sorted((a, b))
    assert points(replace(params, tax_debt_rub=high)) <= points(replace(params, tax_debt_rub=low))


@given(request_params(), st.sampled_from([0, 15, 45, 75, 95]), st.sampled_from([0, 15, 45, 75, 95]))
def test_inv_03_more_overdue_never_raises_points(params: RequestParams, a: int, b: int) -> None:
    low, high = sorted((a, b))
    assert points(replace(params, overdue_days=high)) <= points(replace(params, overdue_days=low))


@no_deadline
@given(request_params(), st.integers(11, 30), st.integers(0, 120))
def test_inv_04_more_revenue_and_older_business_never_hurt(
    params: RequestParams, scale: int, years: int
) -> None:
    richer = replace(
        params, revenue_rub=params.revenue_rub * scale // 10, age_months=params.age_months + years
    )
    assert points(richer) >= points(params)
    before, after = decide(params.to_input()), decide(richer.to_input())
    if before.numbers.max_amount_rub is not None and after.numbers.max_amount_rub is not None:
        assert after.numbers.max_amount_rub >= before.numbers.max_amount_rub


# ---------------------------------------------------------------- INV-60, 61, 62, 63


def _with_stop(inp: DecisionInput, kind: str) -> tuple[DecisionInput, str]:
    snap = inp.snapshot
    if kind == "COMPANY_NOT_ACTIVE":
        return replace(
            inp, snapshot=replace(snap, registry=replace(snap.registry, status_code="LIQUIDATED"))
        ), kind
    if kind == "AML_LIST":
        results = tuple(replace(r, aml_listed=True) for r in snap.compliance.results)
        return replace(
            inp, snapshot=replace(snap, compliance=replace(snap.compliance, results=results))
        ), kind
    if kind == "BANKRUPTCY":
        case = BankruptcyCase("А00-1/2025", "OBSERVATION", add_months(cp.TODAY, -3))
        checks = (
            BankruptcyCheck(snap.registry.inn, SubjectRole.COMPANY, None, cp.ok("efrsb"), (case,)),
        )
        return replace(inp, snapshot=replace(snap, bankruptcies=checks)), kind
    if kind == "FORBIDDEN_INDUSTRY":
        return replace(
            inp, snapshot=replace(snap, registry=replace(snap.registry, okved_main="92.00"))
        ), kind
    if kind == "DUPLICATE_APPLICATION":
        return replace(
            inp, context=replace(inp.context, other_active_applications=("APP-OTHER",))
        ), kind
    if kind == "TAX_ARREARS_HIGH":
        return replace(
            inp, snapshot=replace(snap, tax=replace(snap.tax, tax_debt_rub=10**10))
        ), kind
    subjects = tuple(
        replace(s, report=replace(s.report, current_overdue_days=120, current_overdue_rub=500_000))
        if s.role == SubjectRole.COMPANY and s.report is not None
        else s
        for s in snap.bki
    )
    return replace(inp, snapshot=replace(snap, bki=subjects)), "CURRENT_OVERDUE_90"


@no_deadline
@given(
    request_params(),
    st.sampled_from(
        [
            "COMPANY_NOT_ACTIVE",
            "AML_LIST",
            "BANKRUPTCY",
            "FORBIDDEN_INDUSTRY",
            "DUPLICATE_APPLICATION",
            "TAX_ARREARS_HIGH",
            "CURRENT_OVERDUE_90",
        ]
    ),
)
def test_inv_60_any_stop_factor_gives_rejection_whatever_the_rest(
    params: RequestParams, kind: str
) -> None:
    inp, code = _with_stop(params.to_input(), kind)
    result = decide(inp)
    assert result.outcome == Outcome.REJECTED
    assert code in result.reason_codes
    assert all(CODE_KINDS[c].value == "STOP" for c in result.reason_codes)


@no_deadline
@given(request_params())
def test_inv_61_a_flag_without_stop_is_never_auto_approval(params: RequestParams) -> None:
    decide_module = sys.modules["app.modules.decisioning.decide"]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            decide_module,
            "evaluate_flags",
            lambda _i, _f: (make("MASS_REGISTRATION", which="адрес"),),
        )
        result = decide(params.to_input())
    assert result.outcome != Outcome.APPROVED
    if result.outcome == Outcome.MANUAL_REVIEW:
        assert "MASS_REGISTRATION" in result.reason_codes


@no_deadline
@given(request_params())
def test_inv_62_young_business_without_security_is_never_approved(params: RequestParams) -> None:
    young = replace(params, age_months=params.age_months % 6, collateral_rub=0, guarantor=False)
    result = decide(young.to_input())
    assert result.outcome != Outcome.APPROVED
    assert not (result.numbers.grade is not None and result.outcome == Outcome.APPROVED)


@given(request_params())
def test_inv_63_points_within_scale_and_grade_follows_points(params: RequestParams) -> None:
    result = score(compute_features(params.to_input()), POLICY, Mode.DECISION)
    assert 0 <= result.points <= 100
    assert all(0 <= f.points <= f.max_points for f in result.factors)
    row = POLICY.grade_of(result.points)
    capped = result.capped is not None
    assert (result.grade.value == row.grade) or capped
    if capped:
        assert GRADE_RANK[result.grade.value] >= GRADE_RANK[row.grade]


def test_inv_63_grade_is_monotone_over_all_points_and_scale_has_no_holes() -> None:
    ranks = [GRADE_RANK[POLICY.grade_of(p).grade] for p in range(100, -1, -1)]
    assert ranks == sorted(ranks)  # баллы падают → грейд не лучше
    covered = [p for p in range(101) if POLICY.grade_of(p)]
    assert len(covered) == 101


@no_deadline
@given(request_params())
def test_worsening_every_factor_at_once_does_not_raise_points_inv_63(params: RequestParams) -> None:
    worse = replace(
        params,
        inquiries=min(params.inquiries + 3, 9),
        rejected=min(params.rejected + 1, 4),
        tax_debt_rub=params.tax_debt_rub + 100_000,
        monthly_payments_rub=params.monthly_payments_rub + 20_000,
        age_months=max(params.age_months - 12, 0),
    )
    assert points(worse) <= points(params)
