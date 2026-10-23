"""Independent fixed input: syntax coverage, not a claim of economic reconciliation."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from app.modules.documents.statement_format import money, read_statement
from app.shared.errors import AppError

pytestmark = pytest.mark.unit
FIXTURE = Path(__file__).parents[1] / "fixtures/statements/manual-good.txt"


@pytest.mark.parametrize("encoding", ["utf-8", "cp1251", "utf-8-sig"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_manual_syntax_preserves_exact_posted_dates_amounts_and_purpose(
    encoding: str, newline: str
) -> None:
    content = FIXTURE.read_text().replace("\n", newline).encode(encoding)
    result = read_statement(content)
    assert (result.start, result.end) == (date(2026, 1, 1), date(2026, 3, 31))
    assert len(result.accounts) == 1
    assert result.accounts[0].received == Decimal("601.47")
    assert result.accounts[0].spent == Decimal("200.30")
    assert len(result.payments) == 6
    first = result.payments[0]
    assert first.amount == Decimal("100.49")
    assert first.created == date(2026, 1, 9)
    assert first.credited == date(2026, 1, 10)
    assert first.debited is None
    assert first.fields["НазначениеПлатежа"] == "Оплата по договору: сумма=с НДС"
    assert result.encoding == ("windows-1251" if encoding == "cp1251" else "utf-8")
    with pytest.raises(TypeError):
        first.fields["Сумма"] = "1"  # type: ignore[index]


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("ВерсияФормата=1.03", "ВерсияФормата=1.02", "UNSUPPORTED_VERSION"),
        ("Кодировка=Windows", "Кодировка=DOS", "BAD_ENCODING"),
        ("КонецФайла", "", "MALFORMED_STATEMENT"),
        ("КонецРасчСчет", "КонецДокумента", "MALFORMED_STATEMENT"),
        ("Сумма=100.49", "Сумма=100.49\nСумма=100.49", "DUPLICATE_FIELD"),
        ("Сумма=100.49", "Сумма=-100.49", "INVALID_AMOUNT"),
        ("Дата=09.01.2026", "Дата=31.02.2026", "INVALID_DATE"),
    ],
)
def test_invalid_envelopes_fail_without_echoing_the_source(old: str, new: str, code: str) -> None:
    with pytest.raises(AppError) as error:
        read_statement(FIXTURE.read_text().replace(old, new).encode())
    assert error.value.code == code
    assert "Оплата по договору" not in str(error.value)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e9", "1.001", "-1", "9" * 1000])
def test_amounts_are_bounded_exact_and_finite(value: str) -> None:
    with pytest.raises(AppError):
        money(value)


@given(st.binary(max_size=10_000))
def test_arbitrary_bytes_have_only_controlled_errors(content: bytes) -> None:
    try:
        read_statement(content)
    except AppError:
        pass
