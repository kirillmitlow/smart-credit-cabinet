"""T-236: запись в АБС против живого мока: открытие счёта не-клиенту и выдача (garipov, 7.3, 7.4)."""

# ruff: noqa: PT018
from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from app.modules.integrations import (
    DisbursementRequest,
    Failure,
    Integrations,
    Ok,
    SourceUnavailable,
    classify_failure,
)
from tests.contract.conftest import ListJournal, Persona

pytestmark = pytest.mark.contract

PersonaFactory = Callable[[str], Persona]


def request_for(inn: str, account: str, ref: str, **over: object) -> DisbursementRequest:
    base: dict[str, object] = {
        "application_ref": ref,
        "customer_inn": inn,
        "contract_number": f"КД-{ref}",
        "contract_uid": f"{uuid4()}-1",
        "contract_signed_at": datetime(2026, 10, 21, 9, 0, tzinfo=UTC),
        "product_code": "EXPRESS",
        "kind": "LOAN",
        "amount_rub": 300_000,
        "limit_rub": None,
        "term_months": 12,
        "rate_percent": 24.0,
        "repayment_type": "ANNUITY",
        "settlement_account": account,
    }
    return DisbursementRequest(**{**base, **over})  # type: ignore[arg-type]


def test_garipov_open_account_then_disburse_with_replay(
    live: Integrations, persona: PersonaFactory, journal: ListJournal, scenarios_http: httpx.Client
) -> None:
    garipov = persona("garipov")
    scenarios_http.post(f"/scenarios/{garipov.code}/apply").raise_for_status()
    inn = garipov.inn
    assert live.bank_core_write is not None
    write = live.bank_core_write
    key = f"acc:{uuid4()}"
    opened = write.open_account(inn, "INDIVIDUAL_ENTREPRENEUR", "ИП Гарипов", idempotency_key=key)
    assert isinstance(opened, Ok)
    number = opened.data.account.number
    assert len(number) == 20 and opened.data.account.status == "OPEN"

    # Повтор с тем же ключом — тот же счёт, второго нет
    again = write.open_account(inn, "INDIVIDUAL_ENTREPRENEUR", "ИП Гарипов", idempotency_key=key)
    assert isinstance(again, Ok) and again.data.account.number == number
    assert again.snapshot_meta.replayed
    # Другой ключ: счёт уже есть
    other = write.open_account(
        inn, "INDIVIDUAL_ENTREPRENEUR", "ИП Гарипов", idempotency_key=f"acc:{uuid4()}"
    )
    assert isinstance(other, SourceUnavailable)
    assert classify_failure(other) is Failure.ACCOUNT_EXISTS

    ref = f"АЗ-2026-{random.randint(100000, 999999)}"
    request = request_for(inn, number, ref)
    dkey = f"dsb:{uuid4()}"
    first = write.disburse(request, idempotency_key=dkey)
    assert isinstance(first, Ok)
    assert first.data.amount_rub == 300_000 and first.data.settlement_account == number
    second = write.disburse(request, idempotency_key=dkey)
    assert isinstance(second, Ok) and second.snapshot_meta.replayed
    assert second.data.loan_id == first.data.loan_id  # деньги выданы один раз

    # Тот же кредит под другим ключом — ALREADY_DISBURSED
    dup = write.disburse(request, idempotency_key=f"dsb:{uuid4()}")
    assert isinstance(dup, SourceUnavailable)
    assert classify_failure(dup) is Failure.ALREADY_DISBURSED
    assert any(r.idempotent_replayed for r in journal.records)

    loans = live.bank_core.get_loans(inn)
    assert isinstance(loans, Ok) and loans.data is not None
    assert [x.application_ref for x in loans.data] == [ref]


def test_disburse_error_codes(live: Integrations, persona: PersonaFactory) -> None:
    inn = persona("garipov").inn
    assert live.bank_core_write is not None
    write = live.bank_core_write
    stranger = write.disburse(
        request_for("0010000000", "40802810800000000001", f"АЗ-{uuid4().hex[:8]}"),
        idempotency_key=f"dsb:{uuid4()}",
    )
    assert isinstance(stranger, SourceUnavailable)
    assert classify_failure(stranger) is Failure.CUSTOMER_NOT_FOUND

    not_owned = write.disburse(
        request_for(inn, "40802810800000009999", f"АЗ-{uuid4().hex[:8]}"),
        idempotency_key=f"dsb:{uuid4()}",
    )
    assert isinstance(not_owned, SourceUnavailable)
    assert classify_failure(not_owned) is Failure.ACCOUNT_PROBLEM

    bad = write.disburse(
        request_for(inn, "40802810800000009999", f"АЗ-{uuid4().hex[:8]}", amount_rub=0),
        idempotency_key=f"dsb:{uuid4()}",
    )
    assert isinstance(bad, SourceUnavailable) and bad.status_code == 422
    assert classify_failure(bad) is Failure.DEFECT
