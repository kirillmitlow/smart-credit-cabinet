"""Признаки (T-285, T-286, T-287): выручка, поток, БКИ, налоги, тренд, шок."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.modules.decisioning import features as ft
from app.modules.decisioning.types import (
    BkiObligation,
    BkiReport,
    BkiSubject,
    CustomerData,
    DecisionInput,
    FinancialsData,
    FinancialYear,
    Mode,
    OurLoan,
    Quality,
    SourceMeta,
    SourceStatus,
    StatementData,
    SubjectRole,
    TaxData,
    TurnoverData,
    TurnoverMonth,
)
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal
POLICY = cp.load_policy()


def feats(inp: DecisionInput):  # type: ignore[no-untyped-def]
    return ft.compute_features(inp)


def months(values: list[int], last: date = date(2026, 9, 1)) -> tuple[TurnoverMonth, ...]:
    starts = cp.month_starts(len(values), last)
    return tuple(TurnoverMonth(m, v, 0, 5) for m, v in zip(starts, values, strict=True))


def base_with_turnover(values: list[int], **snapshot: object) -> DecisionInput:
    inp = cp.t_base()
    snap = replace(
        inp.snapshot,
        financials=FinancialsData(),
        turnover=TurnoverData(cp.ok("abs"), months(values)),
        **snapshot,  # type: ignore[arg-type]
    )
    return replace(inp, snapshot=snap)


# ---------------------------------------------------------------- НДС по дате месяца


def test_vat_rate_follows_the_month_not_the_application_date() -> None:
    assert ft.vat_rate(POLICY, date(2025, 12, 1)) == D("0.20")
    assert ft.vat_rate(POLICY, date(2026, 1, 1)) == D("0.22")
    assert ft.vat_rate(POLICY, date(1999, 1, 1)) == D(0)


def test_net_series_across_2025_2026_divides_by_each_months_rate() -> None:
    series = ft.net_series(
        [
            TurnoverMonth(date(2025, 12, 1), 18_000_000, 0),
            TurnoverMonth(date(2026, 1, 1), 18_300_000, 0),
        ],
        osno=True,
        policy=POLICY,
    )
    assert series == (D(15_000_000), D(15_000_000))
    flat = ft.net_series([TurnoverMonth(date(2026, 1, 1), 1_000, 0)], osno=False, policy=POLICY)
    assert flat == (D(1_000),)  # без ОСНО НДС не делим


# ---------------------------------------------------------------- выручка и поток


def test_cautious_revenue_is_min_of_12_and_6_month_averages() -> None:
    values = [100] * 6 + [200] * 6  # среднее за 12 — 150, за последние 6 — 200
    f = feats(base_with_turnover([v * 1_000 for v in values]))
    assert f.revenue_cautious_rub == 150_000
    falling = [200] * 6 + [100] * 6  # среднее за 12 — 150, за последние 6 — 100
    assert feats(base_with_turnover([v * 1_000 for v in falling])).revenue_cautious_rub == 100_000


def test_revenue_never_exceeds_either_average_inv_33() -> None:
    values = [3, 9, 4, 8, 5, 7, 6, 10, 2, 12, 11, 1]
    f = feats(base_with_turnover([v * 100_000 for v in values]))
    long_avg = sum(values) * 100_000 / 12
    short_avg = sum(values[-6:]) * 100_000 / 6
    assert f.revenue_cautious_rub is not None
    assert f.revenue_cautious_rub <= min(long_avg, short_avg) + 1


def test_short_history_uses_factor_07() -> None:
    f = feats(base_with_turnover([1_000_000] * 3))
    assert f.revenue_cautious_rub == 700_000
    assert f.revenue_source == "OWN_BANK"
    assert f.revenue_months == 3


def test_no_data_is_not_zero() -> None:
    inp = base_with_turnover([])
    inp = replace(inp, snapshot=replace(inp.snapshot, turnover=TurnoverData(cp.not_found("abs"))))
    f = feats(inp)
    assert f.revenue_cautious_rub is None
    assert f.flow_model_rub is None
    assert f.revenue_source is None
    assert f.revenue_quality is None


def test_source_priority_bank_then_financials_then_statement() -> None:
    inp = cp.t_base()
    f = feats(inp)
    assert (f.revenue_source, f.revenue_quality) == ("OWN_BANK", Quality.OWN_BANK)
    # меньше 6 месяцев оборотов и свежая отчётность → отчётность
    short = replace(
        inp,
        snapshot=replace(
            inp.snapshot, turnover=TurnoverData(cp.ok("abs"), months([1_000_000] * 3))
        ),
    )
    f = feats(short)
    assert (f.revenue_source, f.revenue_quality) == ("OFFICIAL", Quality.OFFICIAL)
    assert f.revenue_cautious_rub == 5_000_000  # 2110 / 12
    # ни отчётности, ни банка → выписка клиента
    stmt = StatementData(cp.ok("stmt"), cp.flat_turnover(12, 400_000, 300_000))
    only_statement = replace(
        inp,
        snapshot=replace(
            inp.snapshot,
            turnover=TurnoverData(cp.not_found("abs")),
            financials=FinancialsData(),
            statement=stmt,
        ),
    )
    f = feats(only_statement)
    assert (f.revenue_source, f.revenue_quality) == ("CLIENT_UPLOAD", Quality.CLIENT_UPLOAD)
    assert f.flow_quality == Quality.ESTIMATE
    # короткий ряд банка — «нет лучшего», берём его с коэффициентом 0,7
    only_short = replace(
        inp,
        snapshot=replace(
            inp.snapshot,
            turnover=TurnoverData(cp.ok("abs"), months([1_000_000] * 3)),
            financials=FinancialsData(),
        ),
    )
    assert feats(only_short).revenue_cautious_rub == 700_000


def test_statement_of_another_owner_is_ignored() -> None:
    inp = cp.garipov(second_pass=True)
    foreign = replace(inp.snapshot.statement, owner_inn_matches=False)
    f = feats(replace(inp, snapshot=replace(inp.snapshot, statement=foreign)))
    assert f.revenue_cautious_rub is None


def test_stale_financials_are_not_a_revenue_source() -> None:
    inp = cp.stankoprom()
    fresh = feats(inp)
    assert fresh.revenue_source == "OFFICIAL"
    # отчёт 2025 года свеж 18 мес. от 31.12.2025, то есть по 30.06.2027
    on_edge = replace(inp, context=replace(inp.context, app_today=date(2027, 6, 30)))
    assert feats(on_edge).revenue_source == "OFFICIAL"
    stale = replace(inp, context=replace(inp.context, app_today=date(2027, 7, 1)))
    assert feats(stale).revenue_source is None


def test_flow_from_financials_is_scaled_down_when_revenue_fell() -> None:
    """Не даём кредит под прошлогоднюю прибыль, если выручка упала (30-02)."""
    inp = cp.t_base()
    fin = FinancialsData(cp.ok("fin"), (FinancialYear(2025, 120_000_000, 12_000_000, 0),))
    snap = replace(inp.snapshot, financials=fin)  # 2110/12 = 10 млн, выручка по счёту 5 млн
    f = feats(replace(inp, snapshot=snap))
    assert f.flow_model_rub == 500_000  # 12 млн / 12 × (5 / 10)


def test_negative_profit_gives_zero_flow_not_negative() -> None:
    inp = cp.t_base()
    fin = FinancialsData(cp.ok("fin"), (FinancialYear(2025, 60_000_000, -3_000_000, 0),))
    f = feats(replace(inp, snapshot=replace(inp.snapshot, financials=fin)))
    assert f.flow_model_rub == 0


def test_flow_by_margin_for_each_industry_group() -> None:
    expected = {
        "46.90": "TRADE",
        "56.10": "FOOD",
        "25.62": "MANUFACTURING",
        "43.21": "MANUFACTURING",
        "62.01": "IT",
        "01.11": "AGRO",
        "96.02": "SERVICES",
        "": "SERVICES",
        "x": "SERVICES",
    }
    for okved, group in expected.items():
        assert ft.industry_group(okved, POLICY) == group
    inp = base_with_turnover([1_000_000] * 12)
    inp = replace(
        inp,
        snapshot=replace(inp.snapshot, registry=replace(inp.snapshot.registry, okved_main="56.10")),
    )
    assert feats(inp).flow_model_rub == 100_000  # 10% общепита


def test_flow_crosscheck_ratio_matches_sokolova_example() -> None:
    f = feats(cp.sokolova())
    assert f.flow_observed_rub == 113_000  # (905 000 − 795 000) + 3 000
    assert f.flow_crosscheck_ratio is not None
    assert f.flow_crosscheck_ratio.quantize(D("0.01")) == D("1.25")


# ---------------------------------------------------------------- тренд, вариация, сезонность, шок


def test_theil_sen_is_robust_to_one_outlier() -> None:
    clean = [D(100 + i) for i in range(12)]
    spiked = [*clean[:5], D(10_000), *clean[6:]]
    assert ft.theil_sen_slope(clean) == D(1)
    assert ft.theil_sen_slope(spiked) == D(1)


def test_trend_of_flat_and_growing_series() -> None:
    assert feats(base_with_turnover([1_000_000] * 12)).revenue_trend_pct == D(0)
    growing = [1_000_000 + 10_000 * i for i in range(12)]
    trend = feats(base_with_turnover(growing)).revenue_trend_pct
    assert trend is not None
    assert trend > D("0.05")


def test_trend_needs_six_points_else_two_years_of_financials_or_none() -> None:
    inp = base_with_turnover([1_000_000] * 4)
    assert feats(inp).revenue_trend_pct is None
    fin = FinancialsData(
        cp.ok("fin"),
        (FinancialYear(2025, 420_000_000, 1, 1), FinancialYear(2024, 388_000_000, 1, 1)),
    )
    with_fin = replace(inp, snapshot=replace(inp.snapshot, financials=fin))
    trend = feats(with_fin).revenue_trend_pct
    assert trend is not None
    assert trend.quantize(D("0.001")) == D("0.082")


def test_year_over_year_for_long_series() -> None:
    values = [1_000_000] * 12 + [1_200_000] * 12
    assert feats(base_with_turnover(values)).revenue_trend_pct == D("0.2")


def test_seasonal_series_is_flagged_and_has_zero_year_over_year() -> None:
    f = feats(cp.zarya())
    assert f.is_seasonal
    assert f.revenue_trend_pct == D(0)
    assert f.stress_shock == D("0.20")
    assert f.bad_months == 3  # февраль–апрель (30-17)


def test_agro_okved_is_seasonal_below_24_months() -> None:
    inp = base_with_turnover([1_000_000] * 8)
    inp = replace(
        inp,
        snapshot=replace(inp.snapshot, registry=replace(inp.snapshot.registry, okved_main="01.11")),
    )
    f = feats(inp)
    assert f.is_seasonal
    assert f.revenue_trend_pct is None  # у сезонного короче 24 мес. тренд только по отчётности


def test_flat_series_is_not_seasonal() -> None:
    f = feats(base_with_turnover([1_000_000] * 24))
    assert not f.is_seasonal
    assert f.revenue_cv == D(0)


def test_cv_needs_six_points_and_shock_stays_between_20_and_40_percent() -> None:
    assert feats(base_with_turnover([1_000_000] * 5)).revenue_cv is None
    assert feats(base_with_turnover([1_000_000] * 5)).stress_shock == D("0.20")
    assert feats(base_with_turnover([1_000_000] * 12)).stress_shock == D(
        "0.20"
    )  # CV 0 → нижняя граница
    wild = [100_000, 3_000_000] * 6
    f = feats(base_with_turnover(wild))
    assert f.revenue_cv is not None
    assert f.revenue_cv > D("0.4")
    assert f.stress_shock == D("0.40")
    mid = [900_000, 1_400_000] * 6
    f = feats(base_with_turnover(mid))
    assert D("0.2") < f.stress_shock < D("0.4")
    assert f.stress_shock == f.revenue_cv


@pytest.mark.parametrize(
    ("values", "ok_"),
    [([1_000_000] * 12, True), ([100_000, 5_000_000] * 6, True), ([0] * 12, True)],
)
def test_shock_is_always_in_bounds(values: list[int], ok_: bool) -> None:
    shock = feats(base_with_turnover(values)).stress_shock
    assert (D("0.20") <= shock <= D("0.40")) is ok_


def test_pearson_and_statistics_helpers() -> None:
    xs = [D(1), D(2), D(3), D(4)]
    assert ft.pearson(xs, xs) == D(1)
    assert ft.pearson(xs, [D(5)] * 4) is None
    assert ft.median([D(3), D(1), D(2)]) == D(2)
    assert ft.median([D(1), D(2), D(3), D(4)]) == D("2.5")
    assert ft.pstdev([D(2), D(4), D(4), D(4), D(5), D(5), D(7), D(9)]) == D(2)


# ---------------------------------------------------------------- БКИ, долги, платежи


def test_existing_payments_and_debt_of_sokolova() -> None:
    f = feats(cp.sokolova())
    assert f.existing_payments_rub == 3_000
    assert f.total_debt_rub == 60_000
    assert f.debt_to_revenue is not None
    assert f.debt_to_revenue.quantize(D("0.0001")) == D("0.0055")
    assert f.coverage_existing is not None
    assert f.coverage_existing > 30
    assert f.credit_history_class == "CLEAN"
    assert f.bki_known


def test_our_loan_in_abs_and_bki_is_counted_once() -> None:
    inp = cp.snabkontrakt()
    shared = OurLoan("snab-loan-1", 350_000, 5_000_000)  # тот же uid, что в БКИ
    only_ours = OurLoan("snab-loan-new", 40_000, 900_000)  # в БКИ его ещё нет
    both = replace(
        inp,
        snapshot=replace(
            inp.snapshot, customer=replace(inp.snapshot.customer, our_loans=(shared,))
        ),
    )
    f = feats(both)
    assert f.existing_payments_rub == 600_000
    assert f.total_debt_rub == 8_000_000
    extra = replace(
        inp,
        snapshot=replace(
            inp.snapshot, customer=replace(inp.snapshot.customer, our_loans=(shared, only_ours))
        ),
    )
    f = feats(extra)
    assert f.existing_payments_rub == 640_000
    assert f.total_debt_rub == 8_900_000


def test_contingent_liabilities_count_at_half() -> None:
    inp = cp.sokolova()
    report = replace(cp.company_subject(inp).report, contingent_liabilities_rub=1_000_000)  # type: ignore[type-var]
    f = feats(cp.with_company_report(inp, report))
    assert f.total_debt_rub == 60_000 + 500_000
    assert f.existing_payments_rub == 3_000  # поручительства в платежи не входят


def test_directors_personal_debts_do_not_load_the_company() -> None:
    f = feats(cp.stankoprom())
    assert f.existing_payments_rub == 0  # карта директора идёт в класс истории, не в нагрузку ООО
    assert f.total_debt_rub == 0


def test_no_bki_data_gives_unknown_not_zero() -> None:
    inp = cp.sokolova()
    absent = replace(
        inp.snapshot,
        bki=(BkiSubject(SubjectRole.COMPANY, "x", SourceMeta(SourceStatus.NOT_REQUESTED)),),
    )
    f = feats(replace(inp, snapshot=absent, context=replace(inp.context, mode=Mode.PREVIEW)))
    assert not f.bki_known
    assert f.debt_to_revenue is None  # «неизвестно», в скоринге осторожное значение
    assert f.credit_history_class == "NO_HISTORY"


def _history(**kwargs: int) -> BkiReport:
    base = {
        "has_history": True,
        "history_months": 60,
        "active_obligations": 1,
        "closed_obligations": 1,
    }
    return BkiReport(**(base | kwargs))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (_history(), "CLEAN"),
        (_history(history_months=23), "THIN_CLEAN"),  # граница 24 мес.
        (_history(history_months=24), "CLEAN"),
        (_history(closed_obligations=0), "THIN_CLEAN"),  # одно обязательство (Гарипов)
        (_history(max_overdue_days_24m=5), "MINOR"),
        (_history(max_overdue_days_24m=5, history_months=10), "THIN_CLEAN"),  # тонкая история
        (_history(max_overdue_days_24m=30), "PAST_30"),
        (_history(max_overdue_days_24m=59), "PAST_30"),
        (_history(max_overdue_days_24m=60), "PAST_60"),
        (_history(max_overdue_days_24m=90), "PAST_90"),
        (_history(current_overdue_days=45, current_overdue_rub=154_200), "CURRENT_30_89"),
        (_history(current_overdue_days=45, current_overdue_rub=9_999), "CLEAN"),  # техническая
        (_history(current_overdue_days=94, current_overdue_rub=452_000), "PAST_90"),
        (BkiReport(), "NO_HISTORY"),
    ],
)
def test_subject_history_classes(report: BkiReport, expected: str) -> None:
    inp = cp.sokolova()
    f = feats(cp.with_company_report(inp, report))
    assert f.credit_history_class == expected


def test_company_without_history_is_not_better_than_thin_clean() -> None:
    f = feats(cp.quick_start())
    assert f.credit_history_class == "THIN_CLEAN"  # владелец чистый, у компании истории нет
    assert f.is_bank_customer
    assert f.business_age_months == 3


def test_worst_subject_class_wins_and_all_missing_is_no_history() -> None:
    inp = cp.snabkontrakt()
    bad = replace(cp.clean_person(), max_overdue_days_24m=70)
    subjects = tuple(
        replace(s, report=bad) if s.role == SubjectRole.DIRECTOR else s for s in inp.snapshot.bki
    )
    assert (
        feats(replace(inp, snapshot=replace(inp.snapshot, bki=subjects))).credit_history_class
        == "PAST_60"
    )
    nobody = tuple(cp.bki_absent(s.role, s.inn) for s in inp.snapshot.bki)
    assert (
        feats(replace(inp, snapshot=replace(inp.snapshot, bki=nobody))).credit_history_class
        == "NO_HISTORY"
    )
    assert ft.history_class((), POLICY) == "NO_HISTORY"


def test_inquiries_overdue_and_restructuring_come_from_all_subjects() -> None:
    f = feats(cp.romashka())
    assert (f.inquiries_30d, f.rejected_90d) == (6, 2)
    assert f.max_overdue_24m_days == 94
    inp = cp.sokolova()
    restructured = replace(cp.company_subject(inp).report, restructurings_24m=1)  # type: ignore[type-var]
    assert feats(cp.with_company_report(inp, restructured)).restructurings_24m == 1


# ---------------------------------------------------------------- налоги, компания, заявка


def test_tax_ratio_uses_cautious_revenue_and_ignores_penalties() -> None:
    f = feats(cp.romashka())
    assert f.tax_debt_rub == 1_150_000
    assert f.tax_penalties_rub == 42_000
    assert f.tax_debt_ratio is not None
    assert f.tax_debt_ratio.quantize(D("0.0001")) == D("0.1453")


def test_unavailable_tax_profile_is_unknown() -> None:
    inp = cp.sokolova()
    snap = replace(inp.snapshot, tax=TaxData(SourceMeta(SourceStatus.UNAVAILABLE)))
    f = feats(replace(inp, snapshot=snap))
    assert not f.tax_known
    assert f.tax_debt_ratio is None
    assert f.tax_debt_rub == 0


def test_company_features_age_tenure_and_collateral() -> None:
    f = feats(cp.sokolova())
    assert f.business_age_months == 42
    assert f.customer_tenure_months == 41
    assert f.net_profit_rub is None  # у ИП отчётности нет
    s = feats(cp.stankoprom())
    assert s.collateral_provided
    assert s.security_confirmed
    assert not s.guarantor_confirmed
    assert s.net_profit_rub == 30_700_000
    assert s.interest_paid_rub == 1_900_000
    assert s.customer_tenure_months is None
    assert not s.is_bank_customer
    q = feats(cp.quick_start(with_guarantor=True))
    assert q.guarantor_confirmed
    assert q.security_confirmed
    assert not q.collateral_provided


def test_unsigned_guarantor_is_not_security() -> None:
    inp = cp.quick_start(with_guarantor=True)
    unsigned = replace(
        inp.application, guarantor=replace(inp.application.guarantor, consent_signed=False)
    )  # type: ignore[type-var]
    assert not feats(replace(inp, application=unsigned)).security_confirmed


# ---------------------------------------------------------------- ФИО


@pytest.mark.parametrize(
    ("form", "registry", "same"),
    [
        ("Иванов Иван Иванович", "Иванов Иван Иванович", True),
        ("иванов  иван иванович", "Иванов Иван Иванович", True),  # регистр и пробелы
        ("Королёв Пётр Сергеевич", "Королев Петр Сергеевич", True),  # ё/е
        ("Иванов И. И.", "Иванов Иван Иванович", True),  # инициалы
        ("Иванов И.И.", "Иванов Иван Иванович", True),
        ("Иванов Иван Иванович", "Иванов И. И.", True),
        ("Иванов Иван", "Иванов Иван Иванович", False),  # нет отчества
        ("Петров Иван Иванович", "Иванов Иван Иванович", False),  # другая фамилия
        ("Иванов Пётр Иванович", "Иванов Иван Иванович", False),  # другое имя
        ("Иванов П. И.", "Иванов Иван Иванович", False),  # другой инициал
        ("", "Иванов Иван Иванович", False),
    ],
)
def test_name_matching_table(form: str, registry: str, same: bool) -> None:
    assert ft.names_match(form, registry) is same


def test_form_matches_registry_feature() -> None:
    inp = cp.snabkontrakt()
    assert feats(inp).form_matches_registry
    other = replace(inp.application, director_name_in_form="Сидоров Сидор Сидорович")
    assert not feats(replace(inp, application=other)).form_matches_registry
    assert feats(cp.sokolova()).form_matches_registry  # данных для сверки нет → true


def test_customer_data_without_since_has_no_tenure() -> None:
    inp = cp.sokolova()
    snap = replace(inp.snapshot, customer=CustomerData(cp.ok("abs"), True, None))
    assert feats(replace(inp, snapshot=snap)).customer_tenure_months is None


def test_obligation_dataclass_defaults() -> None:
    o = BkiObligation("u", "LOAN")
    assert o.status == "ACTIVE"
    assert o.monthly_payment_rub == 0
