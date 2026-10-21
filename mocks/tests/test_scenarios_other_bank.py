"""Стыковка T-123/T-125: кредиты нашего банка дополняют единственную карточку клиента."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from app.roles.bank_core.schemas import LoanBody
from tests.test_scenarios_other import base, checked, scenario


def test_bank_loans_merge_without_mutation_or_duplicate_on_repeated_expansion() -> None:
    spec = scenario(bank={"isCustomer": True})
    before = base(spec)
    loan = LoanBody(
        application_ref="SC-our-loan",
        contract_number="SC-contract",
        contract_uid="our-uid",
        product_code="WORKING_CAPITAL",
        amount_rub=100000,
        term_months=12,
        rate_percent=21,
        disbursed_at=date(2026, 1, 21),
    ).model_dump(mode="json", by_alias=True)
    before["bankLoans"] = [{"inn": before["identity"]["inn"], "body": {"loans": [loan]}}]
    saved = deepcopy(before)
    result = checked(spec, before)
    assert before == saved
    assert result["bankCore"]["loans"] == [loan]
    assert checked(spec, result)["bankCore"]["loans"] == [loan]


@pytest.mark.parametrize("personal", [False, True])
def test_bank_loans_require_business_customer(personal: bool) -> None:
    spec = scenario()
    before = base(spec)
    inn = before["identity"]["director"]["inn"] if personal else before["identity"]["inn"]
    before["bankLoans"] = [{"inn": inn, "body": {"loans": []}}]
    with pytest.raises(ValueError, match="компании|клиент"):
        checked(spec, before)
