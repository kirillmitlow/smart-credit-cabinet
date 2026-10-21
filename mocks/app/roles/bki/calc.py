"""Значения БКИ, которые считаются при чтении (разделы 2.5, 6.1, 6.4). Без HTTP и базы.

В базе лежат даты и периоды просрочки, а числа «на сегодня» (дни просрочки, корзины истории
платежей, summary) считаются здесь при каждом запросе. Модуль переиспользует валидатор
согласованности сценариев (T-126), поэтому зависит только от стандартной библиотеки.

Правила, принятые там, где спецификация молчит:
- день просрочки отсчитывается от `since`: на саму дату `since` просрочка 0 дней (18.07 → 18.10 = 92);
- период `[since, until)`: в день `until` платёж внесён, просрочки уже нет, а пик периода
  равен `until - since` (закрытый период длиной N дней даёт `maxOverdueDays24m = N`);
- окна «30 дней» и «90 дней» включают границу: `today - 30 дн ≤ дата ≤ today`.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

LIMIT_KINDS = frozenset({"CREDIT_LINE", "OVERDRAFT", "CREDIT_CARD"})
CONTINGENT_KINDS = frozenset({"GUARANTEE", "SURETY"})
GUARANTOR_ROLE = "GUARANTOR"

HISTORY_MONTHS = 24
INQUIRY_WINDOW_DAYS = 30
REJECTION_WINDOW_DAYS = 90

# Нижняя граница дней просрочки → корзина (шкала своевременности платежей в форматах БКИ)
_BUCKETS: tuple[tuple[int, str], ...] = (
    (120, "D120_PLUS"),
    (90, "D90_119"),
    (60, "D60_89"),
    (30, "D30_59"),
    (1, "D1_29"),
)


@dataclass(frozen=True)
class Period:
    since: date
    until: date | None = None  # None — просрочка продолжается


@dataclass(frozen=True)
class ObligationFacts:
    kind: str
    role: str
    status: str
    opened_at: date
    closed_at: date | None
    balance_rub: int
    monthly_payment_rub: int | None
    overdue_rub: int
    periods: Sequence[Period]


@dataclass(frozen=True)
class InquiryFacts:
    day: date
    is_own: bool


@dataclass(frozen=True)
class ApplicationFacts:
    applied_at: date
    decided_at: date | None
    decision: str
    is_own: bool


@dataclass(frozen=True)
class Summary:
    active_obligations: int
    closed_obligations: int
    total_debt_rub: int
    monthly_payments_rub: int
    contingent_liabilities_rub: int
    current_overdue_rub: int
    current_overdue_days: int
    max_overdue_days_24m: int
    restructurings_24m: int
    inquiries_30d: int
    inquiries_30d_excluding_own: int
    rejected_applications_90d: int
    rejected_applications_90d_excluding_own: int
    history_length_months: int


ZERO_SUMMARY = Summary(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def bucket_for_days(days: int) -> str:
    """Корзина по числу дней просрочки: 0 → OK, 1–29 → D1_29, … , 120 и больше → D120_PLUS."""
    for lower, name in _BUCKETS:
        if days >= lower:
            return name
    return "OK"


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def months_between(start: date, end: date) -> int:
    """Полных месяцев от start до end (0, если end раньше start)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _clamped(periods: Iterable[Period], closed_at: date | None) -> list[Period]:
    """Закрытое обязательство просрочки не копит: открытый период кончается днём закрытия."""
    if closed_at is None:
        return list(periods)
    return [
        Period(p.since, closed_at if p.until is None else min(p.until, closed_at)) for p in periods
    ]


def period_days_at(period: Period, day: date) -> int:
    """Дней просрочки по периоду на дату `day`; вне периода 0."""
    if day < period.since or (period.until is not None and day >= period.until):
        return 0
    return (day - period.since).days


def overdue_days_at(periods: Iterable[Period], day: date, closed_at: date | None = None) -> int:
    """Просрочка обязательства на дату: максимум по периодам, которые на неё действуют."""
    return max((period_days_at(p, day) for p in _clamped(periods, closed_at)), default=0)


def _period_peak(period: Period, today: date, window_start: date) -> int:
    end = period.until if period.until is not None and period.until <= today else today
    if period.since > today or end < window_start:
        return 0
    return (end - period.since).days


def max_overdue_days(
    periods: Iterable[Period], today: date, closed_at: date | None = None, months: int = 24
) -> int:
    """Худшая просрочка за последние `months` месяцев."""
    window_start = add_months(today, -months)
    return max(
        (_period_peak(p, today, window_start) for p in _clamped(periods, closed_at)), default=0
    )


