"""Independent turnover oracle: exact cents, ownership, duplicate control and source provenance."""

import json
from dataclasses import replace
from datetime import date
from decimal import localcontext
from hashlib import sha256
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.documents import parse_statement, validate_statement_set
from app.modules.documents.statement_parser import rounded_rubles
from app.shared.errors import AppError
from tests.fixtures.statements.cases import (
    INN,
    OTHER,
    OWN,
    SECOND,
    account,
    payment,
    statement,
)

pytestmark = pytest.mark.unit
AS_OF = date(2026, 4, 1)
FIXTURES = Path(__file__).parents[1] / "fixtures/statements"


def parse(content: bytes):
    return parse_statement(content, INN, as_of=AS_OF)


def test_fixed_manual_oracle_and_source_are_json_safe(no_network: None) -> None:
    content = (FIXTURES / "manual-good.txt").read_bytes()
    result = parse(content)
    assert result.file_sha256 == sha256(content).hexdigest()
    assert [(m.month, m.incoming_rub, m.outgoing_rub) for m in result.complete_months] == [
        ("2026-01", 100, 50),
        ("2026-02", 200, 70),
        ("2026-03", 300, 80),
    ]
    assert result.accounts[0].closing_kopecks == 1_040_117
    assert sum(m.incoming_kopecks for m in result.months) == 60_147
    assert result.payment_count == 6
    assert result.duplicate_count == 0
    data = result.as_dict()
    assert json.loads(json.dumps(data))["provenance"]["completeMonthCount"] == 3
    assert data["requiresReview"] is True
    assert data["excludedReceipts"] == []
    assert "UNCLASSIFIED_RECEIPTS" in result.warnings
    assert len(data["ambiguousReceipts"]) == 3
    assert "НазначениеПлатежа" not in json.dumps(data, ensure_ascii=False)


@pytest.mark.parametrize(
    ("filename", "code"),
    [("manual-foreign-inn.txt", "INN_MISMATCH"), ("manual-bad-balance.txt", "BALANCE_MISMATCH")],
)
def test_independent_bad_files(filename: str, code: str) -> None:
    with pytest.raises(AppError) as error:
        parse((FIXTURES / filename).read_bytes())
    assert error.value.code == code


def test_round_once_after_aggregation_and_ignore_decimal_context() -> None:
    data = statement(
        [account(incoming="0.50", closing="10000.50")],
        [payment("a", "0.25"), payment("b", "0.25")],
    )
    with localcontext() as context:
        context.prec = 2
        result = parse(data)
    assert result.months[0].incoming_kopecks == 50
    assert result.months[0].incoming_rub == 1  # Not round(.25) + round(.25).
    assert rounded_rubles(-50) == -1


def test_both_legs_of_own_transfer_remain_cash_movement_but_are_excluded() -> None:
    data = statement(
        [
            account(incoming="100.00", outgoing="30.00", closing="10070.00"),
            account(SECOND, incoming="30.00", closing="10030.00"),
        ],
        [
            payment("sale", "100.00"),
            payment(
                "own",
                "30.00",
                payer=OWN,
                recipient=SECOND,
                payer_inn=INN,
                recipient_inn=INN,
                debited="10.01.2026",
            ),
        ],
        numbers=(OWN, SECOND),
    )
    result = parse(data)
    january = result.months[0]
    assert (january.incoming_kopecks, january.outgoing_kopecks) == (13_000, 3_000)
    assert (january.internal_incoming_kopecks, january.internal_outgoing_kopecks) == (3_000, 3_000)
    assert january.unclassified_incoming_kopecks == 10_000
    assert len(result.exclusions) == 1
    assert result.exclusions[0].amount_kopecks == 3_000
    assert result.exclusions[0].reason == "OWN_TRANSFER"


def test_transfer_with_the_same_account_keeps_both_directions() -> None:
    result = parse(
        statement(
            [account(incoming="10.00", outgoing="10.00")],
            [payment("self", "10.00", payer=OWN, payer_inn=INN, debited="10.01.2026")],
        )
    )
    assert (result.months[0].incoming_kopecks, result.months[0].outgoing_kopecks) == (1000, 1000)
    assert len(result.exclusions) == 1


def test_duplicate_document_and_dot_comma_do_not_double_movement() -> None:
    document = payment("same", "100.00")
    result = parse(
        statement(
            [account(incoming="100.00", closing="10100.00")],
            [document, document.replace("Сумма=100.00", "Сумма=100,00")],
        )
    )
    assert result.months[0].incoming_rub == 100
    assert result.payment_count == 1
    assert result.duplicate_count == 1


@pytest.mark.parametrize("change", ["purpose", "counterparty", "posted", "kind"])
def test_conflicting_document_key_never_silently_wins(change: str) -> None:
    document = payment("same", "100.00")
    other = {
        "purpose": document.replace("Оплата по договору", "Выдача кредита"),
        "kind": document.replace(
            "СекцияДокумент=Платежное поручение", "СекцияДокумент=Банковский ордер"
        ),
        "counterparty": document.replace(OTHER, "40702810300000005679"),
        "posted": document.replace("ДатаПоступило=10.01", "ДатаПоступило=11.01"),
    }[change]
    with pytest.raises(AppError) as error:
        parse(statement([account(incoming="200.00", closing="10200.00")], [document, other]))
    assert error.value.code == "CONFLICTING_DUPLICATE"


