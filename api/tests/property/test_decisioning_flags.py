"""Property-тесты флагов (T-288, T-290, 70-02): INV-61 на настоящих флагах, нет ложных срабатываний.

Флаги ставят ручной разбор и ничего больше: не отказывают, не меняют расчёт, не прячут стоп-фактор.
Спокойный бизнес (оборот месяца в пределах ±5% от базы) не получает флагов антифрода и сверки.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.modules.decisioning import decide
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.flags import evaluate_flags
from app.modules.decisioning.reasons import CODE_KINDS
from app.modules.decisioning.types import (
    DecisionInput,
    FinancialsData,
    Outcome,
    Product,
    ReasonKind,
    TurnoverData,
    TurnoverMonth,
)
from tests.fixtures import core_personas as cp
from tests.strategies.decisioning import RequestParams, request_params

pytestmark = pytest.mark.property

D = Decimal
no_deadline = settings(deadline=None)


def flagged(inp: DecisionInput) -> DecisionInput:
    """Тот же вход, но ФНС отмечает массовый адрес: единственное отличие — флаг `MASS_REGISTRATION`."""
    return cp.with_snapshot(inp, tax=replace(inp.snapshot.tax, mass_address=True))


@no_deadline
@given(request_params())
def test_inv_61_a_real_flag_never_gives_auto_approval_or_a_counter_offer(
    params: RequestParams,
) -> None:
    result = decide(flagged(params.to_input()))
    assert result.outcome not in (Outcome.APPROVED, Outcome.COUNTER_OFFER)
    if result.outcome == Outcome.MANUAL_REVIEW:
        assert "MASS_REGISTRATION" in result.reason_codes
        assert result.recommendation is not None
    if result.outcome == Outcome.REJECTED:
        # отказ только по стоп-фактору, флаг сам не отказывает
        assert all(CODE_KINDS[code] == ReasonKind.STOP for code in result.reason_codes)


@no_deadline
@given(request_params())
@example(
    params=RequestParams(
        product=Product.EXPRESS,
        amount_rub=100_000,
        term_months=6,
        revenue_rub=300_000,
        pct=(70, 70, 70),
        age_months=0,
        tenure_months=0,
        history_months=0,
        closed_obligations=0,
        monthly_payments_rub=150_000,
        overdue_days=0,
        inquiries=0,
        rejected=0,
        restructurings=0,
        tax_debt_rub=0,
        collateral_rub=0,
        guarantor=False,
        with_financials=False,
    )
)
def test_a_flag_does_not_hide_a_stop_factor_or_missing_data(params: RequestParams) -> None:
    plain_input = params.to_input()
    plain, with_flag = decide(plain_input), decide(flagged(plain_input))
    has_stop = any(CODE_KINDS[code] == ReasonKind.STOP for code in plain.reason_codes)
    if has_stop or plain.outcome == Outcome.NEEDS_INFO:
        assert with_flag.outcome == plain.outcome
        assert with_flag.reason_codes == plain.reason_codes
    elif plain.outcome == Outcome.REJECTED:
        # 30-11: ручная причина (строка 4) выше RISK_TOO_HIGH/NO_OFFER_FOUND (строка 5).
        assert with_flag.outcome == Outcome.MANUAL_REVIEW
        assert with_flag.recommendation is not None
        assert with_flag.recommendation.outcome == Outcome.REJECTED


@no_deadline
@given(request_params())
def test_a_flag_changes_the_route_but_not_a_single_number(params: RequestParams) -> None:
    plain_input = params.to_input()
    assert decide(flagged(plain_input)).numbers == decide(plain_input).numbers


calm_pct = st.integers(95, 105)


@no_deadline
@given(request_params(), st.data())
def test_calm_turnover_gives_no_reconciliation_or_antifraud_flags(
    params: RequestParams, data: st.DataObject
) -> None:
    pct = tuple(data.draw(st.lists(calm_pct, min_size=len(params.pct), max_size=len(params.pct))))
    inp = replace(params, pct=pct).to_input()
    codes = {r.code for r in evaluate_flags(inp, compute_features(inp))}
    assert not codes & {"DATA_MISMATCH", "TURNOVER_ANOMALY"}


def _series(base: list[int], recent: int) -> DecisionInput:
    incoming = [*base, recent, recent, recent]
    months = tuple(
        TurnoverMonth(m, v, v * 85 // 100, 12)
        for m, v in zip(cp.month_starts(len(incoming)), incoming, strict=True)
    )
    inp = cp.t_base()
    return cp.with_snapshot(
        inp, turnover=TurnoverData(cp.ok("abs-turnover"), months), financials=FinancialsData()
    )


def _has_pump(inp: DecisionInput) -> bool:
    return any(
        r.code == "TURNOVER_ANOMALY" and r.params["rule"] == "PUMP"
        for r in evaluate_flags(inp, compute_features(inp))
    )


@no_deadline
@given(
    st.lists(st.integers(400, 600).map(lambda v: v * 10_000), min_size=9, max_size=21),
    st.integers(300, 2_000),
    st.integers(0, 1_500),
)
def test_pump_flag_is_monotone_in_the_recent_level(base: list[int], low: int, extra: int) -> None:
    """Если накачка видна на уровне последних трёх месяцев, то на более высоком уровне — тоже."""
    lower, higher = low * 10_000, (low + extra) * 10_000
    if _has_pump(_series(base, lower)):
        assert _has_pump(_series(base, higher))
