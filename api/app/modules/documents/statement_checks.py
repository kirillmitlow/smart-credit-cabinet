"""Reconcile posted movement in exact kopecks before interpreting monthly turnover."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from app.modules.documents.statement_format import (
    AccountSection,
    PaymentSection,
    StatementFile,
    kopecks,
    statement_error,
)


@dataclass(frozen=True, slots=True)
class Posting:
    account: str
    at: date
    incoming: bool
    payment: PaymentSection
    operation_id: str
    internal: bool


@dataclass(frozen=True, slots=True)
class AccountTotals:
    account: str
    start: date
    end: date
    opening_kopecks: int
    incoming_kopecks: int
    outgoing_kopecks: int
    closing_kopecks: int
    controls_complete: bool


@dataclass(frozen=True, slots=True)
class Reconciled:
    postings: tuple[Posting, ...]
    accounts: tuple[AccountTotals, ...]
    coverage_start: date
    coverage_end: date
    payment_count: int
    duplicate_count: int
    unposted_count: int


def operation_id(payment: PaymentSection) -> str:
    """Same movement across both own accounts has one stable reference without raw payment fields."""
    parts = (
        payment.kind,
        payment.number,
        payment.created.isoformat(),
        format(payment.amount, ".2f"),
        payment.payer_account,
        payment.recipient_account,
    )
    return sha256("\0".join(parts).encode()).hexdigest()


def _same_payment(left: PaymentSection, right: PaymentSection) -> bool:
    # Dot/comma and omitted zero kopecks are different text representations of equal money.
    return (
        left.kind == right.kind
        and left.amount == right.amount
        and {key: value for key, value in left.fields.items() if key != "Сумма"}
        == {key: value for key, value in right.fields.items() if key != "Сумма"}
    )


def reconcile_accounts(statement: StatementFile, expected_inn: str) -> Reconciled:
    """O(records log sections): never rescan every payment for every account period."""
    grouped: dict[str, list[AccountSection]] = defaultdict(list)
    for section in statement.accounts:
        grouped[section.number].append(section)
    if set(grouped) != set(statement.declared_accounts):
        raise statement_error("OWNER_UNCONFIRMED")
    starts: dict[str, list[int]] = {}
    for account, rows in grouped.items():
        rows.sort(key=lambda row: row.start)
        for previous, current in zip(rows, rows[1:], strict=False):
            if current.start <= previous.end:
                raise statement_error("OVERLAPPING_PERIODS")
            if previous.end.toordinal() + 1 != current.start.toordinal():
                raise statement_error("INCOMPLETE_PERIOD")
        starts[account] = [row.start.toordinal() for row in rows]
    owned = set(grouped)
    verified: set[str] = set()
    seen: dict[str, PaymentSection] = {}
    keys: dict[tuple[str, bool, str, date, int], PaymentSection] = {}
    sums: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    postings: list[Posting] = []
    duplicates = unposted = 0
    for payment in statement.payments:
        sides = [
            (side, account, incoming, posted)
            for side, account, incoming, posted in (
                ("Плательщик", payment.payer_account, False, payment.debited),
                ("Получатель", payment.recipient_account, True, payment.credited),
            )
            if account in owned
        ]
        if not sides:
            raise statement_error("FOREIGN_ACCOUNT")
        for side, account, _incoming, _posted in sides:
            inn = payment.fields.get(f"{side}ИНН", "")
            if inn:
                if inn != expected_inn:
                    raise statement_error("INN_MISMATCH")
                verified.add(account)
        reference = operation_id(payment)
        if reference in seen:
            if not _same_payment(seen[reference], payment):
                raise statement_error("CONFLICTING_DUPLICATE")
            duplicates += 1
            continue
        seen[reference] = payment
        if any(posted is None for _, _, _, posted in sides):
            unposted += 1
        amount = kopecks(payment.amount)
        for _side, account, incoming, posted in sides:
            if posted is None:
                continue  # No own posted date: no movement, even if the instruction has a date.
            index = bisect_right(starts[account], posted.toordinal()) - 1
            if index < 0 or posted > grouped[account][index].end:
                raise statement_error("OPERATION_OUTSIDE_PERIOD")
            key = (account, incoming, payment.number, payment.created, amount)
            if key in keys and not _same_payment(keys[key], payment):
                raise statement_error("CONFLICTING_DUPLICATE")
            keys[key] = payment
            sums[(account, index)][0 if incoming else 1] += amount
            postings.append(
                Posting(
                    account,
                    posted,
                    incoming,
                    payment,
                    reference,
                    payment.payer_account in owned and payment.recipient_account in owned,
                )
            )
    if verified != owned:
        raise statement_error("OWNER_UNCONFIRMED")
    accounts = []
    for account in sorted(grouped):
        previous_closing: int | None = None
        for index, section in enumerate(grouped[account]):
            received, spent = sums[(account, index)]
            opening = kopecks(section.opening)
            closing = opening + received - spent
            if (
                (section.received is not None and kopecks(section.received) != received)
                or (section.spent is not None and kopecks(section.spent) != spent)
                or (section.closing is not None and kopecks(section.closing) != closing)
                or (previous_closing is not None and previous_closing != opening)
            ):
                raise statement_error("BALANCE_MISMATCH")
            accounts.append(
                AccountTotals(
                    account,
                    section.start,
                    section.end,
                    opening,
                    received,
                    spent,
                    closing,
                    all(
                        value is not None
                        for value in (section.received, section.spent, section.closing)
                    ),
                )
            )
            previous_closing = closing
    return Reconciled(
        tuple(postings),
        tuple(accounts),
        max(rows[0].start for rows in grouped.values()),
        min(rows[-1].end for rows in grouped.values()),
        len(seen),
        duplicates,
        unposted,
    )
