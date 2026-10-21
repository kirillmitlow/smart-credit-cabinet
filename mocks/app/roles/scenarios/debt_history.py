"""Исторический долг из модели сценария, отдельно от сегодняшнего raw-снимка.

Допущения T-126/D-106: среднедневной остаток, revolving использован постоянно;
в конце завершённой просрочки накопленные платежи погашаются. На closedAt долг 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from app.roles.scenarios.bki_expand import merge_subjects
from app.roles.scenarios.bki_loans import DEFAULTS, LIMIT_KINDS
from app.roles.scenarios.credit_math import (
    due_date,
    external_balance,
    implied_rate,
    money,
    schedule,
)
from app.roles.scenarios.credit_uid import contract_uid
from app.roles.scenarios.schemas import ActiveLoan, ScenarioSpec

HISTORY_FIELDS = (
    "kind",
    "role",
    "amountRub",
    "limitRub",
    "openedAt",
    "plannedCloseAt",
    "closedAt",
    "overduePeriods",
)


@dataclass(frozen=True)
class DebtTotals:
    year_end: int
    average: Decimal

    @property
    def interest_bounds(self) -> tuple[int, int]:
        return (
            int((self.average * Decimal("0.02")).to_integral_value(rounding=ROUND_CEILING)),
            int((self.average * Decimal("0.25")).to_integral_value(rounding=ROUND_FLOOR)),
        )


@dataclass
class Trajectory:
    body: dict[str, Any]
    rate: Decimal
    bullet: bool = False
    our_bank: bool = False
    _cache: dict[int, list[int]] = field(default_factory=dict)

    def balances(self, year: int) -> list[int]:
        if year in self._cache:
            return self._cache[year]
        loan = self.body
        opened = date.fromisoformat(loan["openedAt"])
        closed = date.fromisoformat(loan["closedAt"]) if loan["closedAt"] else None
        planned = date.fromisoformat(loan["plannedCloseAt"])
        term = max(1, (planned.year - opened.year) * 12 + planned.month - opened.month)
        amount = loan["amountRub"] or loan["limitRub"] or 0
        revolving = loan["kind"] in LIMIT_KINDS
        used = loan["balanceRub"] if closed is None else amount
        rows = schedule(amount, term, self.rate, opened) if self.our_bank else []
        due = [due_date(opened, i, working_days=self.our_bank) for i in range(1, term + 1)]
        periods = [
            (date.fromisoformat(p["since"]), date.fromisoformat(p["until"]) if p["until"] else None)
            for p in loan["overduePeriods"]
        ]
        result = []
        day = date(year, 1, 1)
        while day.year == year:
            if day < opened or (closed is not None and day >= closed):
                balance = 0
            elif revolving:
                balance = used
            elif self.bullet:
                balance = amount
            else:
                cutoff = day
                for since, until in periods:
                    if since <= day and (until is None or day < until):
                        cutoff = min(cutoff, since - timedelta(days=1))
                paid = sum(d <= cutoff for d in due)
                balance = (
                    (rows[paid - 1].balance if paid else amount)
                    if self.our_bank
                    else external_balance(amount, term, self.rate, paid)
                )
            result.append(balance)
            day += timedelta(days=1)
        self._cache[year] = result
        return result


def build_history(spec: ScenarioSpec, data: dict[str, Any], code: str) -> dict[str, Trajectory]:
    identity = data["identity"]
    inn = identity["inn"]
    source = merge_subjects(spec, identity).get(inn)
    active: dict[str, ActiveLoan] = {}
    bullets: set[str] = set()
    if source:
        loans = list(source.active_loans or [])
        if source.monthly_payments_rub:
            loans = [ActiveLoan(kind="LOAN", monthly_payment_rub=source.monthly_payments_rub)]
        active = {contract_uid(code, inn, f"active-{i}"): loan for i, loan in enumerate(loans)}
        bullets = {
            contract_uid(code, inn, f"closed-{i}")
            for i, loan in enumerate(source.closed_loans or [])
            if loan.repayment == "BULLET"
        }
    result = {}
    for entry in data["bki"]:
        if entry["inn"] != inn:
            continue
        for body in entry["body"]["obligations"]:
            uid = body["uid"]
            loan = active.get(uid)
            rate = DEFAULTS.rate_percent
            if loan:
                rate = Decimal(str(loan.rate_percent)) if loan.rate_percent is not None else rate
                if (
                    loan.kind not in LIMIT_KINDS
                    and loan.monthly_payment_rub is not None
                    and loan.rate_percent is None
                ):
                    rate = implied_rate(
                        body["amountRub"], loan.term_months or 24, loan.monthly_payment_rub
                    )
            result[uid] = Trajectory(body, rate, uid in bullets, bool(loan and loan.our_bank))
    return result


def debt_totals(data: dict[str, Any], history: dict[str, Trajectory], year: int) -> DebtTotals:
    inn = data["identity"]["inn"]
    end = date(year, 12, 31).isoformat()
    day_totals = [0] * ((date(year + 1, 1, 1) - date(year, 1, 1)).days)
    for entry in data["bki"]:
        if entry["inn"] != inn:
            continue
        for body in entry["body"]["obligations"]:
            trajectory = history.get(body["uid"])
            if body["openedAt"] > end and (trajectory is None or trajectory.body["openedAt"] > end):
                continue
            if body["role"] == "GUARANTOR" and (
                trajectory is None or trajectory.body["role"] == "GUARANTOR"
            ):
                continue
            if trajectory is None or any(
                body.get(field) != trajectory.body.get(field) for field in HISTORY_FIELDS
            ):
                raise ValueError(
                    f"DEBT_HISTORY_UNVERIFIABLE: кредит {body['uid']} влияет на {year} год, "
                    "но raw не определяет историю погашения. Сохраните УИд и исторические поля "
                    "кредита из параметров сценария; balanceRub/monthlyPaymentRub — снимок сегодня"
                )
            day_totals = [a + b for a, b in zip(day_totals, trajectory.balances(year), strict=True)]
    return DebtTotals(day_totals[-1], Decimal(sum(day_totals)) / len(day_totals))


def enrich_statements(data: dict[str, Any], history: dict[str, Trajectory]) -> None:
    records = data["tax"]["financials"]
    if not records:
        return
    latest = max(records, key=lambda r: r["year"])
    totals = debt_totals(data, history, latest["year"])
    low, high = totals.interest_bounds
    if low > high:
        raise ValueError(
            "STATEMENT_DEBT: для среднего долга нет целой суммы процентов в диапазоне 2–25%"
        )
    lines = latest["lines"]
    debt = totals.year_end
    lines["1400"] = debt
    lines["1200"] += debt
    lines["1600"] += debt
    lines["2330"] = min(high, max(low, money(totals.average * Decimal("0.10"))))
    lines["2200"] = lines["2400"] + lines["2330"]
