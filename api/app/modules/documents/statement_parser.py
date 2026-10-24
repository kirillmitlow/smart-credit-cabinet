"""Pure 1C statement parsing: reconciled turnover, never an assertion of business revenue."""

from __future__ import annotations

import re
from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.documents.statement_checks import AccountTotals, reconcile_accounts
from app.modules.documents.statement_format import kopecks, read_statement, statement_error


def rounded_rubles(cents: int) -> int:
    """One ROUND_HALF_UP at the boundary, using integers independent of Decimal context."""
    return (1 if cents >= 0 else -1) * ((abs(cents) + 50) // 100)


def _months(start: date, end: date) -> Iterator[tuple[str, date, date]]:
    for index in range(start.year * 12 + start.month - 1, end.year * 12 + end.month):
        year, month0 = divmod(index, 12)
        month = month0 + 1
        yield (
            f"{year:04}-{month:02}",
            date(year, month, 1),
            date(year, month, monthrange(year, month)[1]),
        )


@dataclass(frozen=True, slots=True)
class MonthlyTurnover:
    month: str
    complete: bool
    incoming_kopecks: int
    outgoing_kopecks: int
    internal_incoming_kopecks: int
    internal_outgoing_kopecks: int
    unclassified_incoming_kopecks: int

    @property
    def incoming_rub(self) -> int:
        return rounded_rubles(self.incoming_kopecks)

    @property
    def outgoing_rub(self) -> int:
        return rounded_rubles(self.outgoing_kopecks)

    def as_dict(self) -> dict[str, str | int | bool]:
        return {
            "month": self.month,
            "complete": self.complete,
            "incomingRub": self.incoming_rub,
            "outgoingRub": self.outgoing_rub,
            "internalIncomingRub": rounded_rubles(self.internal_incoming_kopecks),
            "internalOutgoingRub": rounded_rubles(self.internal_outgoing_kopecks),
            "unclassifiedIncomingRub": rounded_rubles(self.unclassified_incoming_kopecks),
            "incomingKopecks": self.incoming_kopecks,
            "outgoingKopecks": self.outgoing_kopecks,
            "internalIncomingKopecks": self.internal_incoming_kopecks,
            "internalOutgoingKopecks": self.internal_outgoing_kopecks,
            "unclassifiedIncomingKopecks": self.unclassified_incoming_kopecks,
        }


@dataclass(frozen=True, slots=True)
class ReceiptEvidence:
    operation_id: str
    month: str
    amount_kopecks: int
    reason: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "operationId": self.operation_id,
            "month": self.month,
            "amountKopecks": self.amount_kopecks,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    file_sha256: str
    encoding: str
    inn: str
    start: date
    end: date
    accounts: tuple[AccountTotals, ...]
    months: tuple[MonthlyTurnover, ...]
    exclusions: tuple[ReceiptEvidence, ...]
    ambiguous_receipts: tuple[ReceiptEvidence, ...]
    warnings: tuple[str, ...]
    payment_count: int
    duplicate_count: int
    unposted_count: int

    @property
    def complete_months(self) -> tuple[MonthlyTurnover, ...]:
        return tuple(month for month in self.months if month.complete)

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe provenance: raw purposes are retained only in the saved original file."""
        return {
            "fileSha256": self.file_sha256,
            "inn": self.inn,
            "period": {"start": self.start.isoformat(), "end": self.end.isoformat()},
            "accounts": [
                {
                    "account": a.account,
                    "start": a.start.isoformat(),
                    "end": a.end.isoformat(),
                    "openingKopecks": a.opening_kopecks,
                    "incomingKopecks": a.incoming_kopecks,
                    "outgoingKopecks": a.outgoing_kopecks,
                    "closingKopecks": a.closing_kopecks,
                    "controlsComplete": a.controls_complete,
                }
                for a in self.accounts
            ],
            "months": [month.as_dict() for month in self.months],
            "excludedReceipts": [item.as_dict() for item in self.exclusions],
            "ambiguousReceipts": [item.as_dict() for item in self.ambiguous_receipts],
            "warnings": list(self.warnings),
            "requiresReview": bool(self.warnings),
            "provenance": {
                "format": "1CClientBankExchange",
                "version": "1.03",
                "encoding": self.encoding,
                "parserVersion": "1c-1.03-v1",
                "paymentCount": self.payment_count,
                "duplicateCount": self.duplicate_count,
                "unpostedCount": self.unposted_count,
                "completeMonthCount": len(self.complete_months),
            },
        }


def parse_statement(content: bytes, expected_inn: str, *, as_of: date) -> ParsedStatement:
    """No network, database, current-clock reads or inference from free-text payment purposes.

    Only ownership-confirmed transfers between the loaded own accounts are classified and
    excluded. External receipts, including a loan, owner contribution or refund, remain
    unclassified: a payment purpose alone cannot prove their economic meaning. Consumers
    must confirm these receipts before using them as a revenue source (40-03, T-334).
    """
    if not re.fullmatch(r"(?:[0-9]{10}|[0-9]{12})", expected_inn):
        raise statement_error("OWNER_UNCONFIRMED")
    source = read_statement(content)
    if source.end > as_of:
        raise statement_error("INVALID_PERIOD")
    ledger = reconcile_accounts(source, expected_inn)
    complete = {
        name
        for name, first, last in _months(source.start, source.end)
        if first >= ledger.coverage_start
        and last <= ledger.coverage_end
        and (last.year, last.month) < (as_of.year, as_of.month)
    }
    if len(complete) < 3:
        raise statement_error("PERIOD_TOO_SHORT")
    # Incoming, outgoing, internal incoming/outgoing, and unclassified incoming in kopecks.
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    exclusions: list[ReceiptEvidence] = []
    ambiguous: list[ReceiptEvidence] = []
    for posting in ledger.postings:
        month = f"{posting.at.year:04}-{posting.at.month:02}"
        amount = kopecks(posting.payment.amount)
        sums[month][0 if posting.incoming else 1] += amount
        if posting.internal:
            sums[month][2 if posting.incoming else 3] += amount
        elif posting.incoming:
            sums[month][4] += amount
        if posting.incoming:
            evidence = ReceiptEvidence(
                posting.operation_id,
                month,
                amount,
                "OWN_TRANSFER" if posting.internal else "UNCLASSIFIED_EXTERNAL_RECEIPT",
            )
            (exclusions if posting.internal else ambiguous).append(evidence)
    months = tuple(
        MonthlyTurnover(name, name in complete, *sums[name])
        for name, _first, _last in _months(source.start, source.end)
    )
    warnings = []
    if ambiguous:
        warnings.append("UNCLASSIFIED_RECEIPTS")
    if ledger.unposted_count:
        warnings.append("UNPOSTED_DOCUMENTS")
    if any(not account.controls_complete for account in ledger.accounts):
        warnings.append("CONTROL_TOTALS_MISSING")
    if any(not month.complete for month in months):
        warnings.append("INCOMPLETE_MONTHS")
    if source.encoding == "utf-8":
        warnings.append("UTF8_FALLBACK")
    return ParsedStatement(
        source.sha256,
        source.encoding,
        expected_inn,
        source.start,
        source.end,
        ledger.accounts,
        months,
        tuple(exclusions),
        tuple(ambiguous),
        tuple(warnings),
        ledger.payment_count,
        ledger.duplicate_count,
        ledger.unposted_count,
    )


def validate_statement_set(statements: Sequence[ParsedStatement]) -> tuple[ParsedStatement, ...]:
    """Deduplicate identical originals; reject ambiguous overlaps before combining any turnover.

    Different files for disjoint accounts are fine. Overlapping periods of the same account
    require one consistent source file in MVP; no blind addition of monthly amounts.
    """
    unique = {statement.file_sha256: statement for statement in statements}
    if len({statement.inn for statement in unique.values()}) > 1:
        raise statement_error("INN_MISMATCH")
    periods: dict[str, list[AccountTotals]] = defaultdict(list)
    for statement in unique.values():
        for account in statement.accounts:
            periods[account.account].append(account)
    for rows in periods.values():
        rows.sort(key=lambda row: row.start)
        for previous, current in zip(rows, rows[1:], strict=False):
            if current.start <= previous.end:
                raise statement_error("OVERLAPPING_PERIODS")
            if previous.end.toordinal() + 1 == current.start.toordinal():
                if previous.closing_kopecks != current.opening_kopecks:
                    raise statement_error("BALANCE_MISMATCH")
    return tuple(unique.values())
