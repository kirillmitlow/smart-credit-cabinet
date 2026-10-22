"""Флаги (T-288, T-290, 30-04, 30-02): границы порогов, ложные срабатывания, приоритеты, молодой бизнес.

Ряды собраны вручную из T-BASE (24 мес. по 5 000 000, списания 85%, 12 плательщиков, ОКВЭД 62.01,
УСН). Флаги проверяются и напрямую (`evaluate_flags`), и через `decide()`, где видно приоритет:
стоп-фактор → `NEEDS_INFO` → условное встречное → ручной разбор.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import yaml

from app.modules.decisioning import decide, parse_policy
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.flags import evaluate_flags
from app.modules.decisioning.types import (
    BkiSubject,
    ComplianceData,
    DecisionInput,
    FinancialsData,
    FinancialYear,
    Outcome,
    ReasonCode,
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
USUAL_OUT = D("0.85")  # списания в обычный месяц T-BASE
PASS_THROUGH = D("0.99")  # деньги проходят насквозь


def flags_of(inp: DecisionInput) -> list[ReasonCode]:
    return list(evaluate_flags(inp, compute_features(inp)))


def codes_of(inp: DecisionInput) -> list[str]:
    return [r.code for r in flags_of(inp)]


def rules_of(inp: DecisionInput, code: str) -> list[str]:
    return [str(r.params["rule"]) for r in flags_of(inp) if r.code == code]


def with_policy(inp: DecisionInput, *path: str, value: object) -> DecisionInput:
    """Копия входа с одним изменённым узлом политики (путь по ключам YAML)."""
    data: dict[str, Any] = yaml.safe_load(cp.POLICY_PATH.read_text(encoding="utf-8"))
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return replace(inp, policy=parse_policy(copy.deepcopy(data)))


def series_input(
    incoming: list[int],
    *,
    out_share: Decimal = USUAL_OUT,
    payers: int | None = 12,
    okved: str | None = None,
    fin: bool = False,
    last: date = date(2026, 9, 1),
) -> DecisionInput:
    """T-BASE с другим рядом оборотов; отчётности нет (если не просят), сверки не мешают."""
    base = cp.t_base()
    starts = cp.month_starts(len(incoming), last)
    months = tuple(
        TurnoverMonth(m, v, int(v * out_share), payers)
        for m, v in zip(starts, incoming, strict=True)
    )
    registry = base.snapshot.registry
    if okved is not None:
        registry = replace(registry, okved_main=okved)
    snap = replace(
        base.snapshot,
        registry=registry,
        turnover=TurnoverData(cp.ok("abs-turnover"), months),
        financials=base.snapshot.financials if fin else FinancialsData(),
    )
    return replace(base, snapshot=snap)


# ---------------------------------------------------------------- MASS_REGISTRATION


@pytest.mark.parametrize(
    ("changes", "which"),
    [
        ({"mass_address": True}, "адрес"),
        ({"mass_director": True}, "руководитель"),
        ({"mass_founder": True}, "учредитель"),
        ({"mass_address": True, "mass_founder": True}, "адрес, учредитель"),
    ],
)
def test_mass_registration_any_of_three_signs(changes: dict[str, bool], which: str) -> None:
    inp = cp.t_base()
    tax = replace(inp.snapshot.tax, **changes)
    (flag,) = flags_of(cp.with_snapshot(inp, tax=tax))
    assert flag.code == "MASS_REGISTRATION"
    assert flag.params["which"] == which


def test_mass_registration_is_silent_for_clean_tax_unavailable_tax_or_disabled_rule() -> None:
    inp = cp.t_base()
    assert codes_of(inp) == []
    # профиль ФНС недоступен: массовость неизвестна, это не признак (SOURCE_UNAVAILABLE отдельно)
    gone = TaxData(SourceMeta(SourceStatus.UNAVAILABLE), mass_address=True)
    assert "MASS_REGISTRATION" not in codes_of(cp.with_snapshot(inp, tax=gone))
    flagged = cp.with_snapshot(inp, tax=replace(inp.snapshot.tax, mass_address=True))
    off = with_policy(flagged, "flags", "mass_registration", "enabled", value=False)
    assert codes_of(off) == []


# ---------------------------------------------------------------- OVERDUE_30_89


def overdue_input(days: int, rub: int = 154_200) -> DecisionInput:
    return cp.with_company_report(cp.t_base(), cp._overdue_report(days, rub))


@pytest.mark.parametrize(
    ("days", "flag", "stop"),
    [
        (29, False, False),  # чуть ниже
        (30, True, False),  # ровно 30 — уже флаг
        (45, True, False),
        (89, True, False),
        (90, False, True),  # с 90-го дня стоп-фактор, дня-щели нет
    ],
)
def test_overdue_30_89_day_boundaries(days: int, flag: bool, stop: bool) -> None:
    inp = overdue_input(days)
    assert ("OVERDUE_30_89" in codes_of(inp)) is flag
    result = decide(inp)
    assert ("CURRENT_OVERDUE_90" in result.reason_codes) is stop
    if stop:
        assert result.reason_codes == ("CURRENT_OVERDUE_90",)  # стоп сильнее флага


@pytest.mark.parametrize(("rub", "flag"), [(9_999, False), (10_000, True), (10_001, True)])
def test_overdue_30_89_amount_boundary(rub: int, flag: bool) -> None:
    assert ("OVERDUE_30_89" in codes_of(overdue_input(45, rub))) is flag


def test_overdue_flag_params_name_days_amount_and_subject() -> None:
    (flag,) = flags_of(overdue_input(45))
    assert flag.params == {"days": 45, "overdue_rub": 154_200, "subject": "COMPANY"}


def test_overdue_of_director_counts_and_the_worst_subject_is_named() -> None:
    inp = overdue_input(35, 50_000)
    director = next(s for s in inp.snapshot.bki if s.role == SubjectRole.DIRECTOR)
    assert director.report is not None
    worse = replace(
        director,
        report=replace(director.report, current_overdue_days=60, current_overdue_rub=20_000),
    )
    subjects = tuple(worse if s.role == SubjectRole.DIRECTOR else s for s in inp.snapshot.bki)
    (flag,) = flags_of(cp.with_snapshot(inp, bki=subjects))
    assert flag.params["subject"] == "DIRECTOR"
    assert flag.params["days"] == 60


def test_overdue_of_an_unavailable_bki_subject_is_not_read() -> None:
    inp = overdue_input(45)
    gone = tuple(
        BkiSubject(s.role, s.inn, SourceMeta(SourceStatus.UNAVAILABLE)) for s in inp.snapshot.bki
    )
    assert codes_of(cp.with_snapshot(inp, bki=gone)) == []


def test_overdue_flag_can_be_switched_off_in_config() -> None:
    off = with_policy(overdue_input(45), "flags", "overdue_30_89", "enabled", value=False)
    assert codes_of(off) == []


# ---------------------------------------------------------------- DATA_MISMATCH: обороты и отчётность


def turnover_vs_fin(monthly: int, revenue_2110: int = 60_000_000) -> DecisionInput:
    """24 мес. по `monthly` (2025 год целиком в окне) и строка 2110 за 2025 год."""
    inp = series_input([monthly] * 24)
    fin = FinancialsData(
        cp.ok("gir-bo"),
        (
            FinancialYear(2025, revenue_2110, revenue_2110 // 10, 0),
            FinancialYear(2024, revenue_2110, revenue_2110 // 10, 0),
        ),
    )
    return cp.with_snapshot(inp, financials=fin)


@pytest.mark.parametrize(
    ("monthly", "flag"),
    [
        (6_495_000, False),  # (77,94 − 60) / 60 = 29,9%
        (6_500_000, False),  # ровно 30,0%: «больше 30%», флага нет
        (6_505_000, True),  # 30,1%
        (3_505_000, False),  # |42,06 − 60| / 60 = 29,9%
        (3_500_000, False),  # |42,00 − 60| / 60 = ровно 30,0%
        (3_495_000, True),  # |41,94 − 60| / 60 = 30,1%
        (5_000_000, False),
    ],
)
def test_mismatch_turnover_vs_financials_boundary(monthly: int, flag: bool) -> None:
    inp = turnover_vs_fin(monthly)
    assert ("TURNOVER_VS_FINANCIALS" in rules_of(inp, "DATA_MISMATCH")) is flag


def test_mismatch_denominator_is_the_report_so_plus_and_minus_are_symmetric() -> None:
    up, down = turnover_vs_fin(6_505_000), turnover_vs_fin(3_495_000)
    assert compute_features(up).mismatch_turnover_fin is not None
    for inp in (up, down):
        (flag,) = flags_of(inp)
        assert flag.params["rule"] == "TURNOVER_VS_FINANCIALS"
        assert flag.params["year"] == 2025


def test_t_mismatch_parameter_forty_gives_sixty_six_point_seven() -> None:
    (flag,) = flags_of(cp.t_mismatch())
    assert str(flag.params["value"])[:6] == "0.6666"
    assert "66,67%" in str(flag.params["metric"])


def test_turnover_is_compared_without_vat_and_by_the_months_own_rate() -> None:
    """Снабконтракт: 18 млн с НДС 20% и 18,3 млн с НДС 22% — это 15 млн чистыми, расхождения нет."""
    assert flags_of(cp.snabkontrakt()) == []
    comparison = compute_features(cp.snabkontrakt()).mismatch_turnover_fin
    assert comparison is not None
    assert (comparison.year, comparison.a_rub, comparison.b_rub) == (2025, 180_000_000, 180_000_000)
    assert comparison.deviation == 0  # с НДС было бы 216 млн, то есть +20%
    wrong = cp.snabkontrakt()
    fin = FinancialsData(
        cp.ok("gir-bo"), (FinancialYear(2025, 180_000_000 * 70 // 100, 13_200_000, 1_200_000),)
    )
    assert "TURNOVER_VS_FINANCIALS" in rules_of(
        cp.with_snapshot(wrong, financials=fin), "DATA_MISMATCH"
    )


def test_incomplete_calendar_year_is_not_compared() -> None:
    """В окне 24 мес. (10.2024…09.2026) 2024 год неполный: его строка 2110 не участвует."""
    inp = turnover_vs_fin(5_000_000, revenue_2110=60_000_000)
    only_2024 = FinancialsData(cp.ok("gir-bo"), (FinancialYear(2024, 1_000_000, 0, 0),))
    assert flags_of(cp.with_snapshot(inp, financials=only_2024)) == []
    # 18 мес. (04.2025…09.2026): 2025 год целиком не лежит в окне, как у t-anomaly
    short = series_input([5_000_000] * 18, fin=True)
    assert compute_features(short).mismatch_turnover_fin is None


def test_financials_zero_revenue_or_missing_are_skipped() -> None:
    inp = turnover_vs_fin(5_000_000, revenue_2110=0)
    assert compute_features(inp).mismatch_turnover_fin is None
    assert compute_features(series_input([5_000_000] * 24)).mismatch_turnover_fin is None


def test_the_worst_complete_year_is_reported_when_two_years_fit_the_window() -> None:
    # окно 24 мес. 01.2024…12.2025: оба года целиком
    inp = series_input([5_000_000] * 24, fin=False, last=date(2025, 12, 1))
    fin = FinancialsData(
        cp.ok("gir-bo"),
        (FinancialYear(2025, 60_000_000, 0, 0), FinancialYear(2024, 30_000_000, 0, 0)),
    )
    comparison = compute_features(replace(inp, snapshot=replace(inp.snapshot, financials=fin)))
    assert comparison.mismatch_turnover_fin is not None
    assert comparison.mismatch_turnover_fin.year == 2024  # 100% против 0%


# ---------------------------------------------------------------- DATA_MISMATCH: заявленная выручка


@pytest.mark.parametrize(
    ("declared", "flag"),
    [
        (6_500_000, False),  # |6,5 − 5| / 5 = 30% ровно
        (6_500_001, True),
        (3_500_000, False),  # −30% ровно
        (3_499_999, True),
        (5_000_000, False),
        (None, False),
        (0, False),  # «не заявлено»
    ],
)
def test_mismatch_declared_boundary(declared: int | None, flag: bool) -> None:
    inp = cp.with_application(cp.t_base(), declared_monthly_revenue_rub=declared)
    assert ("DECLARED_VS_CALCULATED" in rules_of(inp, "DATA_MISMATCH")) is flag


def test_declared_denominator_is_the_calculated_cautious_revenue() -> None:
    inp = cp.with_application(cp.t_base(), declared_monthly_revenue_rub=10_000_000)
    (flag,) = flags_of(inp)
    assert flag.params["value"] == D(1)  # |10 − 5| / 5, а не / 10
    assert flag.params["a"] == "10 000 000 ₽"


# ---------------------------------------------------------------- DATA_MISMATCH: выписка клиента


def statement_input(monthly: int, revenue_2110: int = 60_000_000) -> DecisionInput:
    """Выписка за календарный 2025 год и строка 2110 за него; обороты банка пусты."""
    inp = cp.garipov(second_pass=True)
    statement = StatementData(
        cp.ok("statement"),
        tuple(
            TurnoverMonth(m, monthly, monthly * 85 // 100)
            for m in cp.month_starts(12, date(2025, 12, 1))
        ),
    )
    fin = FinancialsData(cp.ok("gir-bo"), (FinancialYear(2025, revenue_2110, 0, 0),))
    return cp.with_snapshot(inp, statement=statement, financials=fin)


@pytest.mark.parametrize(
    ("monthly", "flag"),
    [(6_495_000, False), (6_500_000, False), (6_505_000, True), (5_000_000, False)],
)
def test_mismatch_statement_boundary(monthly: int, flag: bool) -> None:
    assert (
        "STATEMENT_VS_FINANCIALS" in rules_of(statement_input(monthly), "DATA_MISMATCH")
    ) is flag


def test_statement_of_another_owner_is_not_compared() -> None:
    inp = statement_input(9_000_000)
    other = replace(inp.snapshot.statement, owner_inn_matches=False)
    assert flags_of(cp.with_snapshot(inp, statement=other)) == []


# ---------------------------------------------------------------- DATA_MISMATCH: поток и директор


@pytest.mark.parametrize(
    ("ratio", "flag"), [("0.49", True), ("0.4999", True), ("0.5", False), ("0.51", False)]
)
def test_flow_crosscheck_boundary(ratio: str, flag: bool) -> None:
    inp = cp.t_base()
    feats = replace(
        compute_features(inp),
        flow_crosscheck_ratio=D(ratio),
        flow_observed_rub=int(750_000 * D(ratio)),
    )
    found = [r for r in evaluate_flags(inp, feats) if r.code == "DATA_MISMATCH"]
    assert bool(found) is flag
    if flag:
        assert found[0].params["rule"] == "FLOW_CROSSCHECK"


def test_flow_crosscheck_on_real_series_a_pass_through_account() -> None:
    """Остаток на счёте 5% выручки при потоке модели 15% (ОКВЭД 62) → отношение 0,33."""
    inp = series_input([5_000_000] * 24, out_share=D("0.95"))
    features = compute_features(inp)
    assert features.flow_crosscheck_ratio is not None
    assert features.flow_crosscheck_ratio < D("0.5")
    assert "FLOW_CROSSCHECK" in rules_of(inp, "DATA_MISMATCH")


def test_flow_crosscheck_is_skipped_without_flow_or_series() -> None:
    inp = series_input([5_000_000] * 24, out_share=D("0.95"))
    inp = cp.with_snapshot(inp, turnover=TurnoverData(cp.not_found("abs")))
    assert flags_of(inp) == []


def test_director_in_form_differs_from_registry() -> None:
    inp = cp.with_application(cp.t_base(), director_name_in_form="Иванов Иван Иванович")
    (flag,) = flags_of(inp)
    assert flag.code == "DATA_MISMATCH"
    assert flag.params["rule"] == "DIRECTOR_VS_REGISTRY"
    assert flag.params["a"] == "Иванов Иван Иванович"
    assert flag.params["b"] == "Миронов Павел Олегович"


@pytest.mark.parametrize(
    "form",
    [
        "Миронов Павел Олегович",
        "миронов павел олегович",
        "Миронов П. О.",
        "Миронов  Павел О.",
        None,
    ],
)
def test_director_spelling_variants_do_not_raise_the_flag(form: str | None) -> None:
    assert flags_of(cp.with_application(cp.t_base(), director_name_in_form=form)) == []


def test_several_mismatches_give_one_reason_per_rule() -> None:
    inp = cp.with_application(
        turnover_vs_fin(6_505_000),
        declared_monthly_revenue_rub=20_000_000,
        director_name_in_form="Иванов Иван Иванович",
    )
    assert rules_of(inp, "DATA_MISMATCH") == [
        "TURNOVER_VS_FINANCIALS",
        "DECLARED_VS_CALCULATED",
        "DIRECTOR_VS_REGISTRY",
    ]
    result = decide(inp)
    assert result.outcome == Outcome.MANUAL_REVIEW
    assert result.reason_codes.count("DATA_MISMATCH") == 3


def _flow_case() -> DecisionInput:
    return series_input([5_000_000] * 24, out_share=D("0.95"))


def _director_case() -> DecisionInput:
    return cp.with_application(cp.t_base(), director_name_in_form="Иванов Иван Иванович")


MISMATCH_CASES = {
    "turnover_vs_financials": lambda: turnover_vs_fin(6_505_000),
    "declared_vs_calculated": lambda: cp.with_application(
        cp.t_base(), declared_monthly_revenue_rub=20_000_000
    ),
    "statement_vs_financials": lambda: statement_input(6_505_000),
    "flow_crosscheck": _flow_case,
    "director_vs_registry": _director_case,
}


@pytest.mark.parametrize("rule", sorted(MISMATCH_CASES))
def test_each_mismatch_rule_has_its_own_switch(rule: str) -> None:
    inp = MISMATCH_CASES[rule]()
    assert codes_of(inp) == ["DATA_MISMATCH"]
    off = with_policy(inp, "flags", "data_mismatch", rule, "enabled", value=False)
    assert codes_of(off) == []


def test_disabling_one_mismatch_rule_silences_exactly_it() -> None:
    inp = cp.with_application(turnover_vs_fin(6_505_000), declared_monthly_revenue_rub=20_000_000)
    off = with_policy(
        inp, "flags", "data_mismatch", "turnover_vs_financials", "enabled", value=False
    )
    assert rules_of(off, "DATA_MISMATCH") == ["DECLARED_VS_CALCULATED"]


# ---------------------------------------------------------------- TURNOVER_ANOMALY: накачка


def pumped(base: int, recent: int, *, length: int = 18, **kw: Any) -> DecisionInput:
    return series_input([base] * (length - 3) + [recent] * 3, **kw)


@pytest.mark.parametrize(
    ("recent", "flag"),
    [
        (7_900_000, False),  # ×1,58
        (7_990_000, False),  # ×1,598
        (8_000_000, True),  # ×1,6 ровно, MAD = 0 → z = 8,09
        (9_000_000, True),  # t-anomaly: ×1,8, z = 10,79
        (5_000_000, False),
        (3_000_000, False),  # падение — не накачка
    ],
)
def test_pump_ratio_boundary(recent: int, flag: bool) -> None:
    assert ("PUMP" in rules_of(pumped(5_000_000, recent), "TURNOVER_ANOMALY")) is flag


def base_with_spread(spread: int) -> list[int]:
    """9 месяцев базы: медиана 5 млн, MAD ровно `spread` (4 значения в центре, 5 с разбросом)."""
    return [5_000_000 - spread] * 3 + [5_000_000] * 4 + [5_000_000 + spread] * 2


@pytest.mark.parametrize(
    ("spread", "flag"),
    [
        (570_000, True),  # z = 0,6745 × 3 000 000 / 570 000 = 3,55
        (578_000, True),  # 3,5006
        (579_000, False),  # 3,495
        (590_000, False),  # 3,43
        (2_000_000, False),  # шумная база: ×1,6, но z = 1,01
    ],
)
def test_pump_needs_both_ratio_and_modified_z(spread: int, flag: bool) -> None:
    series = [5_000_000] * 6 + base_with_spread(spread) + [8_000_000] * 3  # 18 мес.
    inp = series_input(series)
    stat = compute_features(inp).pump
    assert stat is not None
    assert stat.ratio == D("1.6")
    assert ("PUMP" in rules_of(inp, "TURNOVER_ANOMALY")) is flag


def test_pump_with_zero_mad_uses_five_percent_of_the_base() -> None:
    stat = compute_features(pumped(5_000_000, 9_000_000)).pump
    assert stat is not None
    assert stat.ratio == D("1.8")
    assert abs(stat.modified_z - D("10.792")) < D("0.0005")  # 0,6745 × 4 000 000 / 250 000
    assert (stat.recent_rub, stat.base_rub) == (9_000_000, 5_000_000)


@pytest.mark.parametrize("length", [3, 11])
def test_pump_needs_twelve_months_of_turnover(length: int) -> None:
    assert rules_of(pumped(5_000_000, 20_000_000, length=length), "TURNOVER_ANOMALY") == []


def test_pump_twelve_months_is_enough() -> None:
    assert rules_of(pumped(5_000_000, 9_000_000, length=12), "TURNOVER_ANOMALY") == ["PUMP"]


def test_first_time_jump_in_a_24_month_series_is_not_hidden_by_the_seasonal_exception() -> None:
    """30-02, 30-17: 24 мес. спокойных, потом скачок 5 → 9 млн: x / x_год_назад = 1,8 не гасит флаг."""
    inp = pumped(5_000_000, 9_000_000, length=24)
    stat = compute_features(inp).pump
    assert stat is not None
    assert stat.prior_year_ratio == D(1)  # годом ранее скачка не было
    assert rules_of(inp, "TURNOVER_ANOMALY") == ["PUMP"]


def test_repeating_seasonal_jump_is_not_an_anomaly() -> None:
    """Годом ранее те же 3 месяца тоже были ×1,8 над своей базой: сезон, флага нет."""
    year = [5_000_000] * 9 + [9_000_000] * 3
    inp = series_input(year + year)
    stat = compute_features(inp).pump
    assert stat is not None
    assert stat.ratio == D("1.8")
    assert stat.prior_year_ratio == D("1.8")
    assert rules_of(inp, "TURNOVER_ANOMALY") == []


@pytest.mark.parametrize(
    ("last_year_recent", "flag"),
    [(6_450_000, True), (6_500_000, False)],  # ×1,29 против ×1,30 «своё к своей базе»
)
def test_seasonal_exception_boundary_is_one_point_three(last_year_recent: int, flag: bool) -> None:
    previous = [5_000_000] * 9 + [last_year_recent] * 3
    this_year = [5_000_000] * 9 + [9_000_000] * 3
    assert ("PUMP" in rules_of(series_input(previous + this_year), "TURNOVER_ANOMALY")) is flag


def test_seasonal_zarya_does_not_trigger_the_pump_rule() -> None:
    """Заря: отношение 2,10, но z = 1,74 < 3,5 (30-17), а годом ранее то же ×2,10."""
    inp = cp.zarya()
    stat = compute_features(inp).pump
    assert stat is not None
    assert D("2.10") <= stat.ratio < D("2.11")
    assert stat.modified_z < D("3.5")
    assert codes_of(inp) == []


def test_pump_is_computed_on_net_of_vat_series() -> None:
    """Смена ставки НДС 20% → 22% с января 2026 не выглядит ростом оборотов."""
    base = cp.snabkontrakt()
    stat = compute_features(base).pump
    assert stat is not None
    assert stat.ratio == D(1)
    assert stat.modified_z == D(0)


def test_pump_works_on_a_client_statement_too() -> None:
    inp = cp.garipov(second_pass=True)
    months = tuple(
        TurnoverMonth(m, 700_000 if m < date(2026, 7, 1) else 1_400_000, 600_000)
        for m in cp.month_starts(12)
    )
    statement = replace(inp.snapshot.statement, months=months)
    pumped_statement = cp.with_snapshot(inp, statement=statement)
    assert "PUMP" in rules_of(pumped_statement, "TURNOVER_ANOMALY")


def test_pump_switch_off() -> None:
    off = with_policy(
        pumped(5_000_000, 9_000_000), "flags", "turnover_anomaly", "pump", "enabled", value=False
    )
    assert rules_of(off, "TURNOVER_ANOMALY") == []


# ---------------------------------------------------------------- TURNOVER_ANOMALY: транзит


def transit_input(passing: int, share: Decimal = PASS_THROUGH, length: int = 12) -> DecisionInput:
    """`passing` из последних 12 месяцев с долей списаний `share`, остальные — 85%."""
    base = cp.t_base()
    starts = cp.month_starts(length)
    months = []
    for index, m in enumerate(starts):
        in_window = index >= length - 12
        pass_through = in_window and (index - (length - 12)) < passing
        months.append(
            TurnoverMonth(m, 5_000_000, int(5_000_000 * (share if pass_through else D("0.85"))), 12)
        )
    snap = replace(
        base.snapshot,
        turnover=TurnoverData(cp.ok("abs-turnover"), tuple(months)),
        financials=FinancialsData(),
    )
    return replace(base, snapshot=snap)


@pytest.mark.parametrize(("passing", "flag"), [(0, False), (8, False), (9, True), (12, True)])
def test_transit_nine_of_twelve_months(passing: int, flag: bool) -> None:
    inp = transit_input(passing)
    assert ("TRANSIT" in rules_of(inp, "TURNOVER_ANOMALY")) is flag
    assert compute_features(inp).transit_months == passing


@pytest.mark.parametrize(
    ("outgoing", "flag"), [(984_999, False), (985_000, True), (985_001, True), (1_000_000, True)]
)
def test_transit_share_boundary_is_inclusive(outgoing: int, flag: bool) -> None:
    months = tuple(TurnoverMonth(m, 1_000_000, outgoing, 12) for m in cp.month_starts(12))
    base = series_input([1_000_000] * 12)
    inp = cp.with_snapshot(
        base, turnover=TurnoverData(cp.ok("abs-turnover"), months), financials=FinancialsData()
    )
    assert ("TRANSIT" in rules_of(inp, "TURNOVER_ANOMALY")) is flag


def test_transit_looks_only_at_the_last_twelve_months() -> None:
    inp = transit_input(0, length=24)
    months = list(inp.snapshot.turnover.months)
    months[:12] = [replace(m, outgoing_rub=m.incoming_net_rub) for m in months[:12]]
    old_transit = cp.with_snapshot(inp, turnover=TurnoverData(cp.ok("abs-turnover"), tuple(months)))
    assert rules_of(old_transit, "TURNOVER_ANOMALY") == []


def test_transit_needs_twelve_months_and_ignores_empty_months() -> None:
    assert rules_of(transit_input(12, length=11), "TURNOVER_ANOMALY") == []
    zero = tuple(TurnoverMonth(m, 0, 0, 0) for m in cp.month_starts(12))
    inp = cp.with_snapshot(series_input([1] * 12), turnover=TurnoverData(cp.ok("a"), zero))
    assert compute_features(inp).transit_months == 0


def test_trade_with_five_percent_margin_and_vat_is_not_transit() -> None:
    """Снабконтракт (оптовая торговля, НДС): списания 94% поступлений с НДС, транзита нет."""
    assert compute_features(cp.snabkontrakt()).transit_months == 0


# ---------------------------------------------------------------- TURNOVER_ANOMALY: один плательщик


@pytest.mark.parametrize(
    ("payers", "income", "flag"),
    [
        (2, 3_000_000, True),  # ровно на обоих порогах
        (1, 5_000_000, True),
        (3, 5_000_000, False),  # на одного больше
        (2, 2_999_999, False),  # на рубль меньше
    ],
)
def test_single_payer_boundaries(payers: int, income: int, flag: bool) -> None:
    inp = series_input([income] * 12, payers=payers)
    assert ("SINGLE_PAYER" in rules_of(inp, "TURNOVER_ANOMALY")) is flag


def test_single_payer_needs_every_one_of_the_last_six_months_to_fit() -> None:
    inp = series_input([4_000_000] * 12, payers=2)
    months = list(inp.snapshot.turnover.months)
    months[-3] = replace(months[-3], counterparties_in=5)
    broken = cp.with_snapshot(inp, turnover=TurnoverData(cp.ok("abs"), tuple(months)))
    assert rules_of(broken, "TURNOVER_ANOMALY") == []
    months[-3] = replace(months[-3], counterparties_in=None)  # контрагентов не знаем
    unknown = cp.with_snapshot(inp, turnover=TurnoverData(cp.ok("abs"), tuple(months)))
    assert rules_of(unknown, "TURNOVER_ANOMALY") == []


def test_single_payer_works_on_six_months_but_not_on_five() -> None:
    assert rules_of(series_input([4_000_000] * 6, payers=2), "TURNOVER_ANOMALY") == ["SINGLE_PAYER"]
    assert rules_of(series_input([4_000_000] * 5, payers=2), "TURNOVER_ANOMALY") == []


@pytest.mark.parametrize(
    ("okved", "flag"),
    [
        ("56.10", False),  # кофейня Соколовой: эквайринг и СБП
        ("47.11", False),
        ("55.10", False),
        ("96.02", False),
        ("62.01", True),
        ("46.46", True),
        ("25.62", True),
        ("", True),
    ],
)
def test_single_payer_exempt_industries(okved: str, flag: bool) -> None:
    inp = series_input([4_000_000] * 12, payers=2, okved=okved)
    assert ("SINGLE_PAYER" in rules_of(inp, "TURNOVER_ANOMALY")) is flag


def test_sokolova_coffee_shop_scaled_up_still_has_no_single_payer_flag() -> None:
    """Кофейня с оборотами выше 3 млн и двумя «плательщиками» (эквайринг, СБП): ОКВЭД 56 исключён."""
    inp = cp.sokolova()
    big = tuple(
        replace(m, incoming_net_rub=4_000_000, outgoing_rub=3_400_000)
        for m in inp.snapshot.turnover.months
    )
    scaled = cp.with_snapshot(inp, turnover=TurnoverData(cp.ok("abs"), big))
    assert "SINGLE_PAYER" not in rules_of(scaled, "TURNOVER_ANOMALY")
    as_it = cp.with_snapshot(scaled, registry=replace(scaled.snapshot.registry, okved_main="62.01"))
    assert "SINGLE_PAYER" in rules_of(as_it, "TURNOVER_ANOMALY")


def test_statement_has_no_counterparties_so_single_payer_is_silent_on_it() -> None:
    inp = cp.garipov(second_pass=True)
    big = tuple(TurnoverMonth(m, 4_000_000, 3_400_000) for m in cp.month_starts(12))
    statement = replace(inp.snapshot.statement, months=big)
    features = compute_features(cp.with_snapshot(inp, statement=statement))
    assert features.payers_in_6m_max is None


def test_single_payer_switch_off() -> None:
    inp = series_input([4_000_000] * 12, payers=2)
    off = with_policy(inp, "flags", "turnover_anomaly", "single_payer", "enabled", value=False)
    assert rules_of(off, "TURNOVER_ANOMALY") == []


def test_several_anomaly_rules_give_one_reason_each_with_details() -> None:
    base = series_input([5_000_000] * 9 + [9_000_000] * 3, out_share=PASS_THROUGH, payers=1)
    reasons = [r for r in flags_of(base) if r.code == "TURNOVER_ANOMALY"]
    assert [r.params["rule"] for r in reasons] == ["PUMP", "TRANSIT", "SINGLE_PAYER"]
    assert all(r.params["details"] for r in reasons)
    explanations = decide(base).explanations
    texts = [e.underwriter for e in explanations if e.code == "TURNOVER_ANOMALY"]
    assert any("накачка" in t and "×1,8" in t and "10,79" in t for t in texts)
    assert any("98,5%" in t and "12 из 12" in t for t in texts)


# ---------------------------------------------------------------- приоритеты и маршрут


def test_a_flag_never_rejects_and_never_approves_the_best_client() -> None:
    inp = cp.with_snapshot(cp.t_base(), tax=replace(cp.t_base().snapshot.tax, mass_address=True))
    result = decide(inp)
    assert result.outcome == Outcome.MANUAL_REVIEW
    assert result.reason_codes == ("MASS_REGISTRATION",)
    assert result.recommendation is not None
    assert result.recommendation.outcome == Outcome.APPROVED


def test_stop_factor_beats_flags() -> None:
    base = cp.t_aml()
    flagged = cp.with_snapshot(base, tax=replace(base.snapshot.tax, mass_address=True))
    assert decide(flagged).reason_codes == ("AML_LIST",)


def test_needs_info_beats_flags() -> None:
    inp = cp.garipov(second_pass=False)
    flagged = cp.with_snapshot(inp, tax=replace(inp.snapshot.tax, mass_address=True))
    result = decide(flagged)
    assert result.outcome == Outcome.NEEDS_INFO
    assert "MASS_REGISTRATION" not in result.reason_codes


def test_flags_are_listed_before_route_reasons_and_after_stops() -> None:
    inp = cp.t_overdue_45()
    tax = replace(inp.snapshot.tax, mass_address=True)
    result = decide(cp.with_snapshot(inp, tax=tax))
    assert result.reason_codes == ("MASS_REGISTRATION", "OVERDUE_30_89", "GRADE_NEEDS_REVIEW")


def test_flags_do_not_change_the_numbers_of_the_decision() -> None:
    plain = decide(cp.t_base())
    flagged = decide(
        cp.with_snapshot(cp.t_base(), tax=replace(cp.t_base().snapshot.tax, mass_address=True))
    )
    assert flagged.numbers == plain.numbers


def test_unavailable_source_and_a_flag_come_together_for_the_underwriter() -> None:
    inp = cp.t_base()
    gone = ComplianceData(SourceMeta(SourceStatus.UNAVAILABLE))
    snap = replace(inp.snapshot, compliance=gone, tax=replace(inp.snapshot.tax, mass_director=True))
    result = decide(replace(inp, snapshot=snap))
    assert result.reason_codes == ("MASS_REGISTRATION", "SOURCE_UNAVAILABLE")


# ---------------------------------------------------------------- BUSINESS_TOO_YOUNG (T-290)


def young(registered: date, *, guarantor: bool = False) -> DecisionInput:
    base = cp.quick_start(with_guarantor=guarantor)
    return cp.with_snapshot(
        base, registry=replace(base.snapshot.registry, registration_date=registered)
    )


@pytest.mark.parametrize(
    ("registered", "is_young"),
    [
        (date(2026, 4, 20), False),  # 6 мес. и 1 день
        (date(2026, 4, 21), False),  # ровно 6 полных месяцев — уже не «моложе 6»
        (date(2026, 4, 22), True),  # 5 мес. 30 дн.
        (date(2026, 7, 21), True),  # quick-start: 3 мес.
    ],
)
def test_business_too_young_boundary_is_six_full_months(registered: date, is_young: bool) -> None:
    result = decide(young(registered))
    assert ("BUSINESS_TOO_YOUNG" in result.reason_codes) is is_young
    conditional = [v for v in result.variants if v.kind == "CONDITIONAL_SECURITY"]
    if is_young:
        assert result.outcome == Outcome.COUNTER_OFFER  # без обеспечения — условное встречное
        assert len(conditional) == 1
    else:
        assert conditional == []  # обеспечение требовать не из-за чего


def test_young_without_security_never_gets_approved_and_the_offer_is_conditional() -> None:
    result = decide(cp.quick_start())
    assert result.outcome == Outcome.COUNTER_OFFER
    (variant,) = result.variants
    assert variant.security_required


def test_flag_beats_the_conditional_counter_offer_for_a_young_business() -> None:
    base = cp.quick_start()
    tax = replace(base.snapshot.tax, mass_address=True)
    result = decide(cp.with_snapshot(base, tax=tax))
    assert result.outcome == Outcome.MANUAL_REVIEW
    assert result.variants == ()
    assert result.reason_codes[:2] == ("MASS_REGISTRATION", "BUSINESS_TOO_YOUNG")


def test_stop_beats_the_conditional_counter_offer_for_a_young_business() -> None:
    base = cp.quick_start()
    results = (
        replace(base.snapshot.compliance.results[0], aml_listed=True),
        *base.snapshot.compliance.results[1:],
    )
    listed = replace(base.snapshot.compliance, results=results)
    result = decide(cp.with_snapshot(base, compliance=listed))
    assert result.outcome == Outcome.REJECTED
    assert result.reason_codes == ("AML_LIST",)


def test_young_with_security_goes_to_a_human_even_without_any_flag() -> None:
    result = decide(cp.quick_start(with_guarantor=True))
    assert result.outcome == Outcome.MANUAL_REVIEW
    assert result.reason_codes[0] == "BUSINESS_TOO_YOUNG"
