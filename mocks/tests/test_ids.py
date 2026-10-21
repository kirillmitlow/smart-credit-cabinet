"""T-101: ИНН, ОГРН, КПП и счета — контрольные суммы, синтетический регион, детерминизм."""

from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.common import accounts, inn

SPEC_INNS = ["001234567887", "0017654322", "0015557771"]
SPEC_ACCOUNTS = ["40802810800000001234", "45406810000000000041"]


@pytest.mark.parametrize("value", SPEC_INNS)
def test_spec_inns_are_valid(value: str) -> None:
    assert inn.validate_inn(value) == value


@pytest.mark.parametrize(
    "value", ["", "123", "00123456788", "0017654323", "00176543 2", "abcdefghij"]
)
def test_invalid_inn_raises(value: str) -> None:
    with pytest.raises(inn.IdentifierError):
        inn.validate_inn(value)


@pytest.mark.parametrize("value", SPEC_ACCOUNTS)
def test_spec_accounts_have_valid_key(value: str) -> None:
    assert accounts.account_is_valid(accounts.OUR_BANK_BIK, value)


seeds = st.integers(min_value=0, max_value=2**32)


@given(seeds, st.booleans())
def test_generated_inn_is_valid_synthetic_and_deterministic(seed: int, individual: bool) -> None:
    first = inn.generate_inn(random.Random(seed), individual=individual)
    assert first == inn.generate_inn(random.Random(seed), individual=individual)
    assert inn.inn_is_valid(first)
    assert first.startswith(inn.SYNTHETIC_REGION)
    assert len(first) == (12 if individual else 10)


@given(seeds, st.booleans(), st.integers(min_value=1, max_value=9))
def test_changing_check_digit_breaks_inn(seed: int, individual: bool, delta: int) -> None:
    # Одна контрольная цифра mod 11 mod 10 ловит не любую замену в теле, но всегда — замену себя
    value = inn.generate_inn(random.Random(seed), individual=individual)
    broken = value[:-1] + str((int(value[-1]) + delta) % 10)
    assert not inn.inn_is_valid(broken)


@given(seeds, st.integers(min_value=2000, max_value=2026), st.booleans())
def test_generated_ogrn_matches_year_and_is_valid(seed: int, year: int, individual: bool) -> None:
    value = inn.generate_ogrn(random.Random(seed), year, individual=individual)
    assert inn.ogrn_is_valid(value)
    assert inn.ogrn_year(value) == year
    assert value[3:5] == inn.SYNTHETIC_REGION
    assert len(value) == (15 if individual else 13)
    broken = value[:-1] + str((int(value[-1]) + 1) % 10)
    assert not inn.ogrn_is_valid(broken)


def test_kpp_follows_inn() -> None:
    company_inn = "0017654322"
    kpp = inn.generate_kpp(company_inn)
    assert kpp == "001701001"
    assert inn.kpp_is_valid(kpp, company_inn)
    assert not inn.kpp_is_valid(kpp, "0015557771")
    assert not inn.kpp_is_valid("00170100")


def test_mask_hides_middle() -> None:
    assert inn.mask_inn("0017654322") == "0017****22"
    assert inn.mask_inn("001234567887") == "0012******87"
    assert inn.mask_inns_in_text("/api/v1/companies/0017654322") == "/api/v1/companies/0017****22"


@given(
    seeds,
    st.sampled_from([accounts.OUR_BANK_BIK, accounts.OTHER_BANK_BIK]),
    st.sampled_from(["40702", "40802", "45206", "45406"]),
    st.integers(min_value=0, max_value=19),
    st.integers(min_value=1, max_value=9),
)
def test_generated_account_is_valid_and_any_digit_change_breaks_it(
    seed: int, bik: str, balance: str, position: int, delta: int
) -> None:
    # Веса 7, 1, 3 взаимно просты с 10: замена любой одной цифры всегда меняет ключ
    value = accounts.generate_account(random.Random(seed), bik, balance)
    assert value == accounts.generate_account(random.Random(seed), bik, balance)
    assert value.startswith(balance + accounts.RUB)
    assert accounts.account_is_valid(bik, value)
    broken = value[:position] + str((int(value[position]) + delta) % 10) + value[position + 1 :]
    assert not accounts.account_is_valid(bik, broken)


def test_account_of_other_bank_does_not_validate_with_our_bik() -> None:
    value = accounts.make_account(accounts.OTHER_BANK_BIK, "40702", 1234567)
    assert accounts.account_is_valid(accounts.OTHER_BANK_BIK, value)
    assert not accounts.account_is_valid(accounts.OUR_BANK_BIK, value)


def test_account_mask_keeps_last_four() -> None:
    assert accounts.mask_account("40802810800000001234") == "****************1234"
