"""Unit: паузы outbox, ключи идемпотентности, разбор отказов АБС, график кредита, payload БКИ."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.modules.disbursement import bki_events, keys
from app.modules.disbursement.models import Disbursement
from app.modules.disbursement.terms import shape_of
from app.modules.integrations import (
    Failure,
    Reason,
    SourceUnavailable,
    System,
    classify_failure,
)
from app.modules.integrations.bank_core_write import DisbursementRequest, disbursement_body
from app.modules.loans import next_payment, schedule_rows
from app.shared import outbox

# ruff: noqa: PT018
pytestmark = pytest.mark.unit

APP_ID = UUID("0192a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b")


def test_backoff_schedule_without_jitter() -> None:
    mid = lambda lo, hi: (lo + hi) / 2  # noqa: E731
    delays = [outbox.backoff_delay(n, mid) for n in range(1, 9)]
    assert delays == [5, 15, 45, 120, 300, 300, 300, 300]


@pytest.mark.parametrize("attempt", range(1, 12))
def test_backoff_jitter_stays_in_band_and_under_cap(attempt: int) -> None:
    base = outbox.BACKOFF_S[min(attempt, 5) - 1]
    low = outbox.backoff_delay(attempt, lambda lo, hi: lo)
    high = outbox.backoff_delay(attempt, lambda lo, hi: hi)
    assert low == pytest.approx(base * 0.8)
    assert high == pytest.approx(min(300, base * 1.2))


def test_keys_are_ascii_and_stable_per_application() -> None:
    values = [
        keys.account_key(APP_ID),
        keys.disbursement_key(APP_ID),
        keys.obligation_key(APP_ID),
        keys.obligation_event_id(APP_ID),
        keys.contract_uid(APP_ID),
    ]
    assert all(v.isascii() for v in values)
    assert keys.disbursement_key(APP_ID) == keys.disbursement_key(APP_ID)
    assert keys.disbursement_key(APP_ID) != keys.account_key(APP_ID)
    assert str(APP_ID) in keys.disbursement_key(APP_ID)


def _fail(reason: Reason, code: str | None = None, status: int | None = None) -> SourceUnavailable:
    return SourceUnavailable(System.BANK_CORE, reason, status_code=status, error_code=code)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (_fail(Reason.REJECTED, "ACCOUNT_ALREADY_EXISTS", 409), Failure.ACCOUNT_EXISTS),
        (_fail(Reason.REJECTED, "CUSTOMER_NOT_FOUND", 404), Failure.CUSTOMER_NOT_FOUND),
        (_fail(Reason.REJECTED, "ACCOUNT_BLOCKED", 409), Failure.ACCOUNT_PROBLEM),
        (_fail(Reason.REJECTED, "ACCOUNT_NOT_OWNED", 409), Failure.ACCOUNT_PROBLEM),
        (_fail(Reason.REJECTED, "ALREADY_DISBURSED", 409), Failure.ALREADY_DISBURSED),
        (_fail(Reason.REJECTED, "VALIDATION_ERROR", 422), Failure.DEFECT),
        (_fail(Reason.REJECTED, "IDEMPOTENCY_IN_PROGRESS", 409), Failure.RETRY),
        (_fail(Reason.CONNECTION_ERROR), Failure.RETRY),
        (_fail(Reason.TIMEOUT), Failure.RETRY),
        (_fail(Reason.HTTP_5XX, None, 503), Failure.RETRY),
        (_fail(Reason.CIRCUIT_OPEN), Failure.DEFER),
    ],
)
def test_classify_bank_core_failures(failure: SourceUnavailable, expected: Failure) -> None:
    assert classify_failure(failure) is expected


def test_disbursement_body_is_deterministic_and_camel_case() -> None:
    from datetime import UTC, datetime

    request = DisbursementRequest(
        "АЗ-2026-000001", "001234567887", "КД-2026-000001", "uid-1",
        datetime(2026, 10, 21, 9, 0, tzinfo=UTC), "EXPRESS", "LOAN", 500_000, None, 12, 24.0,
        "ANNUITY", "40802810800000001234",
    )  # fmt: skip
    body = disbursement_body(request)
    assert body == disbursement_body(request)
    assert body["contract"] == {
        "number": "КД-2026-000001",
        "uid": "uid-1",
        "signedAt": "2026-10-21T09:00:00Z",
    }
    assert body["amountRub"] == 500_000 and body["limitRub"] is None


def test_shapes_for_limit_products_open_only_limit() -> None:
    assert shape_of("CREDIT_LINE").is_limit and shape_of("OVERDRAFT").is_limit
    assert shape_of("CONTRACT").repayment_type == "BULLET"
    assert shape_of("EXPRESS").repayment_type == "ANNUITY"
    with pytest.raises(ValueError, match="Неизвестный продукт"):
        shape_of("NOPE")


def test_annuity_schedule_is_twelve_rows_with_business_day_first_payment() -> None:
    rows = schedule_rows("ANNUITY", 500_000, Decimal("24.000"), 12, date(2026, 10, 21))
    assert len(rows) == 12
    assert sum(r.principal_rub for r in rows) == 500_000
    assert all(r.total_rub == r.principal_rub + r.interest_rub for r in rows)
    # 21 ноября 2026 — суббота: платёж переносится на понедельник
    assert rows[0].due_date == date(2026, 11, 23)
    assert next_payment(rows, date(2026, 10, 21)) is rows[0]
    assert next_payment(rows, date(2026, 11, 24)) is rows[1]
    assert next_payment(rows, date(2030, 1, 1)) is None


def test_bullet_and_revolving_schedules() -> None:
    bullet = schedule_rows("BULLET", 1_000_000, Decimal("20"), 6, date(2026, 10, 21))
    assert len(bullet) == 6 and bullet[-1].principal_rub == 1_000_000
    assert all(r.principal_rub == 0 for r in bullet[:-1])
    assert schedule_rows("REVOLVING", 0, Decimal("20"), 12, date(2026, 10, 21)) == []


def test_obligation_payload_round_trip() -> None:
    row = Disbursement(
        application_id=APP_ID, customer_inn="001234567887", contract_uid="uid-1", kind="LOAN",
        amount_rub=500_000, limit_rub=None,
    )  # fmt: skip
    payload = bki_events.build_payload(row, 47_000, date(2026, 10, 21), date(2027, 10, 21))
    event = bki_events.event_from_payload(payload)
    assert event.subject.type == "PERSON" and event.subject.inn == "001234567887"
    assert event.obligation is not None and event.obligation.amount_rub == 500_000
    assert event.event_id == keys.obligation_event_id(APP_ID)
