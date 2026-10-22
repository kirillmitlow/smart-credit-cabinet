"""Признаки шага 6 (T-285, T-286, T-287, 30-02): выручка, поток, БКИ, налоги, тренд, шок.

Нет данных ≠ ноль: у признака `None` или осторожное значение, прописанное в 30-02.
Доли (тренд, CV, шок) — `Decimal`-доли, не проценты: 0,082 = +8,2%.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from app.modules.decisioning.dates import add_months, full_months_between
from app.modules.decisioning.loan_math import to_rub
from app.modules.decisioning.policy import Policy, PumpRule, SinglePayerRule, TransitRule
from app.modules.decisioning.types import (
    BkiReport,
    BkiSubject,
    Comparison,
    DecisionInput,
    Features,
    FinancialYear,
    PumpStat,
    Quality,
    Snapshot,
    SourceStatus,
    SubjectRole,
    TaxData,
    TurnoverMonth,
)

_CTX = Context(prec=40, rounding=ROUND_HALF_UP)
_ZERO = Decimal(0)
_ONE = Decimal(1)

# ---------------------------------------------------------------- статистика на Decimal


def mean(values: Sequence[Decimal]) -> Decimal:
    with localcontext(_CTX):
        return sum(values, _ZERO) / len(values)


def median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    with localcontext(_CTX):
        return (ordered[mid - 1] + ordered[mid]) / 2


def pstdev(values: Sequence[Decimal]) -> Decimal:
    with localcontext(_CTX):
        m = mean(values)
        variance = sum(((v - m) ** 2 for v in values), _ZERO) / len(values)
        return variance.sqrt()


def pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    """Корреляция Пирсона; `None`, если у одного из рядов нет разброса."""
    with localcontext(_CTX):
        mx, my = mean(xs), mean(ys)
        sxx = sum(((x - mx) ** 2 for x in xs), _ZERO)
        syy = sum(((y - my) ** 2 for y in ys), _ZERO)
        if sxx == 0 or syy == 0:
            return None
        sxy = sum(((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)), _ZERO)
        return sxy / (sxx * syy).sqrt()


def theil_sen_slope(values: Sequence[Decimal]) -> Decimal:
    """Медиана наклонов по всем парам точек (устойчива к одному выбросу)."""
    slopes: list[Decimal] = []
    with localcontext(_CTX):
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                slopes.append((values[j] - values[i]) / (j - i))
    return median(slopes)


# ---------------------------------------------------------------- НДС, отрасль, ФИО


def vat_rate(policy: Policy, month: date) -> Decimal:
    """Ставка НДС на месяц (30-18 №7): последняя строка расписания с `since <= month`."""
    rate = _ZERO
    for row in sorted(policy.features.vat.schedule, key=lambda r: r.since):
        if row.since <= month:
            rate = row.rate
    return rate


def industry_group(okved: str, policy: Policy) -> str:
    digits = re.match(r"^\d{2}", okved)
    if digits is None:
        return policy.features.industry.default_group
    prefix = int(digits.group())
    for rng in policy.features.industry.ranges:
        if rng.from_prefix <= prefix <= rng.to_prefix:
            return rng.group
    return policy.features.industry.default_group


def normalize_name(name: str) -> tuple[str, ...]:
    """ФИО → слова в нижнем регистре: ё=е, без точек и лишних пробелов."""
    cleaned = re.sub(r"[.,]", " ", name.casefold().replace("ё", "е"))
    return tuple(cleaned.split())


def names_match(form_name: str, registry_name: str) -> bool:
    """«Иванов И. И.» = «Иванов Иван Иванович»: фамилия целиком, имя и отчество — по инициалам."""
    a, b = normalize_name(form_name), normalize_name(registry_name)
    if not a or not b or a[0] != b[0]:
        return False
    rest_a, rest_b = a[1:], b[1:]
    # Инициалы могут быть слитно: «и.и.» после очистки даёт два слова, «ии» — одно
    if len(rest_a) == 1 and len(rest_a[0]) == len(rest_b) and len(rest_a[0]) <= 2:
        rest_a = tuple(rest_a[0])
    if len(rest_b) == 1 and len(rest_b[0]) == len(rest_a) and len(rest_b[0]) <= 2:
        rest_b = tuple(rest_b[0])
    if len(rest_a) != len(rest_b):
        return False
    for x, y in zip(rest_a, rest_b, strict=True):
        if x == y:
            continue
        if (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)):
            continue
        return False
    return True


# ---------------------------------------------------------------- ряды оборотов


def net_series(months: Sequence[TurnoverMonth], osno: bool, policy: Policy) -> tuple[Decimal, ...]:
    """Помесячные поступления без НДС; ставка берётся по дате месяца, не по дате заявки."""
    out: list[Decimal] = []
    with localcontext(_CTX):
        for m in months:
            gross = Decimal(m.incoming_net_rub)
            out.append(gross / (_ONE + vat_rate(policy, m.month)) if osno else gross)
    return tuple(out)


def _is_osno(tax: TaxData, policy: Policy) -> bool:
    return policy.features.vat.regime_code in tax.regimes


def _is_seasonal(series: Sequence[Decimal], okved: str, policy: Policy) -> bool:
    cfg = policy.features.seasonality
    if len(series) >= cfg.min_months:
        last = list(series[-cfg.min_months :])
        half = cfg.min_months // 2
        corr = pearson(last[:half], last[half:])
        cv = _cv(series)
        return (
            corr is not None and cv is not None and corr >= cfg.min_correlation and cv >= cfg.min_cv
        )
    return any(okved.startswith(p) for p in cfg.okved_prefixes)


def _cv(series: Sequence[Decimal]) -> Decimal | None:
    """Коэффициент вариации последних 12 месяцев (стандартное отклонение генеральной совокупности)."""
    if len(series) < 6:
        return None
    window = list(series[-12:])
    m = mean(window)
    if m == 0:
        return None
    with localcontext(_CTX):
        return pstdev(window) / m


def _trend(
    series: Sequence[Decimal], seasonal: bool, years: Sequence[tuple[int, int]], policy: Policy
) -> Decimal | None:
    cfg = policy.features.trend
    with localcontext(_CTX):
        if seasonal or len(series) >= 24:
            if len(series) >= 24:
                recent = sum(series[-12:], _ZERO)
                previous = sum(series[-24:-12], _ZERO)
                return recent / previous - _ONE if previous > 0 else None
        elif len(series) >= cfg.min_points:
            window = list(series[-cfg.max_points :])
            med = median(window)
            if med <= 0:
                return None
            return 12 * theil_sen_slope(window) / med
        # Ряда нет (или он короткий), но есть два года отчётности: 2110 / предыдущий − 1
        if len(years) >= 2 and years[1][1] > 0:
            return Decimal(years[0][1]) / Decimal(years[1][1]) - _ONE
    return None


# ---------------------------------------------------------------- БКИ


def _subject_class(report: BkiReport, policy: Policy) -> str:
    hist = policy.features.history
    min_rub = policy.features.debt.overdue_min_rub
    if not report.has_history:
        return "NO_HISTORY"
    current = report.current_overdue_days if report.current_overdue_rub >= min_rub else 0
    if current >= 90:
        return "PAST_90"
    if current >= 30:
        return "CURRENT_30_89"
    worst = max(report.max_overdue_days_24m, current)
    if worst >= 90:
        return "PAST_90"
    if worst >= 60:
        return "PAST_60"
    if worst >= 30:
        return "PAST_30"
    obligations = report.active_obligations + report.closed_obligations
    thin = (
        obligations < hist.thin_min_obligations
        or report.history_months < hist.clean_min_history_months
    )
    if worst >= 1:
        # Малая просрочка на тонкой истории не лучше тонкой чистой (иначе INV-03: просрочка
        # «повышала» бы баллы, MINOR 18 > THIN_CLEAN 16 в 30-07)
        return "THIN_CLEAN" if thin else "MINOR"
    return "THIN_CLEAN" if thin else "CLEAN"


def history_class(subjects: Sequence[BkiSubject], policy: Policy) -> str:
    """Худший класс по всем оценённым субъектам; у компании без истории не выше `THIN_CLEAN`."""
    classes: dict[SubjectRole, str] = {}
    for s in subjects:
        if s.meta.status == SourceStatus.OK and s.report is not None:
            classes[s.role] = _subject_class(s.report, policy)
        elif s.meta.status == SourceStatus.NOT_FOUND:
            classes[s.role] = "NO_HISTORY"
    if not classes:
        return "NO_HISTORY"
    others_have_history = any(
        c != "NO_HISTORY" for r, c in classes.items() if r != SubjectRole.COMPANY
    )
    if classes.get(SubjectRole.COMPANY) == "NO_HISTORY" and others_have_history:
        classes[SubjectRole.COMPANY] = "THIN_CLEAN"
    points = policy.scorecard.credit_history.points
    return min(classes.values(), key=lambda c: (points[c], c))


def _bki_reports(snapshot: Snapshot) -> list[tuple[BkiSubject, BkiReport]]:
    return [
        (s, s.report)
        for s in snapshot.bki
        if s.meta.status == SourceStatus.OK and s.report is not None
    ]


# ---------------------------------------------------------------- сверка и антифрод (T-288)

_MONTHS_IN_YEAR = 12


def compare_with_financials(
    months: Sequence[TurnoverMonth], series: Sequence[Decimal], years: Sequence[FinancialYear]
) -> Comparison | None:
    """Обороты календарного года без НДС против строки 2110 за тот же год (30-02).

    Берётся только год, у которого в окне оборотов есть все 12 месяцев. Если таких лет несколько,
    остаётся год с наибольшим расхождением. Знаменатель — отчётность, чтобы +40% и −40% ловились
    одинаково.
    """
    by_month = {m.month: v for m, v in zip(months, series, strict=True)}
    best: Comparison | None = None
    for fy in years:
        keys = [date(fy.year, n, 1) for n in range(1, _MONTHS_IN_YEAR + 1)]
        if fy.revenue_rub <= 0 or any(k not in by_month for k in keys):
            continue
        with localcontext(_CTX):
            total = sum((by_month[k] for k in keys), _ZERO)
            deviation = abs(total - fy.revenue_rub) / fy.revenue_rub
        if best is None or deviation > best.deviation:
            best = Comparison(to_rub(total), fy.revenue_rub, deviation, fy.year)
    return best


def compare_declared(declared_rub: int | None, calculated_rub: int | None) -> Comparison | None:
    """Заявленная выручка в месяц против осторожной расчётной; знаменатель — расчётная (30-02).

    Не заявлено (нет значения или оно не положительное) или расчётной нет — проверки нет.
    """
    if declared_rub is None or declared_rub <= 0 or not calculated_rub:
        return None
    with localcontext(_CTX):
        deviation = abs(Decimal(declared_rub) - calculated_rub) / calculated_rub
    return Comparison(declared_rub, calculated_rub, deviation)


def _pump_window(
    series: Sequence[Decimal], cfg: PumpRule
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """`x`, `b`, `x / b` и модифицированный z для окна, которым заканчивается `series`."""
    need = cfg.recent_months + cfg.base_months
    if len(series) < need:
        return None
    base = list(series[-need : -cfg.recent_months])
    recent = list(series[-cfg.recent_months :])
    b = median(base)
    if b <= 0:
        return None
    x = mean(recent)
    with localcontext(_CTX):
        mad = median([abs(v - b) for v in base])
        if mad == 0:
            mad = b * cfg.mad_fallback_share
        return x, b, x / b, cfg.modified_z_constant * (x - b) / mad


def pump_stat(series: Sequence[Decimal], cfg: PumpRule) -> PumpStat | None:
    """Накачка: среднее последних месяцев против медианы базы (30-02, D-076).

    Для ряда не короче `seasonal_min_months` считается и то же окно годом ранее: это отношение
    «своё к своей базе», а не к текущему уровню. Буквальное `x / x_год_назад` подавило бы настоящую
    накачку (9 / 5 = 1,8, `t-anomaly`), потому что любой рост за год выглядел бы повтором сезона.
    """
    now = _pump_window(series, cfg)
    if now is None:
        return None
    x, b, ratio, modified_z = now
    prior: Decimal | None = None
    if len(series) >= cfg.seasonal_min_months:
        ago = _pump_window(series[:-_MONTHS_IN_YEAR], cfg)
        prior = ago[2] if ago is not None else None
    return PumpStat(to_rub(x), to_rub(b), ratio, modified_z, prior)


def transit_months(months: Sequence[TurnoverMonth], cfg: TransitRule) -> int | None:
    """Месяцев окна, где списания не меньше доли поступлений (с НДС, как они на счёте)."""
    if len(months) < cfg.window_months:
        return None
    return sum(
        1
        for m in months[-cfg.window_months :]
        if m.incoming_net_rub > 0 and m.outgoing_rub >= cfg.min_outgoing_share * m.incoming_net_rub
    )


def payers_window(months: Sequence[TurnoverMonth], cfg: SinglePayerRule) -> tuple[int, int] | None:
    """Максимум контрагентов-плательщиков и средние поступления за окно; `None`, если данных нет.

    У выписки клиента число контрагентов неизвестно: правило на ней не работает.
    """
    if len(months) < cfg.window_months:
        return None
    window = months[-cfg.window_months :]
    counts = [m.counterparties_in for m in window if m.counterparties_in is not None]
    if len(counts) != len(window):
        return None
    average = mean([Decimal(m.incoming_net_rub) for m in window])
    return max(counts), to_rub(average)


# ---------------------------------------------------------------- главная функция


def _fresh_financials(snapshot: Snapshot, today: date, policy: Policy) -> bool:
    fin = snapshot.financials
    if fin.meta.status != SourceStatus.OK or not fin.years:
        return False
    latest = max(y.year for y in fin.years)
    deadline = add_months(date(latest, 12, 31), policy.features.revenue.fresh_financials_months)
    return deadline >= today


def compute_features(inp: DecisionInput) -> Features:  # noqa: PLR0914 — один проход по признакам
    policy = inp.policy
    snap = inp.snapshot
    app = inp.application
    today = inp.context.app_today
    cfg = policy.features
    cfg_flags = policy.flags
    reg = snap.registry
    okved = reg.okved_main

    osno = _is_osno(snap.tax, policy) if snap.tax.meta.status == SourceStatus.OK else False
    bank_months = snap.turnover.months if snap.turnover.meta.status == SourceStatus.OK else ()
    # Выписка чужого владельца (ИНН в файле не совпал) не источник выручки
    statement_usable = (
        snap.statement.meta.status == SourceStatus.OK and snap.statement.owner_inn_matches
    )
    stmt_months = snap.statement.months if statement_usable else ()
    bank_months = bank_months[-24:]
    stmt_months = stmt_months[-24:]
    fin_years = (
        sorted(snap.financials.years, key=lambda y: -y.year)
        if snap.financials.meta.status == SourceStatus.OK
        else []
    )
    fresh_fin = _fresh_financials(snap, today, policy)
    latest_fin = fin_years[0] if fin_years else None

    # --- источник выручки по приоритету (30-02)
    source: str | None
    quality: Quality | None
    used: Sequence[TurnoverMonth] = ()
    if len(bank_months) >= cfg.revenue.short_history_months:
        source, quality, used = "OWN_BANK", Quality.OWN_BANK, bank_months
    elif fresh_fin:
        source, quality, used = "OFFICIAL", Quality.OFFICIAL, bank_months
    elif stmt_months:
        source, quality, used = "CLIENT_UPLOAD", Quality.CLIENT_UPLOAD, stmt_months
    elif bank_months:
        source, quality, used = "OWN_BANK", Quality.OWN_BANK, bank_months
    else:
        source, quality = None, None

    series = net_series(used, osno, policy) if used else ()
    seasonal = _is_seasonal(series, okved, policy)
    cv = _cv(series)
    shock = cfg.stress.shock_min
    if cv is not None and not seasonal:
        shock = max(cfg.stress.shock_min, min(cfg.stress.shock_max, cv))
    trend = _trend(series, seasonal, [(y.year, y.revenue_rub) for y in fin_years], policy)
    bad = None
    if len(series) >= 6:
        window = list(series[-12:])
        med = median(window)
        bad = sum(1 for v in window if v < med * cfg.bad_month.share_of_median)

    # --- осторожная выручка
    revenue: int | None = None
    with localcontext(_CTX):
        if source == "OFFICIAL" and latest_fin is not None:
            revenue = to_rub(Decimal(latest_fin.revenue_rub) / 12)
        elif series:
            n = len(series)
            if n < cfg.revenue.short_history_months:
                revenue = to_rub(mean(series) * cfg.revenue.short_history_factor)
            elif seasonal:
                revenue = to_rub(sum(series[-12:], _ZERO) / min(12, n))
            else:
                long_avg = mean(series[-cfg.revenue.window_long_months :])
                short_avg = mean(series[-cfg.revenue.window_short_months :])
                revenue = to_rub(min(long_avg, short_avg))
    annual = revenue * 12 if revenue is not None else None

    # --- свободный поток
    flow: int | None = None
    flow_quality: Quality | None = None
    group = industry_group(okved, policy)
    if revenue is not None:
        with localcontext(_CTX):
            if fresh_fin and latest_fin is not None:
                base = Decimal(latest_fin.net_profit_rub + latest_fin.interest_paid_rub) / 12
                factor = _ONE
                if latest_fin.revenue_rub > 0:
                    factor = min(_ONE, Decimal(revenue) / (Decimal(latest_fin.revenue_rub) / 12))
                flow = max(0, to_rub(base * factor))
                flow_quality = Quality.OFFICIAL
            else:
                flow = max(0, to_rub(Decimal(revenue) * cfg.industry.margins[group]))
                flow_quality = Quality.ESTIMATE

    # --- долги и платежи (заёмщик — компания или ИП; личные долги директора не входят)
    reports = _bki_reports(snap)
    company_reports = [r for s, r in reports if s.role == SubjectRole.COMPANY]
    company_report = company_reports[0] if company_reports else None
    bki_known = any(
        s.role == SubjectRole.COMPANY and s.meta.status in (SourceStatus.OK, SourceStatus.NOT_FOUND)
        for s in snap.bki
    )
    bki_uids = {o.uid for o in company_report.obligations} if company_report else set()
    our_extra = [loan for loan in snap.customer.our_loans if loan.contract_uid not in bki_uids]
    existing = (company_report.monthly_payments_rub if company_report else 0) + sum(
        loan.monthly_payment_rub for loan in our_extra
    )
    with localcontext(_CTX):
        contingent = (
            Decimal(company_report.contingent_liabilities_rub) * cfg.debt.contingent_weight
            if company_report
            else _ZERO
        )
    total_debt = (
        (company_report.total_debt_rub if company_report else 0)
        + sum(loan.balance_rub for loan in our_extra)
        + to_rub(contingent)
    )
    debt_to_revenue: Decimal | None = None
    if bki_known and annual:
        with localcontext(_CTX):
            debt_to_revenue = Decimal(total_debt) / Decimal(annual)
    coverage: Decimal | None = None
    if flow is not None and existing > 0:
        with localcontext(_CTX):
            coverage = Decimal(flow) / Decimal(existing)

    inflow_average = to_rub(mean(series[-12:])) if series else None

    # --- сверка потока по счёту (для флагов T-288; здесь только расчёт)
    observed: int | None = None
    crosscheck: Decimal | None = None
    if used:
        window_months = list(used[-12:])
        with localcontext(_CTX):
            gap = mean([Decimal(m.incoming_net_rub - m.outgoing_rub) for m in window_months])
            observed = to_rub(gap + existing)
            if flow:
                crosscheck = Decimal(observed) / Decimal(flow)

    # --- сверка и антифрод (T-288): только расчёт признаков, флаги ставит `flags.py`
    tax_ok = snap.tax if snap.tax.meta.status == SourceStatus.OK else None
    anomaly = cfg_flags.turnover_anomaly
    bank_series = net_series(bank_months, osno, policy) if bank_months else ()
    stmt_series = net_series(stmt_months, osno, policy) if stmt_months else ()
    mismatch_fin = (
        compare_with_financials(bank_months, bank_series, fin_years) if bank_months else None
    )
    mismatch_statement = (
        compare_with_financials(stmt_months, stmt_series, fin_years) if stmt_months else None
    )
    payers = payers_window(used, anomaly.single_payer) if used else None

    # --- БКИ по всем субъектам
    all_reports = [r for _, r in reports]
    max_overdue = max((r.max_overdue_days_24m for r in all_reports), default=0)
    current_max = max(
        (
            r.current_overdue_days
            for r in all_reports
            if r.current_overdue_rub >= cfg.debt.overdue_min_rub
        ),
        default=0,
    )
    restructurings = sum(r.restructurings_24m for r in all_reports)
    inquiries = max((r.inquiries_30d_excl_own for r in all_reports), default=0)
    rejected = max((r.rejected_90d_excl_own for r in all_reports), default=0)

    # --- налоги
    tax = snap.tax
    tax_known = tax.meta.status == SourceStatus.OK
    tax_ratio: Decimal | None = None
    if tax_known and revenue:
        with localcontext(_CTX):
            tax_ratio = Decimal(tax.tax_debt_rub) / Decimal(revenue)

    # --- компания, клиент банка, заявка
    age = (
        full_months_between(reg.registration_date, today)
        if reg.registration_date is not None
        else None
    )
    cust = snap.customer
    tenure = (
        full_months_between(cust.customer_since, today)
        if cust.is_customer and cust.customer_since is not None
        else None
    )
    collateral = app.collateral is not None and app.collateral.value_rub > 0
    guarantor = app.guarantor is not None and app.guarantor.consent_signed
    matches = True
    if app.director_name_in_form and reg.director_name:
        matches = names_match(app.director_name_in_form, reg.director_name)

    return Features(
        business_age_months=age,
        is_bank_customer=cust.is_customer,
        customer_tenure_months=tenure,
        industry_group=group,
        revenue_source=source,
        revenue_quality=quality,
        revenue_months=len(used),
        revenue_cautious_rub=revenue,
        revenue_annual_rub=annual,
        flow_model_rub=flow,
        flow_quality=flow_quality,
        flow_observed_rub=observed,
        inflow_average_rub=inflow_average,
        flow_crosscheck_ratio=crosscheck,
        existing_payments_rub=existing,
        total_debt_rub=total_debt,
        debt_to_revenue=debt_to_revenue,
        coverage_existing=coverage,
        revenue_trend_pct=trend,
        revenue_cv=cv,
        bad_months=bad,
        is_seasonal=seasonal,
        stress_shock=shock,
        credit_history_class=history_class(snap.bki, policy),
        max_overdue_24m_days=max(max_overdue, current_max),
        restructurings_24m=restructurings,
        inquiries_30d=inquiries,
        rejected_90d=rejected,
        bki_known=bki_known,
        tax_debt_rub=tax.tax_debt_rub if tax_known else 0,
        tax_penalties_rub=tax.penalties_rub if tax_known else 0,
        tax_debt_ratio=tax_ratio,
        tax_offenses=tax.offenses_count if tax_known else 0,
        account_block_active=tax.account_block_active if tax_known else False,
        tax_known=tax_known,
        net_profit_rub=latest_fin.net_profit_rub if latest_fin else None,
        interest_paid_rub=latest_fin.interest_paid_rub if latest_fin else None,
        collateral_provided=collateral,
        guarantor_confirmed=guarantor,
        security_confirmed=collateral or guarantor,
        form_matches_registry=matches,
        mismatch_turnover_fin=mismatch_fin,
        mismatch_declared=compare_declared(app.declared_monthly_revenue_rub, revenue),
        mismatch_statement=mismatch_statement,
        pump=pump_stat(series, anomaly.pump) if series else None,
        transit_months=transit_months(used, anomaly.transit) if used else None,
        payers_in_6m_max=payers[0] if payers is not None else None,
        payers_in_6m_avg_income_rub=payers[1] if payers is not None else None,
        risk_mass_address=tax_ok.mass_address if tax_ok is not None else False,
        risk_mass_director=tax_ok.mass_director if tax_ok is not None else False,
        risk_mass_founder=tax_ok.mass_founder if tax_ok is not None else False,
    )
