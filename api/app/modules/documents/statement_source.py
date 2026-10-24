"""Client-asserted business receipts, bounded by verified originals (T-334).

No economic formulas: exact cents in, one rounding at the core boundary. Confirmation
is immutable; correcting an assertion requires replacing the file. The application
owner must authorize and lock the application before calling confirm_statement.
"""

from collections import defaultdict
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.service import Access, get_metadata, verified_content
from app.modules.documents.statement_parser import (
    ParsedStatement,
    parse_statement,
    rounded_rubles,
    validate_statement_set,
)
from app.shared import clock
from app.shared.errors import AppError

CONFIRMATION_VERSION = "statement-revenue-v1"
CONFIRMATION_KEY = "revenueConfirmation"


def _invalid(code: str = "STATEMENT_CONFIRMATION_INVALID") -> AppError:
    return AppError(422, code, "Проверьте подтверждённые суммы и общие полные месяцы выписок")


def _read(session: Session, row: Document, inn: str) -> ParsedStatement:
    _, content = verified_content(session, Access(row.created_by, (row.company_id,)), row.id)
    return parse_statement(content, inn, as_of=clock.today())


def _eligible(row: Document, parsed: ParsedStatement) -> dict[str, Any]:
    # A clock change must not silently expand the set of months the client reviewed.
    original_months = {
        month["month"] for month in (row.parsed or {}).get("months", []) if month.get("complete")
    }
    return {m.month: m for m in parsed.complete_months if m.month in original_months}


def _assertion(row: Document, parsed: ParsedStatement) -> dict[str, int]:
    confirmation = (row.parsed or {}).get(CONFIRMATION_KEY, {})
    if (
        row.confirmed_at is None
        or row.confirmed_by is None
        or confirmation.get("version") != CONFIRMATION_VERSION
        or confirmation.get("sha256") != row.sha256
    ):
        raise _invalid()
    amounts: dict[str, int] = confirmation.get("months", {})
    eligible = _eligible(row, parsed)
    if not 3 <= len(amounts) <= 24 or not set(amounts) <= set(eligible):
        raise _invalid()
    for month, amount in amounts.items():
        if (
            type(amount) is not int
            or not 0 <= amount <= eligible[month].unclassified_incoming_kopecks
        ):
            raise _invalid()
    return amounts


def _rows(session: Session, application_id: UUID, company_id: UUID) -> list[Document]:
    return list(
        session.scalars(
            select(Document)
            .where(
                Document.application_id == application_id,
                Document.company_id == company_id,
                Document.kind == "BANK_STATEMENT_1C",
                Document.cancelled_at.is_(None),
                Document.parse_status == "PARSED",
                Document.confirmed_at.is_not(None),
            )
            .order_by(Document.created_at, Document.id)
        )
    )


def confirmed_statement_source(
    session: Session, application_id: UUID, company_id: UUID, inn: str
) -> dict[str, Any] | None:
    """Freeze an auditable bundle for one run; no unconfirmed file can enter it.

    A month needs complete coverage from all loaded accounts. A missing month breaks
    the history: only the latest continuous suffix (at most 24 months) is used.
    """
    rows = _rows(session, application_id, company_id)
    if not rows:
        return None
    originals = [_read(session, row, inn) for row in rows]
    validate_statement_set(originals)
    seen: dict[str, dict[str, int]] = {}
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    covered: dict[str, set[str]] = defaultdict(set)
    all_accounts: set[str] = set()
    evidence = []
    for row, original in zip(rows, originals, strict=True):
        amounts = _assertion(row, original)
        evidence.append(
            {
                "documentId": str(row.id),
                "sha256": row.sha256,
                "origin": row.origin,
                "confirmedAt": row.confirmed_at.isoformat(),  # type: ignore[union-attr]
                "confirmedBy": str(row.confirmed_by),
                "confirmation": (row.parsed or {})[CONFIRMATION_KEY],
            }
        )
        if row.sha256 in seen:
            if seen[row.sha256] != amounts:
                raise _invalid("DUPLICATE_CONFIRMATION_CONFLICT")
            continue
        seen[row.sha256] = amounts
        accounts = {account.account for account in original.accounts}
        all_accounts.update(accounts)
        months = _eligible(row, original)
        for month, amount in amounts.items():
            incoming[month] += amount
            outgoing[month] += (
                months[month].outgoing_kopecks - months[month].internal_outgoing_kopecks
            )
            covered[month].update(accounts)
    candidates = sorted(month for month in covered if covered[month] == all_accounts)
    continuous: list[str] = []
    previous: int | None = None
    for month in reversed(candidates):
        year, number = map(int, month.split("-"))
        index = year * 12 + number
        if previous is not None and index != previous - 1:
            break
        continuous.append(month)
        previous = index
        if len(continuous) == 24:
            break
    if len(continuous) < 3:
        raise _invalid("STATEMENT_COVERAGE_INCOMPLETE")
    return {
        "inn": inn,
        "confirmationVersion": CONFIRMATION_VERSION,
        "documents": evidence,
        "months": [
            {
                "month": month,
                "incomingRub": rounded_rubles(incoming[month]),
                "outgoingRub": rounded_rubles(outgoing[month]),
                "incomingKopecks": incoming[month],
                "outgoingKopecks": outgoing[month],
            }
            for month in reversed(continuous)
        ],
    }


def confirm_statement(
    session: Session,
    access: Access,
    document_id: UUID,
    *,
    inn: str,
    sha256: str,
    months: Mapping[str, int],
) -> tuple[Document, bool]:
    row = get_metadata(session, access, document_id)
    session.refresh(row, with_for_update=True)
    if (
        access.bank
        or row.cancelled_at is not None
        or row.kind != "BANK_STATEMENT_1C"
        or row.parse_status != "PARSED"
        or row.sha256 != sha256
    ):
        raise AppError(409, "STATEMENT_NOT_CONFIRMABLE", "Обновите сведения о выписке")
    original = _read(session, row, inn)
    eligible = _eligible(row, original)
    expected_months = sorted(eligible)[-24:]
    if set(months) != set(expected_months) or not 3 <= len(months) <= 24:
        raise _invalid()
    for month, amount in months.items():
        if (
            type(amount) is not int
            or not 0 <= amount <= eligible[month].unclassified_incoming_kopecks
        ):
            raise _invalid()
    confirmation = {
        "version": CONFIRMATION_VERSION,
        "sha256": sha256,
        "months": dict(sorted(months.items())),
    }
    if row.confirmed_at is not None:
        if (row.parsed or {}).get(CONFIRMATION_KEY) != confirmation:
            raise AppError(409, "STATEMENT_ALREADY_CONFIRMED", "Для исправления замените файл")
        return row, False
    row.parsed = {**(row.parsed or {}), CONFIRMATION_KEY: confirmation}
    row.confirmed_at, row.confirmed_by = clock.now(), access.user_id
    session.flush()
    # Validate the whole active set before accepting a new confirmation; rollback is atomic.
    confirmed_statement_source(session, row.application_id, row.company_id, inn)
    return row, True