def test_posted_date_not_instruction_date_selects_month() -> None:
    result = parse(
        statement(
            [account(incoming="10.00", closing="10010.00")],
            [payment("earlier", "10.00", created="31.12.2025", credited="01.02.2026")],
        )
    )
    assert [month.incoming_rub for month in result.months] == [0, 10, 0]


def test_unposted_instruction_never_becomes_turnover() -> None:
    result = parse(statement([account()], [payment("pending", "500.00", credited="")]))
    assert all(month.incoming_kopecks == 0 for month in result.months)
    assert result.unposted_count == 1
    assert "UNPOSTED_DOCUMENTS" in result.warnings


@pytest.mark.parametrize(
    "purpose", ["Выдача кредита", "Взнос учредителя", "Возврат средств", "Оплата товаров"]
)
def test_purpose_alone_never_confirms_business_revenue(purpose: str) -> None:
    result = parse(
        statement(
            [account(incoming="100.00", closing="10100.00")],
            [payment("x", "100.00", purpose=purpose)],
        )
    )
    assert len(result.ambiguous_receipts) == 1
    assert result.months[0].unclassified_incoming_kopecks == 10_000
    assert result.as_dict()["requiresReview"] is True
    assert "revenueRub" not in result.as_dict()


def test_optional_account_fields_are_not_fabricated_as_verified() -> None:
    section = account(incoming="100.00", closing="10100.00")
    section = "\n".join(
        line
        for line in section.splitlines()
        if not line.startswith(
            (
                "ДатаКонца=",
                "ВсегоПоступило=",
                "ВсегоСписано=",
                "КонечныйОстаток=",
            )
        )
    )
    result = parse(statement([section], [payment("x", "100.00")]))
    assert result.accounts[0].closing_kopecks == 1_010_000
    assert result.accounts[0].controls_complete is False
    assert "CONTROL_TOTALS_MISSING" in result.warnings


def test_overdraft_and_adjacent_sections_have_exact_continuity() -> None:
    result = parse(
        statement(
            [
                account(end="31.01.2026", opening="-10.00", incoming="5.00", closing="-5.00"),
                account(start="01.02.2026", opening="-5.00", closing="-5.00"),
            ],
            [payment("x", "5.00")],
        )
    )
    assert result.accounts[1].opening_kopecks == result.accounts[0].closing_kopecks == -500


@pytest.mark.parametrize(
    ("sections", "code"),
    [
        ([account(end="31.01.2026"), account(start="31.01.2026")], "OVERLAPPING_PERIODS"),
        ([account(end="31.01.2026"), account(start="02.02.2026")], "INCOMPLETE_PERIOD"),
        (
            [
                account(end="31.01.2026"),
                account(start="01.02.2026", opening="9999.99", closing="9999.99"),
            ],
            "BALANCE_MISMATCH",
        ),
    ],
)
def test_bad_section_intervals_and_continuity(sections: list[str], code: str) -> None:
    with pytest.raises(AppError) as error:
        parse(statement(sections, [payment("zero", "0.00")]))
    assert error.value.code == code


def test_partial_months_and_year_boundary_are_explicit() -> None:
    content = statement(
        [account(start="15.11.2025", end="15.03.2026", incoming="10.00", closing="10010.00")],
        [payment("x", "10.00", created="01.03.2026", credited="10.03.2026")],
        start="15.11.2025",
        end="15.03.2026",
    )
    result = parse_statement(content, INN, as_of=date(2026, 3, 16))
    assert [month.month for month in result.complete_months] == ["2025-12", "2026-01", "2026-02"]
    assert result.months[-1].incoming_rub == 10
    assert not result.months[-1].complete
    assert not result.months[0].complete


def test_shorter_account_coverage_cannot_create_fake_zero_months() -> None:
    content = statement(
        [account(), account(SECOND, start="01.02.2026")],
        [
            payment("a", "0.00"),
            payment("b", "0.00", recipient=SECOND, created="09.02.2026", credited="10.02.2026"),
        ],
        numbers=(OWN, SECOND),
    )
    with pytest.raises(AppError) as error:
        parse(content)
    assert error.value.code == "PERIOD_TOO_SHORT"


@pytest.mark.parametrize(
    ("transform", "code"),
    [
        (lambda text: text.replace(f"ПолучательИНН={INN}", "ПолучательИНН="), "OWNER_UNCONFIRMED"),
        (
            lambda text: text.replace("ДатаПоступило=10.01.2026", "ДатаПоступило=10.04.2026"),
            "OPERATION_OUTSIDE_PERIOD",
        ),
        (lambda text: text.replace(OWN, SECOND, 1), "OWNER_UNCONFIRMED"),
    ],
)
def test_ownership_and_posted_window_errors(transform, code: str) -> None:
    with pytest.raises(AppError) as error:
        parse(
            transform(statement([account()], [payment("zero", "0.00")]).decode("cp1251")).encode(
                "cp1251"
            )
        )
    assert error.value.code == code


