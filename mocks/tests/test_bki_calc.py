"""T-113 (unit): расчёт значений БКИ при чтении — просрочка, корзины, сводка (раздел 6.4)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.roles.bki import calc
from app.roles.bki.calc import ApplicationFacts, InquiryFacts, ObligationFacts, Period

TODAY = date(2026, 10, 20)
ROMASHKA_PERIOD = [Period(date(2026, 7, 18))]


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (0, "OK"),
        (1, "D1_29"),
        (29, "D1_29"),
        (30, "D30_59"),
        (59, "D30_59"),
        (60, "D60_89"),
        (89, "D60_89"),
        (90, "D90_119"),
        (119, "D90_119"),
        (120, "D120_PLUS"),
        (900, "D120_PLUS"),
    ],
)
def test_bucket_boundaries(days: int, bucket: str) -> None:
    assert calc.bucket_for_days(days) == bucket


def test_spec_example_overdue_days_and_history() -> None:
    """Пример 6.1: кредит от 18.02.2024, неоплачено с 18.07.2026, на 20.10.2026."""
    assert calc.overdue_days_at(ROMASHKA_PERIOD, TODAY) == 94
    history = calc.payment_history(date(2024, 2, 18), None, ROMASHKA_PERIOD, TODAY)
    assert history[-7:] == [
        ("2026-04", "OK"),
        ("2026-05", "OK"),
        ("2026-06", "OK"),
        ("2026-07", "D1_29"),  # на 31.07 — 13 дней
        ("2026-08", "D30_59"),  # на 31.08 — 44
        ("2026-09", "D60_89"),  # на 30.09 — 74
        ("2026-10", "D90_119"),  # на 20.10 — 94
    ]
    assert len(history) == 24


def test_history_of_young_loan_starts_at_opening_month() -> None:
    history = calc.payment_history(date(2026, 9, 5), None, [], TODAY)
    assert history == [("2026-09", "OK"), ("2026-10", "OK")]


def test_history_stops_at_closing_month() -> None:
    history = calc.payment_history(date(2025, 11, 3), date(2026, 2, 3), [], TODAY)
    assert [m for m, _ in history] == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_closed_period_gives_past_buckets_and_no_current_overdue() -> None:
    periods = [Period(date(2026, 3, 10), date(2026, 5, 10))]
    history = dict(calc.payment_history(date(2025, 1, 1), None, periods, TODAY))
    assert history["2026-02"] == "OK"
    assert history["2026-03"] == "D1_29"  # на 31.03 — 21 день
    assert history["2026-04"] == "D30_59"  # на 30.04 — 51
    assert history["2026-05"] == "OK"  # 10.05 платёж внесён
    assert calc.overdue_days_at(periods, TODAY) == 0
    assert calc.max_overdue_days(periods, TODAY) == 61


def test_closed_period_older_than_24_months_is_ignored_in_max() -> None:
    assert calc.max_overdue_days([Period(date(2023, 1, 1), date(2023, 3, 1))], TODAY) == 0


def test_closed_obligation_does_not_accumulate_overdue() -> None:
    assert calc.overdue_days_at([Period(date(2026, 1, 1))], TODAY, closed_at=date(2026, 3, 1)) == 0


def test_period_in_the_future_has_no_days() -> None:
    assert calc.overdue_days_at([Period(date(2026, 11, 1))], TODAY) == 0


@given(
    since_ago=st.integers(min_value=0, max_value=1500),
    shift=st.integers(min_value=0, max_value=400),
    opened_ago=st.integers(min_value=1, max_value=2000),
)
def test_open_overdue_grows_monotonically_when_today_moves(
    since_ago: int, shift: int, opened_ago: int
) -> None:
    since = TODAY - timedelta(days=since_ago)
    periods = [Period(since)]
    later = TODAY + timedelta(days=shift)
    now_days = calc.overdue_days_at(periods, TODAY)
    assert calc.overdue_days_at(periods, later) == now_days + shift
    assert calc.max_overdue_days(periods, later) >= calc.max_overdue_days(periods, TODAY)
    assert calc.max_overdue_days(periods, TODAY) == now_days

    opened = min(since, TODAY - timedelta(days=opened_ago))
    history = calc.payment_history(opened, None, periods, later, months=10_000)
    statuses = [calc.bucket_for_days(0)] + [s for _, s in history]
    order = ["OK", "D1_29", "D30_59", "D60_89", "D90_119", "D120_PLUS"]
    ranks = [order.index(s) for s in statuses]
    assert ranks == sorted(ranks)  # открытая просрочка только ухудшает корзины
    assert history[-1][1] == calc.bucket_for_days(now_days + shift)


@given(days=st.integers(min_value=0, max_value=5000))
def test_bucket_is_monotone_in_days(days: int) -> None:
    order = ["OK", "D1_29", "D30_59", "D60_89", "D90_119", "D120_PLUS"]
    assert order.index(calc.bucket_for_days(days)) <= order.index(calc.bucket_for_days(days + 1))


def loan(**over: object) -> ObligationFacts:
    base: dict[str, object] = {
        "kind": "LOAN",
        "role": "BORROWER",
        "status": "ACTIVE",
        "opened_at": date(2024, 2, 18),
        "closed_at": None,
        "balance_rub": 837_000,
        "monthly_payment_rub": 113_000,
        "overdue_rub": 452_000,
        "periods": ROMASHKA_PERIOD,
    }
    base.update(over)
    return ObligationFacts(**base)  # type: ignore[arg-type]


def test_summary_sums_exclude_contingent_and_closed() -> None:
    obligations = [
        loan(),
        loan(balance_rub=976_000, monthly_payment_rub=205_500, overdue_rub=0, periods=[]),
        loan(kind="SURETY", role="GUARANTOR", balance_rub=500_000, monthly_payment_rub=None,
             overdue_rub=0, periods=[]),
        loan(status="CLOSED", closed_at=date(2023, 1, 1), balance_rub=0, periods=[],
             opened_at=date(2019, 10, 15), overdue_rub=0),
    ]  # fmt: skip
    summary = calc.summarize(obligations, [], [], TODAY, 5.0)
    assert summary.active_obligations == 3
    assert summary.closed_obligations == 1
    assert summary.total_debt_rub == 1_813_000
    assert summary.monthly_payments_rub == 318_500
    assert summary.contingent_liabilities_rub == 500_000
    assert summary.current_overdue_rub == 452_000
    assert summary.current_overdue_days == 94
    assert summary.history_length_months == 84


def test_limit_kinds_pay_five_percent_of_used_part() -> None:
    card = loan(kind="CREDIT_CARD", balance_rub=90_000, monthly_payment_rub=None, periods=[],
                overdue_rub=0)  # fmt: skip
    assert calc.effective_monthly_payment("CREDIT_CARD", None, 90_000, 5.0) == 4_500
    assert calc.effective_monthly_payment("CREDIT_LINE", None, 90_000, 10.0) == 9_000
    assert calc.effective_monthly_payment("OVERDRAFT", 7_000, 90_000, 5.0) == 7_000
    assert calc.effective_monthly_payment("GUARANTEE", 1, 90_000, 5.0) is None
    assert calc.summarize([card], [], [], TODAY, 5.0).monthly_payments_rub == 4_500


def test_inquiry_and_rejection_windows_and_own_flag() -> None:
    inquiries = [
        InquiryFacts(TODAY, True),
        InquiryFacts(TODAY - timedelta(days=30), False),  # граница включается
        InquiryFacts(TODAY - timedelta(days=31), False),
        InquiryFacts(TODAY - timedelta(days=5), False),
    ]
    applications = [
        ApplicationFacts(date(2026, 10, 14), date(2026, 10, 15), "REJECTED", False),
        ApplicationFacts(date(2026, 10, 1), date(2026, 10, 2), "REJECTED", True),
        ApplicationFacts(date(2026, 1, 1), date(2026, 1, 5), "REJECTED", False),
        ApplicationFacts(date(2026, 10, 1), None, "PENDING", True),
    ]
    summary = calc.summarize([], inquiries, applications, TODAY, 5.0)
    assert (summary.inquiries_30d, summary.inquiries_30d_excluding_own) == (3, 2)
    assert (
        summary.rejected_applications_90d,
        summary.rejected_applications_90d_excluding_own,
    ) == (2, 1)


def test_empty_summary_is_zero() -> None:
    assert calc.summarize([], [], [], TODAY, 5.0) == calc.ZERO_SUMMARY


def test_months_between() -> None:
    assert calc.months_between(date(2019, 10, 15), TODAY) == 84
    assert calc.months_between(date(2019, 10, 21), TODAY) == 83
    assert calc.months_between(TODAY, date(2020, 1, 1)) == 0


def test_bureau_score_stays_in_scale() -> None:
    worst = calc.summarize(
        [loan(periods=[Period(date(2020, 1, 1))])],
        [InquiryFacts(TODAY, False)] * 20,
        [ApplicationFacts(TODAY, TODAY, "REJECTED", False)] * 9,
        TODAY,
        5.0,
    )
    assert 300 <= calc.bureau_score(worst, True) <= 850
