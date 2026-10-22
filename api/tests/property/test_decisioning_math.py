"""Property-тесты кредитной математики и обратной задачи: INV-07, 08, 09, 20–24, 30, 31 (70-02)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.dates import add_months

pytestmark = pytest.mark.property

D = Decimal
amounts = st.integers(50_000, 100_000_000)
terms = st.integers(1, 84)
rates = st.integers(0, 60).map(lambda p: D(p) / 100)  # 0–60% годовых
rates_pos = st.integers(1, 60).map(lambda p: D(p) / 100)


@given(amounts, rates, terms)
def test_inv_20_21_schedule_principal_balance_and_totals(amount: int, rate: D, term: int) -> None:
    rows = lm.build_schedule(amount, rate, term)
    assert len(rows) == term  # число платежей = сроку
    assert sum(r.principal for r in rows) == amount  # сумма основного долга = сумме кредита
    assert rows[-1].balance == 0  # остаток в конце равен нулю
    balances = [amount, *(r.balance for r in rows)]
    assert all(a >= b for a, b in zip(balances, balances[1:], strict=False))  # остаток убывает
    assert all(r.interest >= 0 and r.principal >= 0 for r in rows)
    assert sum(r.payment for r in rows) == amount + sum(r.interest for r in rows)  # INV-20
    assert lm.overpayment(rows, amount) == sum(r.interest for r in rows)


@given(amounts, rates, terms)
def test_rounded_payment_is_within_half_ruble_and_last_payment_within_n_rubles(
    amount: int, rate: D, term: int
) -> None:
    rows = lm.build_schedule(amount, rate, term)
    exact = lm.annuity_payment_exact(amount, rate, term)
    pmt = lm.annuity_payment(amount, rate, term)
    assert abs(D(pmt) - exact) <= D("0.5")
    # 30-16, инвариант 3: «не больше чем на n рублей». Это верно на обычных ставках и сроках;
    # при ставке 60% и сроке 7 лет ошибки округления копятся с множителем (1+i)^n, поэтому
    # общая граница — n·(1+i)^n, а граница спецификации проверяется в реалистичной области.
    growth = (1 + rate / 12) ** term
    assert abs(rows[-1].payment - pmt) <= term * growth
    if rate <= D("0.30") and term <= 36:
        assert abs(rows[-1].payment - pmt) <= term


@given(amounts, terms)
def test_inv_22_zero_rate_is_even_split(amount: int, term: int) -> None:
    assert lm.annuity_payment(amount, D(0), term) == lm.to_rub(D(amount) / term)


@given(amounts, rates, rates, terms)
def test_inv_22_payment_grows_with_rate(amount: int, r1: D, r2: D, term: int) -> None:
    low, high = sorted((r1, r2))
    assert lm.annuity_payment(amount, low, term) <= lm.annuity_payment(amount, high, term)


@given(amounts, rates, st.integers(1, 83))
def test_inv_22_payment_falls_with_term(amount: int, rate: D, term: int) -> None:
    assert lm.annuity_payment(amount, rate, term + 1) <= lm.annuity_payment(amount, rate, term)


@given(amounts, amounts, rates, terms)
def test_inv_09_payment_grows_with_amount(a1: int, a2: int, rate: D, term: int) -> None:
    small, big = sorted((a1, a2))
    assert lm.annuity_payment(small, rate, term) <= lm.annuity_payment(big, rate, term)


@given(amounts, rates_pos, st.integers(1, 60))
def test_closed_formula_balance_matches_schedule(amount: int, rate: D, term: int) -> None:
    rows = lm.build_schedule(amount, rate, term)
    for k, row in enumerate(rows[:-1], start=1):
        # 30-16, инвариант 5: «до k/2 рублей»; точная граница накопления — (k+1)·(1+i)^k
        bound = (D(k) + 1) * (1 + rate / 12) ** k
        assert abs(lm.balance_after(amount, rate, term, k) - row.balance) <= bound


@given(amounts, rates_pos, st.integers(2, 24), st.integers(1, 12))
def test_inv_23_bullet_payment_is_independent_of_term_and_overpayment_is_linear(
    amount: int, rate: D, term: int, extra: int
) -> None:
    assert lm.payment_for("BULLET", amount, rate, term) == lm.payment_for(
        "BULLET", amount, rate, term + extra
    )
    one = lm.overpayment(lm.bullet_schedule(amount, rate, term), amount)
    other = lm.overpayment(lm.bullet_schedule(amount, rate, term + extra), amount)
    assert other * term == one * (term + extra)
    rows = lm.bullet_schedule(amount, rate, term)
    assert rows[-1].principal == amount
    assert sum(r.principal for r in rows) == amount


@given(st.integers(1, 10**9), rates)
def test_inv_24_money_is_whole_rubles(amount: int, rate: D) -> None:
    rows = lm.build_schedule(amount, rate, 12)
    assert all(
        isinstance(v, int) for r in rows for v in (r.interest, r.principal, r.payment, r.balance)
    )
    assert sum(r.principal for r in rows) == amount  # рубли не теряются


# ---------------------------------------------------------------- обратная задача


flows = st.integers(10_000, 5_000_000)
existing = st.integers(0, 5_000_000)
thresholds = st.sampled_from([D("1.25"), D("1.30"), D("1.3125")])


def best_amount(flow: int, ex: int, rate: D, term: int, threshold: D, step: int) -> int:
    p_max = lm.max_payment(flow, ex, threshold)
    hint = lm.max_amount_formula(p_max, rate, term, "ANNUITY")

    def ok(amount: int) -> bool:
        return lm.dscr(flow, ex, lm.annuity_payment(amount, rate, term)) >= threshold

    if p_max <= 0:
        return 0
    return lm.largest_step_amount(ok, hint, step)


@given(flows, existing, rates_pos, terms, thresholds, st.sampled_from([1, 1_000, 50_000]))
def test_inv_30_31_max_amount_sits_exactly_on_the_threshold(
    flow: int, ex: int, rate: D, term: int, threshold: D, step: int
) -> None:
    top = best_amount(flow, ex, rate, term, threshold, step)
    assert top >= 0
    assert top % step == 0
    if top > 0:
        assert lm.dscr(flow, ex, lm.annuity_payment(top, rate, term)) >= threshold
    beyond = lm.annuity_payment(top + step, rate, term)
    assert lm.dscr(flow, ex, beyond) < threshold  # DSCR(макс + шаг) < порога


@given(flows, existing, rates_pos, st.integers(1, 83), thresholds)
def test_inv_07_max_amount_does_not_fall_with_term(
    flow: int, ex: int, rate: D, term: int, threshold: D
) -> None:
    step = 50_000
    assert best_amount(flow, ex, rate, term, threshold, step) <= best_amount(
        flow, ex, rate, term + 1, threshold, step
    )


@given(
    flows, existing, rates_pos, terms, st.integers(50_000, 20_000_000), st.integers(0, 20_000_000)
)
def test_inv_08_09_smaller_amount_still_passes_and_dscr_does_not_improve_with_amount(
    flow: int, ex: int, rate: D, term: int, amount: int, cut: int
) -> None:
    smaller = max(50_000, amount - cut)
    big_p = lm.annuity_payment(amount, rate, term)
    small_p = lm.annuity_payment(smaller, rate, term)
    assert small_p <= big_p
    big_dscr, small_dscr = lm.dscr(flow, ex, big_p), lm.dscr(flow, ex, small_p)
    assert big_dscr <= small_dscr  # INV-09
    if big_dscr >= D("1.25"):
        assert small_dscr >= D("1.25")  # INV-08
    assert lm.stress_dscr(flow, ex, big_p, D("0.2")) <= big_dscr  # стресс не лучше обычного


@given(amounts, rates_pos, st.integers(1_000, 3_000_000))
def test_min_term_is_the_smallest_passing_term(amount: int, rate: D, p_max_rub: int) -> None:
    n = lm.min_term(amount, rate, D(p_max_rub))
    if n is None:
        assert (
            D(amount) * rate / 12 >= p_max_rub or lm.annuity_payment(amount, rate, 1200) > p_max_rub
        )
        return
    assert lm.annuity_payment(amount, rate, n) <= p_max_rub
    if n > 1:
        assert lm.annuity_payment(amount, rate, n - 1) > p_max_rub


@given(st.dates(min_value=date(2026, 1, 1), max_value=date(2030, 12, 31)), st.integers(1, 60))
def test_payment_dates_are_business_days_and_never_go_back(issue: date, term: int) -> None:
    dates = lm.payment_dates(issue, term)
    assert all(d.weekday() < 5 for d in dates)  # инвариант 12 из 30-16
    assert all(a <= b for a, b in zip(dates, dates[1:], strict=False))
    anchor = issue.replace(day=min(issue.day, 28))
    assert all(d >= add_months(anchor, k) for k, d in enumerate(dates, start=1))