def test_future_and_current_month_do_not_extend_history() -> None:
    content = statement([account()], [payment("zero", "0.00")])
    with pytest.raises(AppError) as error:
        parse_statement(content, INN, as_of=date(2026, 3, 31))
    assert error.value.code == "PERIOD_TOO_SHORT"
    with pytest.raises(AppError) as error:
        parse_statement(content, INN, as_of=date(2026, 3, 30))
    assert error.value.code == "INVALID_PERIOD"


def test_file_set_deduplicates_originals_and_rejects_overlaps() -> None:
    content = (FIXTURES / "manual-good.txt").read_bytes()
    first = parse(content)
    assert validate_statement_set([first, first]) == (first,)
    # Same period, different original: no blind addition, even if the visible totals match.
    second = parse(content.replace(b"\n", b"\r\n"))
    with pytest.raises(AppError) as error:
        validate_statement_set([first, second])
    assert error.value.code == "OVERLAPPING_PERIODS"
    with pytest.raises(AppError) as error:
        validate_statement_set([first, replace(second, inn="0017654322")])
    assert error.value.code == "INN_MISMATCH"


@given(st.binary(max_size=20_000))
def test_public_parser_does_not_crash_on_arbitrary_bytes(content: bytes) -> None:
    try:
        parse(content)
    except AppError:
        pass


def test_sets_allow_disjoint_accounts_and_check_adjacent_balance() -> None:
    first = parse(
        statement(
            [account(incoming="100.00", closing="10100.00")],
            [payment("one", "100.00")],
        )
    )
    different_account = parse(
        statement(
            [account(SECOND, incoming="100.00", closing="10100.00")],
            [payment("two", "100.00", recipient=SECOND)],
            numbers=(SECOND,),
        )
    )
    assert len(validate_statement_set([first, different_account])) == 2
    second_content = statement(
        [account(start="01.04.2026", end="30.06.2026", opening="10100.00", closing="10100.00")],
        [payment("later", "0.00", created="09.04.2026", credited="10.04.2026")],
        start="01.04.2026",
        end="30.06.2026",
    )
    second = parse_statement(second_content, INN, as_of=date(2026, 7, 1))
    assert validate_statement_set([first, second]) == (first, second)
    wrong = parse_statement(
        second_content.replace(b"10100.00", b"10101.00"), INN, as_of=date(2026, 7, 1)
    )
    with pytest.raises(AppError) as error:
        validate_statement_set([first, wrong])
    assert error.value.code == "BALANCE_MISMATCH"


@pytest.mark.parametrize("encoding", ["cp1251", "utf-8", "cp866"])
def test_actual_dos_profile_is_rejected(encoding: str) -> None:
    text = statement([account()], [payment("x", "0.00")]).decode("cp1251")
    with pytest.raises(AppError) as error:
        parse(text.replace("Кодировка=Windows", "Кодировка=DOS").encode(encoding))
    assert error.value.code == "BAD_ENCODING"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"%PDF-1.7\nbogus", "UNSUPPORTED_FORMAT"),
        (b"1CClientBankExchange\n" + b"a" * (5 * 1024 * 1024), "FILE_TOO_LARGE"),
        (b"1CClientBankExchange\n" + b"a\n" * 100_000, "TOO_MANY_LINES"),
    ],
)
def test_public_limits_and_pdf_masquerade(content: bytes, code: str) -> None:
    with pytest.raises(AppError) as error:
        parse(content)
    assert error.value.code == code


def test_explicit_utf8_does_not_accept_cp1251_and_bad_bytes() -> None:
    content = statement([account()], [payment("x", "0.00")])
    text = content.decode("cp1251").replace("Кодировка=Windows", "Кодировка=UTF-8")
    with pytest.raises(AppError) as error:
        parse(text.encode("cp1251"))
    assert error.value.code == "BAD_ENCODING"
    with pytest.raises(AppError) as error:
        parse(content + b"\x98")
    assert error.value.code == "BAD_ENCODING"


@given(st.integers(min_value=0, max_value=10**12))
def test_cent_conservation_and_idempotent_duplicate(amount_cents: int) -> None:
    amount = f"{amount_cents // 100}.{amount_cents % 100:02}"
    document = payment("one", amount)
    content = statement(
        [account(opening="0", incoming=amount, closing=amount)],
        [document, document],
    )
    result = parse(content)
    assert result.accounts[0].closing_kopecks == amount_cents
    assert result.months[0].incoming_kopecks == amount_cents
    assert result.months[0].outgoing_kopecks == 0
    assert result.duplicate_count == 1


@given(st.text(max_size=100))
def test_valid_envelope_with_arbitrary_money_has_only_controlled_errors(value: str) -> None:
    content = statement([account()], [payment("mutated", "0.00")], encoding="utf-8")
    # Reach the parser's inner fields, rather than fuzzing only the file signature.
    content = content.replace(
        "\nСумма=0.00".encode(), ("\nСумма=" + value).encode("utf-8", errors="surrogatepass")
    )
    try:
        parse(content)
    except AppError:
        pass
