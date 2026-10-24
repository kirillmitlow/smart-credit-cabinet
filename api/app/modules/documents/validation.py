"""Content detection and bounded validation, independent of filename/Content-Type."""

import io
import re
import unicodedata
from hashlib import sha256

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.shared.errors import AppError

STATEMENT_LIMIT = 5 * 1024 * 1024
PDF_LIMIT = 10 * 1024 * 1024
UPLOAD_KINDS = frozenset({"BANK_STATEMENT_1C", "FINANCIALS", "CONTRACT", "OTHER"})


def clean_filename(value: str) -> str:
    # Display only; also safe in Content-Disposition after RFC 5987 encoding.
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1]
    leaf = "".join(c for c in leaf if not unicodedata.category(c).startswith("C"))
    return leaf.strip(" .")[:200] or "document"


def decode_statement(content: bytes) -> str:
    candidates: tuple[str, ...]
    if content.startswith(b"\xef\xbb\xbf"):
        candidates = ("utf-8-sig",)
    else:
        # UTF-8 first avoids mistaking Cyrillic UTF-8 bytes for valid cp1251 mojibake.
        candidates = ("utf-8", "cp1251")
    for encoding in candidates:
        try:
            result = content.decode(encoding, errors="strict")
        except UnicodeError:
            continue
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029]", result):
            continue
        if len(result.splitlines()) > 100_000:
            raise AppError(422, "TOO_MANY_LINES", "В выписке больше 100 000 строк")
        return result
    raise AppError(422, "BAD_ENCODING", "Сохраните выписку в Windows-1251 или UTF-8")


def validate_content(content: bytes, kind: str, max_bytes: int = PDF_LIMIT) -> tuple[str, str]:
    if not content:
        raise AppError(422, "EMPTY_FILE", "Файл пуст")
    if len(content) > max_bytes:
        raise AppError(413, "FILE_TOO_LARGE", "Размер файла превышает лимит")
    if kind not in UPLOAD_KINDS:
        raise AppError(422, "UNSUPPORTED_DOCUMENT_KIND", "Такой документ нельзя загрузить")
    if kind == "BANK_STATEMENT_1C":
        if len(content) > STATEMENT_LIMIT:
            raise AppError(413, "FILE_TOO_LARGE", "Выписка должна быть не больше 5 МБ")
        if not content.removeprefix(b"\xef\xbb\xbf").startswith(b"1CClientBankExchange"):
            raise AppError(422, "UNSUPPORTED_FORMAT", "Нужна текстовая выписка 1С из клиент-банка")
        if decode_statement(content).splitlines()[0] != "1CClientBankExchange":
            raise AppError(422, "UNSUPPORTED_FORMAT", "Нужна текстовая выписка 1С")
        try:
            content.decode("utf-8-sig", errors="strict")
            charset = "utf-8"
        except UnicodeError:
            charset = "windows-1251"
        return f"text/plain; charset={charset}", sha256(content).hexdigest()
    if not content.startswith(b"%PDF-"):
        raise AppError(422, "UNSUPPORTED_FORMAT", "Для этого документа нужен PDF")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise AppError(422, "PDF_ENCRYPTED", "Снимите пароль с PDF")
        if len(reader.pages) > 30:
            raise AppError(422, "PDF_TOO_LONG", "В PDF должно быть не больше 30 страниц")
        if not reader.pages:
            raise AppError(422, "UNSUPPORTED_FORMAT", "В PDF нет страниц")
    except (PdfReadError, ValueError, KeyError, RecursionError) as exc:
        raise AppError(422, "UNSUPPORTED_FORMAT", "Не удалось прочитать PDF") from exc
    return "application/pdf", sha256(content).hexdigest()
