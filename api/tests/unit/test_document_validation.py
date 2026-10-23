"""T-332: detect contents, enforce early limits, do not trust client names or MIME."""

import io
from collections.abc import AsyncIterator

import pytest
from pypdf import PdfWriter
from starlette.requests import Request

from app.modules.documents.uploads import read_upload
from app.modules.documents.validation import clean_filename, decode_statement, validate_content
from app.shared.errors import AppError

pytestmark = pytest.mark.unit


def pdf_bytes(pages: int = 1, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("test-only")
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


@pytest.mark.parametrize("encoding", ["cp1251", "utf-8", "utf-8-sig"])
def test_statement_encoding_and_digest(encoding: str) -> None:
    content = "1CClientBankExchange\r\nВерсияФормата=1.03\r\nКонецФайла\r\n".encode(encoding)
    mime, digest = validate_content(content, "BANK_STATEMENT_1C")
    assert mime.startswith("text/plain; charset=")
    assert len(digest) == 64
    assert decode_statement(content).endswith("КонецФайла\r\n")


@pytest.mark.parametrize(
    ("content", "kind", "code"),
    [
        (b"", "BANK_STATEMENT_1C", "EMPTY_FILE"),
        (b"%PDF-1.7", "BANK_STATEMENT_1C", "UNSUPPORTED_FORMAT"),
        (b"1CClientBankExchange\x00\xff", "BANK_STATEMENT_1C", "BAD_ENCODING"),
        (b"1CClientBankExchangeBAD\n", "BANK_STATEMENT_1C", "UNSUPPORTED_FORMAT"),
        (b"abc", "CONTRACT", "UNSUPPORTED_FORMAT"),
        (b"anything", "CREDIT_AGREEMENT", "UNSUPPORTED_DOCUMENT_KIND"),
        (b"1CClientBankExchange\n" + b"a\n" * 100_000, "BANK_STATEMENT_1C", "TOO_MANY_LINES"),
    ],
)
def test_bad_uploads_have_specific_codes(content: bytes, kind: str, code: str) -> None:
    with pytest.raises(AppError) as caught:
        validate_content(content, kind)
    assert caught.value.code == code


def test_exact_line_limit_is_accepted() -> None:
    content = b"1CClientBankExchange\n" + b"a\n" * 99_999
    assert validate_content(content, "BANK_STATEMENT_1C")[0].startswith("text/plain")


@pytest.mark.parametrize(
    ("pages", "encrypted", "code"), [(31, False, "PDF_TOO_LONG"), (1, True, "PDF_ENCRYPTED")]
)
def test_pdf_limits(pages: int, encrypted: bool, code: str) -> None:
    with pytest.raises(AppError) as caught:
        validate_content(pdf_bytes(pages, encrypted=encrypted), "CONTRACT")
    assert caught.value.code == code


def test_pdf_is_detected_from_bytes() -> None:
    assert validate_content(pdf_bytes(), "CONTRACT")[0] == "application/pdf"
    with pytest.raises(AppError) as caught:
        validate_content(b"%PDF-1.7 broken", "CONTRACT")
    assert caught.value.code == "UNSUPPORTED_FORMAT"


def test_size_and_filename() -> None:
    with pytest.raises(AppError) as caught:
        validate_content(b"a" * 100, "CONTRACT", max_bytes=99)
    assert (caught.value.status, caught.value.code) == (413, "FILE_TOO_LARGE")
    assert clean_filename("../../private\\secret\r\n\x00.txt") == "secret.txt"
    assert clean_filename("...\x00") == "document"


def multipart_request(body: bytes, *, chunk_size: int = 13) -> Request:
    offset = 0

    async def receive() -> dict[str, object]:
        nonlocal offset
        chunk = body[offset : offset + chunk_size]
        offset += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": offset < len(body)}

    return Request(
        {"type": "http", "headers": [(b"content-type", b"multipart/form-data; boundary=abc")]},
        receive,
    )


async def test_streaming_reader_survives_split_headers_and_file() -> None:
    body = (
        b'--abc\r\nContent-Disposition: form-data; name="kind"\r\n\r\nBANK_STATEMENT_1C\r\n'
        b'--abc\r\nContent-Disposition: form-data; name="file"; filename="test.txt"\r\n\r\n'
        b"1CClientBankExchange\nabc=def\r\n--abc--\r\n"
    )
    parsed = await read_upload(multipart_request(body))
    assert parsed.filename == "test.txt"
    assert parsed.fields == {"kind": "BANK_STATEMENT_1C"}
    assert parsed.content == b"1CClientBankExchange\nabc=def"


async def test_streaming_limit_stops_without_reading_rest() -> None:
    chunks_read = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal chunks_read
        yield b'--abc\r\nContent-Disposition: form-data; name="file"; filename="x.pdf"\r\n\r\n'
        for _ in range(1000):
            chunks_read += 1
            yield b"x" * 64

    request = multipart_request(b"")
    request.stream = chunks  # type: ignore[method-assign]
    with pytest.raises(AppError) as caught:
        await read_upload(request, max_bytes=100)
    assert caught.value.code == "FILE_TOO_LARGE"
    assert chunks_read == 2
