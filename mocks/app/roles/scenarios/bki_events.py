"""Просрочки, чужие запросы/отказы и статусы истории (T-124), без ввода-вывода."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.common.reldate import add_months
from app.roles.scenarios.bki_loans import CreditDefaults, active_loan, closed_loan
from app.roles.scenarios.schemas import ActiveLoan, BkiSubjectSpec, ClosedLoan


def overdue_start(block: BkiSubjectSpec, today: date) -> date | None:
    if not block.current_overdue_days:
        if block.current_overdue_rub:
            raise ValueError("Для currentOverdueRub > 0 нужен currentOverdueDays > 0")
        return None
    return today - timedelta(days=block.current_overdue_days)


def dated_events(count: int, days: int, today: date) -> list[date]:
    """Детерминированно внутри окна, не создавая будущих дат."""
    return [today - timedelta(days=(index + 1) * days // (count + 1)) for index in range(count)]


def apply_events(
    block: BkiSubjectSpec,
    obligations: list[dict[str, Any]],
    code: str,
    inn: str,
    today: date,
    earliest: date | None,
    defaults: CreditDefaults,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active = [o for o in obligations if o["closedAt"] is None]
    if block.current_overdue_days:
        if not active:
            raise ValueError("Для текущей просрочки нужен хотя бы один activeLoans")
        if block.current_overdue_rub is not None:
            active[0]["overdueRub"] = block.current_overdue_rub

    if block.past_max_overdue_days:
        # Завершённый эпизод не пересекается с текущим и целиком лежит в окне 24 мес.
        end = min(
            today - timedelta(days=30), (overdue_start(block, today) or today) - timedelta(days=1)
        )
        start = end - timedelta(days=block.past_max_overdue_days)
        if start < add_months(today, -24):
            raise ValueError("pastMaxOverdueDays не помещается в последние 24 месяца")
        if earliest is not None and start < earliest:
            raise ValueError("Прошлая просрочка компании не может быть раньше регистрации")
        eligible = [
            o
            for o in obligations
            if date.fromisoformat(o["openedAt"]) <= start
            and (o["closedAt"] is None or date.fromisoformat(o["closedAt"]) >= end)
        ]
        if eligible:
            target = eligible[0]
        else:
            generated = ClosedLoan(
                kind="LOAN",
                amount_rub=100000,
                opened_at=max(start - timedelta(days=1), earliest or date.min).isoformat(),
                closed_at=end.isoformat(),
            )
            target = closed_loan(generated, code, inn, "past-overdue", today, earliest, defaults)
            obligations.append(target)
        target["overduePeriods"].insert(0, {"since": start.isoformat(), "until": end.isoformat()})

    if block.sold_to_collectors:
        if not active:
            generated_active, _ = active_loan(
                ActiveLoan(kind="LOAN", amount_rub=100000),
                code,
                inn,
                len(obligations),
                today,
                earliest,
                defaults,
            )
            obligations.append(generated_active)
            active.append(generated_active)
        active[0]["status"] = "SOLD_TO_COLLECTORS"

    candidates = [o for o in active if o["status"] == "ACTIVE"]
    for index in range(block.restructurings24m or 0):
        if index < len(candidates):
            candidates[index]["status"] = "RESTRUCTURED"
            continue
        opened = max(add_months(today, -18), earliest) if earliest else add_months(today, -18)
        if opened >= today:
            raise ValueError("Для реструктуризации нужна история компании хотя бы за один день")
        closed = max(add_months(today, -6), opened + timedelta(days=1))
        closed = min(closed, today)
        historical = closed_loan(
            ClosedLoan(
                kind="LOAN",
                amount_rub=100000,
                opened_at=opened.isoformat(),
                closed_at=closed.isoformat(),
            ),
            code,
            inn,
            f"restructured-{index}",
            today,
            earliest,
            defaults,
        )
        historical["status"] = "RESTRUCTURED"
        obligations.append(historical)

    inquiries = [
        {"date": day.isoformat(), "userType": "BANK", "purpose": "LOAN_APPLICATION", "isOwn": False}
        for day in dated_events(block.inquiries30d or 0, 30, today)
    ]
    applications = [
        {
            "date": day.isoformat(),
            "kind": "LOAN",
            "amountRub": 100000,
            "decision": "REJECTED",
            "decisionDate": day.isoformat(),
            "isOwn": False,
        }
        for day in dated_events(block.rejected_applications90d or 0, 90, today)
    ]
    return inquiries, applications
