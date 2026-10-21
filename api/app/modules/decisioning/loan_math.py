"""Кредитная математика (T-282, T-283, 30-16): чистые функции над `Decimal`.

Договорённости (30-16, раздел 1): деньги — целые рубли, округление «половина вверх»; точность
40 знаков; `float` запрещён; ставка — годовая номинальная, месячная `i = r / 12`. Те же функции
используют ядро, калькулятор, график оферты и имитатор, поэтому «показали одно, проверили другое»
невозможно.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Context, Decimal, localcontext

from app.modules.decisioning.dates import add_months, next_business_day

_CTX = Context(prec=40, rounding=ROUND_HALF_UP)
_ONE = Decimal(1)
_ZERO = Decimal(0)
_TAIL = Decimal("1e-12")


def to_rub(value: Decimal) -> int:
    """Округление до целого рубля, «половина вверх»."""
    with localcontext(_CTX):
        return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def floor_rub(value: Decimal) -> int:
    with localcontext(_CTX):
        return int(value.to_integral_value(rounding=ROUND_FLOOR))


def monthly_rate(annual_rate: Decimal) -> Decimal:
    with localcontext(_CTX):
        return annual_rate / 12


# ---------------------------------------------------------------- аннуитет


def annuity_payment_exact(amount: int, annual_rate: Decimal, term: int) -> Decimal:
    """`PMT = S·i / (1 − (1+i)^(−n))`; при `i = 0` — `S / n`."""
    if term <= 0:
        raise ValueError("срок должен быть положительным")
    with localcontext(_CTX):
        i = annual_rate / 12
        if i == 0:
            return Decimal(amount) / term
        return Decimal(amount) * i / (_ONE - (_ONE + i) ** (-term))


def annuity_payment(amount: int, annual_rate: Decimal, term: int) -> int:
    """Платёж по графику, целые рубли. Это число идёт в DSCR (без отдельного округления)."""
    return to_rub(annuity_payment_exact(amount, annual_rate, term))


def balance_after(amount: int, annual_rate: Decimal, term: int, paid: int) -> Decimal:
    """Закрытая формула остатка после `paid` платежей (проверка графика, инвариант 5)."""
    with localcontext(_CTX):
        i = annual_rate / 12
        if i == 0:
            return Decimal(amount) * (term - paid) / term
        pmt = annuity_payment_exact(amount, annual_rate, term)
        growth = (_ONE + i) ** paid
        return Decimal(amount) * growth - pmt * (growth - _ONE) / i


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    number: int
    interest: int
    principal: int
    payment: int
    balance: int


def build_schedule(amount: int, annual_rate: Decimal, term: int) -> tuple[ScheduleRow, ...]:
    """График: проценты месяца = округление остатка × i, последний платёж закрывает остаток."""
    pmt = annuity_payment(amount, annual_rate, term)
    i = monthly_rate(annual_rate)
    rows: list[ScheduleRow] = []
    balance = amount
    for number in range(1, term + 1):
        with localcontext(_CTX):
            interest = to_rub(Decimal(balance) * i)
        if number == term:
            principal = balance
            payment = balance + interest
        else:
            principal = pmt - interest
            payment = pmt
        balance -= principal
        rows.append(ScheduleRow(number, interest, principal, payment, balance))
    return tuple(rows)


def overpayment(schedule: Sequence[ScheduleRow], amount: int) -> int:
    return sum(row.payment for row in schedule) - amount


def payment_dates(
    issue_date: date, term: int, holidays: frozenset[date] = frozenset()
) -> tuple[date, ...]:
    """Даты платежей: день выдачи (не позже 28-го), перенос с выходных на следующий рабочий.

    Сумма платежа при переносе не меняется (30-16, пример 9).
    """
    anchor = issue_date.replace(day=min(issue_date.day, 28))
    return tuple(next_business_day(add_months(anchor, k), holidays) for k in range(1, term + 1))


# ---------------------------------------------------------------- проценты в конце срока, линия, овердрафт


def bullet_interest(amount: int, annual_rate: Decimal) -> int:
    """Платёж `CONTRACT` в месяц: `round(S·i)`; от срока не зависит."""
    with localcontext(_CTX):
        return to_rub(Decimal(amount) * annual_rate / 12)


def bullet_schedule(amount: int, annual_rate: Decimal, term: int) -> tuple[ScheduleRow, ...]:
    interest = bullet_interest(amount, annual_rate)
    rows = [ScheduleRow(k, interest, 0, interest, amount) for k in range(1, term)]
    rows.append(ScheduleRow(term, interest, amount, amount + interest, 0))
    return tuple(rows)


def line_payment_on_limit(limit: int, annual_rate: Decimal) -> int:
    """Платёж линии для DSCR (способ 3б): проценты на весь лимит."""
    return bullet_interest(limit, annual_rate)


def line_interest_on_average_use(balance_start: int, balance_end: int, annual_rate: Decimal) -> int:
    """Проценты месяца на среднее использованное: `(D_{t−1} + D_t) / 2 · i`."""
    with localcontext(_CTX):
        return to_rub(Decimal(balance_start + balance_end) / 2 * annual_rate / 12)


def overdraft_interest(daily_balances: Sequence[int], annual_rate: Decimal) -> int:
    """Проценты овердрафта по дням: `Σ U_d · r / 365`."""
    with localcontext(_CTX):
        return to_rub(Decimal(sum(daily_balances)) * annual_rate / 365)


def payment_for(repayment: str, amount: int, annual_rate: Decimal, term: int) -> int:
    """Платёж для DSCR по виду погашения продукта (30-08): аннуитет, проценты, проценты на лимит."""
    if repayment == "ANNUITY":
        return annuity_payment(amount, annual_rate, term)
    if repayment in ("BULLET", "LINE"):
        return bullet_interest(amount, annual_rate)
    if repayment == "OVERDRAFT":
        return 0
    raise ValueError(f"неизвестный вид погашения: {repayment}")


# ---------------------------------------------------------------- DSCR и обратная задача


def dscr(flow: int, existing: int, payment: int) -> Decimal:
    """`DSCR = CF / (E + P_new)`."""
    total = existing + payment
    if total <= 0:
        raise ValueError("сумма платежей должна быть положительной")
    with localcontext(_CTX):
        return Decimal(flow) / total


def stress_dscr(flow: int, existing: int, payment: int, shock: Decimal) -> Decimal:
    """`CF·(1 − s) / (E + P_new)`."""
    total = existing + payment
    if total <= 0:
        raise ValueError("сумма платежей должна быть положительной")
    with localcontext(_CTX):
        return Decimal(flow) * (_ONE - shock) / total


def max_payment(flow: int, existing: int, threshold: Decimal) -> Decimal:
    """`P_max = CF / T − E` (может быть отрицательным: поток не покрывает текущие платежи)."""
    with localcontext(_CTX):
        return Decimal(flow) / threshold - existing


def counter_threshold(base_dscr: Decimal, stress_min: Decimal, shock: Decimal) -> Decimal:
    """Порог DSCR для встречных: `max(1,30; 1,05 / (1 − шок))` (30-16, раздел 7)."""
    with localcontext(_CTX):
        return max(base_dscr, stress_min / (_ONE - shock))


def max_amount_formula(p_max: Decimal, annual_rate: Decimal, term: int, repayment: str) -> int:
    """Подсказка для поиска: `S_max = P_max · (1 − (1+i)^(−n)) / i`, округление вниз."""
    if p_max <= 0:
        return 0
    with localcontext(_CTX):
        i = annual_rate / 12
        if repayment == "ANNUITY":
            if i == 0:
                value = p_max * term
            else:
                value = p_max * (_ONE - (_ONE + i) ** (-term)) / i
        elif repayment in ("BULLET", "LINE"):
            value = p_max / i if i != 0 else _ZERO
        else:
            return 0
        # Гасим хвост деления (…999999 вместо …000000), иначе округление вниз теряет рубль
        return floor_rub(value.quantize(_TAIL))


def largest_step_amount(
    ok: Callable[[int], bool], hint: int, step: int, cap: int | None = None
) -> int:
    """Наибольшая сумма, кратная `step`, для которой `ok(сумма)` истинно (монотонное условие).

    `hint` — формула как подсказка; истина — прямой расчёт `ok` (30-16, раздел 7, п. 3).
    """
    if step <= 0:
        raise ValueError("шаг суммы должен быть положительным")
    k = max(hint // step, 0)
    if cap is not None:
        k = min(k, cap // step)
    while (cap is None or (k + 1) * step <= cap) and ok((k + 1) * step):
        k += 1
    while k > 0 and not ok(k * step):
        k -= 1
    return k * step


def min_term(amount: int, annual_rate: Decimal, p_max: Decimal) -> int | None:
    """Минимальный срок аннуитета для суммы при платеже не выше `p_max` (30-16, раздел 7, п. 4).

    `None`, если платёж не может быть меньше процентов (`S·i ≥ P_max`). Результат проверен прямым
    расчётом: платёж из графика не выше `P_max`.
    """
    if p_max <= 0:
        return None
    with localcontext(_CTX):
        i = annual_rate / 12
        if i == 0:
            term = int((Decimal(amount) / p_max).to_integral_value(rounding="ROUND_CEILING"))
            return max(term, 1)
        ratio = Decimal(amount) * i / p_max
        if ratio >= 1:
            return None
        n = int(
            ((-(_ONE - ratio).ln()) / (_ONE + i).ln()).to_integral_value(rounding="ROUND_CEILING")
        )
    n = max(n, 1)
    while n > 1 and annuity_payment(amount, annual_rate, n - 1) <= p_max:
        n -= 1
    while annuity_payment(amount, annual_rate, n) > p_max:
        n += 1
        if n > 1200:
            return None
    return n
