"""T-123: проверяем админ-контракт и экономический результат генерации."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.roles.bank_core.schemas import LoanBody
from app.roles.bki.admin import BkiAdminHandler
from app.roles.bki.schemas import BkiSubjectBody
from app.roles.scenarios.bki_expand import expand_bki
from app.roles.scenarios.credit_math import (
    annuity,
    external_balance,
    implied_rate,
    money,
    schedule,
)
from app.roles.scenarios.credit_uid import contract_uid
from app.roles.scenarios.expand import resolved_spec
from app.roles.scenarios.identity import expand_identity
from app.roles.scenarios.schemas import ScenarioSpec

TODAY = date(2026, 10, 20)


def scenario(**kwargs: Any) -> tuple[ScenarioSpec, dict[str, Any]]:
    spec = ScenarioSpec.model_validate(
        {"title": "БКИ", "company": {"form": "LLC", "ageMonths": 120}, **kwargs}
    )
    spec = resolved_spec(spec)
    return spec, expand_identity(spec, "bki-test", TODAY, set())["identity"]


def run(**kwargs: Any) -> dict[str, Any]:
    spec, identity = scenario(**kwargs)
    before = deepcopy(identity)
    result = expand_bki(spec, identity, "bki-test", TODAY)
    assert identity == before
    for item in result["bki"]:
        body = BkiSubjectBody.model_validate(item["body"])
        BkiAdminHandler().check(item["inn"], body)
    for group in result["bankLoans"]:
        for loan in group["body"]["loans"]:
            LoanBody.model_validate(loan)
    return result


@pytest.mark.parametrize(
    ("amount", "term", "rate", "payment", "balance6"),
    [
        (500000, 12, "24", 47280, 264833),
        (8000000, 12, "21", 744910, None),
        (8000000, 36, "19.5", 295274, None),
    ],
)
def test_vectors_30_16(
    amount: int, term: int, rate: str, payment: int, balance6: int | None
) -> None:
    rows = schedule(amount, term, Decimal(rate), TODAY)
    assert rows[0].payment == payment
    assert sum(row.principal for row in rows) == amount
    assert rows[-1].balance == 0
    if balance6 is not None:
        assert rows[5].balance == balance6
    assert all(row.day.weekday() < 5 for row in rows)


def test_bullet_holds_principal_until_final_payment() -> None:
    rows = schedule(300000, 12, Decimal(24), TODAY, bullet=True)
    assert all(row.balance == 300000 and row.payment == 6000 for row in rows[:-1])
    assert rows[-1].principal == 300000


def test_external_vector_ready_for_t124() -> None:
    assert money(annuity(3000000, 36, Decimal(21)), 100) == 113000
    assert external_balance(3000000, 36, Decimal(21), 28) == 837000


@given(amount=st.integers(100000, 50000000), term=st.integers(1, 120), rate=st.integers(0, 60))
def test_schedule_invariants(amount: int, term: int, rate: int) -> None:
    rows = schedule(amount, term, Decimal(rate), TODAY)
    assert sum(row.principal for row in rows) == amount
    assert rows[-1].balance == 0
    assert all(row.principal >= 0 and row.interest >= 0 for row in rows)
    assert [row.balance for row in rows] == sorted((row.balance for row in rows), reverse=True)
    assert all(row.payment <= amount + row.interest for row in rows)


def test_history_zero_omits_subject() -> None:
    assert run(bki={"company": {"historyYears": 0}}) == {"bki": [], "bankLoans": []}


def test_history_uses_closed_loan_and_caps_company_age() -> None:
    body = run(company={"form": "LLC", "ageMonths": 18}, bki={"company": {"historyYears": 10}})[
        "bki"
    ][0]["body"]
    loan = body["obligations"][0]
    assert loan["openedAt"] == "2025-04-20"
    assert loan["closedAt"] <= TODAY.isoformat()
    assert loan["balanceRub"] == 0
    assert loan["status"] == "CLOSED"


def test_director_owner_merge_and_multiple_old_obligations() -> None:
    old = {"kind": "CONSUMER_LOAN", "amountRub": 300000, "openedAt": "-4y", "closedAt": "-2y"}
    card = {
        "kind": "CREDIT_CARD",
        "limitRub": 100000,
        "balanceRub": 0,
        "openedAt": "-3y",
        "termMonths": 60,
    }
    result = run(bki={"director": {"closedLoans": [old]}, "owner": {"activeLoans": [card]}})
    assert len(result["bki"]) == 1
    loans = result["bki"][0]["body"]["obligations"]
    assert len(loans) == 2
    assert all(loan["openedAt"] < "2024-10-20" for loan in loans)


def test_ip_owner_company_merge() -> None:
    result = run(
        company={"form": "IP", "ageMonths": 120},
        bki={"company": {"historyYears": 3}, "owner": {"historyYears": 3}},
    )
    assert len(result["bki"]) == 1
    assert result["bki"][0]["body"]["subject"]["type"] == "PERSON"


@pytest.mark.parametrize("kind", ["CREDIT_LINE", "OVERDRAFT", "CREDIT_CARD"])
def test_limit_payment_is_five_percent_of_used_balance(kind: str) -> None:
    loan = run(
        bki={"company": {"activeLoans": [{"kind": kind, "limitRub": 300000, "balanceRub": 90000}]}}
    )["bki"][0]["body"]["obligations"][0]
    assert loan["amountRub"] is None
    assert loan["monthlyPaymentRub"] == 4500
    assert loan["limitRub"] == 300000
    assert loan["balanceRub"] == 90000


def test_our_bank_uid_terms_and_exact_payment() -> None:
    result = run(
        bank={"isCustomer": True},
        bki={
            "company": {
                "activeLoans": [
                    {
                        "kind": "LOAN",
                        "amountRub": 500000,
                        "termMonths": 12,
                        "ratePercent": 24,
                        "openedAt": "-6M",
                        "ourBank": True,
                    }
                ]
            }
        },
    )
    loan = result["bki"][0]["body"]["obligations"][0]
    bank = result["bankLoans"][0]["body"]["loans"][0]
    assert bank["contractUid"] == loan["uid"]
    assert bank["amountRub"] == loan["amountRub"] == 500000
    assert bank["disbursedAt"] == loan["openedAt"]
    assert loan["monthlyPaymentRub"] == 47280
    assert loan["balanceRub"] == 264833


def test_uid_is_deterministic_version_one_with_weighted_checksum() -> None:
    uid = contract_uid("code", "0012345673", "active-0")
    assert uid == contract_uid("code", "0012345673", "active-0")
    assert uid != contract_uid("code", "0012345673", "active-1")
    root, check = uid.rsplit("-", 1)
    parsed = UUID(root)
    assert parsed.version == 1
    assert int(check, 16) == sum(int(c, 16) * (n % 10 + 1) for n, c in enumerate(parsed.hex)) % 16


def test_repeated_expansion_and_relative_dates() -> None:
    spec, identity = scenario(
        bki={"company": {"activeLoans": [{"kind": "LOAN", "amountRub": 1000000}]}}
    )
    first = expand_bki(spec, identity, "code", TODAY)
    assert first == expand_bki(spec, identity, "code", TODAY)
    later = expand_bki(spec, identity, "code", date(2027, 10, 20))
    a, b = [x["bki"][0]["body"]["obligations"][0] for x in (first, later)]
    assert a["uid"] == b["uid"]
    assert b["openedAt"] == "2026-10-20"


def test_monthly_load_synthesizes_one_loan() -> None:
    obligations = run(bki={"company": {"monthlyPaymentsRub": 560000}})["bki"][0]["body"][
        "obligations"
    ]
    assert len(obligations) == 1
    assert obligations[0]["monthlyPaymentRub"] == 560000


def test_rate_is_solved_from_payment() -> None:
    rate = implied_rate(500000, 12, 47280)
    assert abs(rate - Decimal(24)) < Decimal("0.002")
    assert money(annuity(500000, 12, rate)) == 47280


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"bki": {"company": {"historyYears": 0, "monthlyPaymentsRub": 1000}}}, "historyYears"),
        ({"bki": {"director": {"historyYears": 3}, "owner": {"historyYears": 5}}}, "противоречат"),
        ({"company": {"form": "JSC"}, "bki": {"owner": {"historyYears": 3}}}, "нет такого"),
        ({"bki": {"company": {"currentOverdueDays": 1}}}, "activeLoans"),
        (
            {
                "bki": {
                    "company": {
                        "activeLoans": [{"kind": "CREDIT_LINE", "limitRub": 10, "balanceRub": 11}]
                    }
                }
            },
            "balanceRub",
        ),
        (
            {
                "bki": {
                    "company": {
                        "activeLoans": [{"kind": "LOAN", "amountRub": 100000, "openedAt": "+1M"}]
                    }
                }
            },
            "будущем",
        ),
        (
            {
                "company": {"form": "LLC", "ageMonths": 12},
                "bki": {
                    "company": {
                        "activeLoans": [
                            {
                                "kind": "LOAN",
                                "amountRub": 100000,
                                "openedAt": "-2y",
                                "termMonths": 60,
                            }
                        ]
                    }
                },
            },
            "регистрации",
        ),
        (
            {
                "bki": {
                    "company": {
                        "activeLoans": [{"kind": "LOAN", "amountRub": 100000, "ourBank": True}]
                    }
                }
            },
            "isCustomer",
        ),
        (
            {
                "bank": {"isCustomer": True},
                "bki": {
                    "owner": {
                        "activeLoans": [{"kind": "LOAN", "amountRub": 100000, "ourBank": True}]
                    }
                },
            },
            "физлица",
        ),
        (
            {
                "bki": {
                    "company": {
                        "activeLoans": [
                            {"kind": "LOAN", "amountRub": 100000, "monthlyPaymentRub": 10}
                        ]
                    }
                }
            },
            "несовместим",
        ),
    ],
)
def test_invalid_inputs_are_rejected(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        run(**kwargs)


def test_configurable_default_rate_and_limit_payment() -> None:
    from app.roles.scenarios.bki_loans import CreditDefaults

    spec, identity = scenario(
        bki={
            "company": {
                "activeLoans": [
                    {"kind": "CREDIT_CARD", "limitRub": 300000, "balanceRub": 90000},
                    {"kind": "LOAN", "amountRub": 500000, "termMonths": 12},
                ]
            }
        }
    )
    output = expand_bki(
        spec, identity, "code", TODAY, defaults=CreditDefaults(Decimal(24), Decimal(7))
    )
    loans = output["bki"][0]["body"]["obligations"]
    assert loans[0]["monthlyPaymentRub"] == 6300
    assert loans[1]["monthlyPaymentRub"] == 47300


@pytest.mark.parametrize(
    "preset", ["IP_HEALTHY", "LLC_HEALTHY", "LLC_HIGH_DEBT_LOAD", "STARTUP", "SELF_EMPLOYED"]
)
def test_clean_presets_satisfy_admin_contract(preset: str) -> None:
    run(preset=preset)


@pytest.mark.parametrize("kind", ["CREDIT_LINE", "OVERDRAFT"])
def test_our_bank_revolving_keeps_uid_and_conditions(kind: str) -> None:
    result = run(
        bank={"isCustomer": True},
        bki={
            "company": {
                "activeLoans": [
                    {"kind": kind, "limitRub": 300000, "balanceRub": 90000, "ourBank": True},
                ]
            }
        },
    )
    loan = result["bki"][0]["body"]["obligations"][0]
    bank = result["bankLoans"][0]["body"]["loans"][0]
    assert bank["contractUid"] == loan["uid"]
    assert bank["amountRub"] == loan["balanceRub"] == 90000
    assert bank["limitRub"] == loan["limitRub"] == 300000
    assert bank["repaymentType"] == "REVOLVING"


def test_explicit_bullet_closed_loan() -> None:
    loan = run(
        bki={
            "company": {
                "closedLoans": [
                    {
                        "kind": "LOAN",
                        "amountRub": 3000000,
                        "openedAt": "-3y",
                        "closedAt": "-2y",
                        "repayment": "BULLET",
                        "secured": True,
                    },
                ]
            }
        }
    )["bki"][0]["body"]["obligations"][0]
    assert loan["plannedCloseAt"] == loan["closedAt"] == "2024-10-20"
    assert loan["monthlyPaymentRub"] == 52500
    assert loan["balanceRub"] == 0
    assert loan["secured"] is True


def test_ip_keeps_personal_credit_history_predating_business() -> None:
    result = run(
        company={"form": "IP", "ageMonths": 42},
        bki={
            "company": {"historyYears": 8},
            "owner": {
                "closedLoans": [
                    {
                        "kind": "CONSUMER_LOAN",
                        "amountRub": 300000,
                        "openedAt": "-8y",
                        "closedAt": "-6y",
                    }
                ]
            },
        },
    )
    assert len(result["bki"]) == 1
    body = result["bki"][0]["body"]
    assert body["subject"]["type"] == "PERSON"
    assert len(body["obligations"]) == 1
    assert body["obligations"][0]["openedAt"] == "2018-10-20"
    assert body["obligations"][0]["closedAt"] == "2020-10-20"


@pytest.mark.parametrize("form", ["LLC", "JSC"])
def test_legal_entity_cannot_have_credit_predating_registration(form: str) -> None:
    with pytest.raises(ValueError, match="раньше|до.*регистрации"):
        run(
            company={"form": form, "ageMonths": 42},
            bki={
                "company": {
                    "historyYears": 8,
                    "closedLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 300000,
                            "openedAt": "-8y",
                            "closedAt": "-6y",
                        }
                    ],
                }
            },
        )