def payment_history(
    opened_at: date,
    closed_at: date | None,
    periods: Sequence[Period],
    today: date,
    months: int = HISTORY_MONTHS,
) -> list[tuple[str, str]]:
    """История платежей: (месяц «YYYY-MM», корзина) за последние `months` месяцев.

    Месяцы от открытия до начала просрочки — OK; дальше корзина по дням просрочки на конец месяца
    (для текущего месяца — на «сегодня»). Закрытые периоды дают корзины в прошлом.
    """
    last = min(today, closed_at) if closed_at is not None else today
    result: list[tuple[str, str]] = []
    year, month = opened_at.year, opened_at.month
    while (year, month) <= (last.year, last.month):
        end = min(date(year, month, calendar.monthrange(year, month)[1]), today)
        days = overdue_days_at(periods, end, closed_at)
        result.append((f"{year:04d}-{month:02d}", bucket_for_days(days)))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result[-months:]


def is_contingent(kind: str, role: str) -> bool:
    """Поручительства и гарантии — не долг субъекта, а то, за что он ответит (6.1)."""
    return kind in CONTINGENT_KINDS or role == GUARANTOR_ROLE


def effective_monthly_payment(
    kind: str, stored: int | None, balance_rub: int, limit_percent: float
) -> int | None:
    """Платёж обязательства в отчёте.

    Гарантии и поручительства: null (платит основной должник). Лимитные виды без заданного платежа:
    `limit_percent` % от использованной части. Иначе — платёж по графику, как передан.
    """
    if kind in CONTINGENT_KINDS:
        return None
    if kind in LIMIT_KINDS and stored is None:
        return round(balance_rub * limit_percent / 100)
    return stored


def is_closed(o: ObligationFacts, today: date) -> bool:
    return o.status == "CLOSED" or (o.closed_at is not None and o.closed_at <= today)


def summarize(
    obligations: Sequence[ObligationFacts],
    inquiries: Iterable[InquiryFacts],
    applications: Iterable[ApplicationFacts],
    today: date,
    limit_percent: float,
) -> Summary:
    active = [o for o in obligations if not is_closed(o, today)]
    debt = [o for o in active if not is_contingent(o.kind, o.role)]
    contingent = [o for o in active if is_contingent(o.kind, o.role)]

    window_24m = add_months(today, -24)
    restructured = [
        o
        for o in obligations
        if o.status == "RESTRUCTURED" and (o.closed_at is None or o.closed_at >= window_24m)
    ]

    inq_start = today - timedelta(days=INQUIRY_WINDOW_DAYS)
    inq = [i for i in inquiries if inq_start <= i.day <= today]

    rej_start = today - timedelta(days=REJECTION_WINDOW_DAYS)
    rejected = [
        a
        for a in applications
        if a.decision == "REJECTED" and rej_start <= (a.decided_at or a.applied_at) <= today
    ]

    return Summary(
        active_obligations=len(active),
        closed_obligations=len(obligations) - len(active),
        total_debt_rub=sum(o.balance_rub for o in debt),
        monthly_payments_rub=sum(
            effective_monthly_payment(o.kind, o.monthly_payment_rub, o.balance_rub, limit_percent)
            or 0
            for o in debt
        ),
        contingent_liabilities_rub=sum(o.balance_rub for o in contingent),
        current_overdue_rub=sum(o.overdue_rub for o in active),
        current_overdue_days=max(
            (overdue_days_at(o.periods, today, o.closed_at) for o in active), default=0
        ),
        max_overdue_days_24m=max(
            (max_overdue_days(o.periods, today, o.closed_at) for o in obligations), default=0
        ),
        restructurings_24m=len(restructured),
        inquiries_30d=len(inq),
        inquiries_30d_excluding_own=sum(1 for i in inq if not i.is_own),
        rejected_applications_90d=len(rejected),
        rejected_applications_90d_excluding_own=sum(1 for a in rejected if not a.is_own),
        history_length_months=(
            months_between(min(o.opened_at for o in obligations), today) if obligations else 0
        ),
    )


def bureau_score(summary: Summary, has_bankruptcy: bool) -> int:
    """Иллюстративная оценка бюро 300–850: детерминированная, ядро её не использует."""
    score = (
        720
        - 1.5 * min(summary.current_overdue_days, 180)
        - 0.5 * min(summary.max_overdue_days_24m, 180)
        - 15 * min(summary.inquiries_30d, 6)
        - 20 * min(summary.rejected_applications_90d, 3)
        - (80 if has_bankruptcy else 0)
        + 0.8 * min(summary.history_length_months, 60)
    )
    return max(300, min(850, round(score)))
