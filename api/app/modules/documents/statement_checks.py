"""Ownership, posted movement and exact balance reconciliation before monthly aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.modules.documents.statement_format import PaymentSection, StatementFile
from app.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class Posting:
    account: str
    at: date
    incoming: bool
    payment: PaymentSection
    internal: bool


def _fail(code: str) -> AppError:
    return AppError(422, code, "Проверьте ИНН, период и суммы банковской выписки")


def complete_months(statement: StatementFile, *, as_of: date) -> tuple[str, ...]:
    """Only fully covered months ending before as_of; current partial month never qualifies."""
    if statement.end > as_of:
        raise _fail("INVALID_PERIOD")
    first = statement.start.year * 12 + statement.start.month - 1
    last = statement.end.year * 12 + statement.end.month - 1
    months = []
    for index in range(first, last + 1):
        year, month0 = divmod(index, 12)
        start = date(year, month0 + 1, 1)
        if year == 9999 and month0 == 11:
            continue
        next_year, next_month0 = divmod(index + 1, 12)
        after = date(next_year, next_month0 + 1, 1)
        if (
            start >= statement.start
            and after <= as_of
            and after.toordinal() - 1 <= statement.end.toordinal()
        ):
            months.append(f"{year:04}-{month0 + 1:02}")
    if len(months) < 3:
        raise _fail("PERIOD_TOO_SHORT")
    return tuple(months)


def reconcile_accounts(statement: StatementFile, expected_inn: str) -> tuple[Posting, ...]:
    """Deduplicate before totals. Keep actual cash movement separate from revenue semantics."""
    sections: dict[str, list[tuple[date, date]]] = {}
    for section in statement.accounts:
        periods = sections.setdefault(section.number, [])
        if any(section.start <= end and section.end >= start for start, end in periods):
            raise _fail("OVERLAPPING_PERIODS")
        periods.append((section.start, section.end))
    owned = set(sections)
    if owned != set(statement.declared_accounts):
        raise _fail("OWNER_UNCONFIRMED")
    verified: set[str] = set()
    seen: dict[tuple[str, str, str, date, Decimal], PaymentSection] = {}
    postings: list[Posting] = []
    for payment in statement.payments:
        matched = False
        for side, account, incoming, posted in (
            ("Плательщик", payment.payer_account, False, payment.debited),
            ("Получатель", payment.recipient_account, True, payment.credited),
        ):
            if account not in owned:
                continue
            matched = True
            inn = payment.fields.get(f"{side}ИНН", "")
            if inn:
                if inn != expected_inn:
                    raise _fail("INN_MISMATCH")
                verified.add(account)
            if posted is None:
                continue  # A payment instruction alone is not proof of movement.
            if not any(start <= posted <= end for start, end in sections[account]):
                raise _fail("OPERATION_OUTSIDE_PERIOD")
            key = (account, payment.kind, payment.number, payment.created, payment.amount)
            previous = seen.get(key)
            if previous is not None:
                if previous != payment:
                    raise _fail("CONFLICTING_DUPLICATE")
                continue
            seen[key] = payment
            postings.append(
                Posting(
                    account,
                    posted,
                    incoming,
                    payment,
                    payment.payer_account in owned and payment.recipient_account in owned,
                )
            )
        if not matched:
            raise _fail("FOREIGN_ACCOUNT")
    if verified != owned:
        raise _fail("OWNER_UNCONFIRMED")
    for section in statement.accounts:
        relevant = [
            posting
            for posting in postings
            if posting.account == section.number and section.start <= posting.at <= section.end
        ]
        received = sum((p.payment.amount for p in relevant if p.incoming), Decimal(0))
        spent = sum((p.payment.amount for p in relevant if not p.incoming), Decimal(0))
        if (
            section.received is not None
            and section.received != received
            or section.spent is not None
            and section.spent != spent
            or section.closing is not None
            and section.opening + received - spent != section.closing
        ):
            raise _fail("BALANCE_MISMATCH")
    for account, periods in sections.items():
        rows = sorted((s for s in statement.accounts if s.number == account), key=lambda s: s.start)
        for previous, current in zip(rows, rows[1:], strict=False):
            if previous.end.toordinal() + 1 == current.start.toordinal():
                if previous.closing is None or previous.closing != current.opening:
                    raise _fail("BALANCE_MISMATCH")
    return tuple(postings)
