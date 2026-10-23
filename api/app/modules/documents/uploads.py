"""Streaming multipart reader: stop on the first over-limit chunk, before spooling a full file."""

from dataclasses import dataclass, field

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.requests import Request

from app.modules.documents.validation import PDF_LIMIT, STATEMENT_LIMIT
from app.shared.errors import AppError


@dataclass
class Upload:
    fields: dict[str, str] = field(default_factory=dict)
    filename: str = "document"
    content: bytearray = field(default_factory=bytearray)


async def read_upload(request: Request, max_bytes: int = PDF_LIMIT) -> Upload:
    mime, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if mime != b"multipart/form-data" or not boundary or len(boundary) > 200:
        raise AppError(422, "INVALID_UPLOAD", "Нужен multipart/form-data с файлом")
    total_limit = max_bytes + 64 * 1024
    length = request.headers.get("content-length")
    if length and (not length.isdecimal() or int(length) > total_limit):
        raise AppError(413, "FILE_TOO_LARGE", "Размер запроса превышает лимит")
    upload = Upload()
    headers: dict[bytes, bytes] = {}
    header_name = bytearray()
    header_value = bytearray()
    part_name = ""
    is_file = False
    file_seen = False
    finished = False
    value = bytearray()
    header_size = 0

    def part_begin() -> None:
        nonlocal header_size
        headers.clear()
        value.clear()
        header_size = 0

    def header_field(data: bytes, start: int, end: int) -> None:
        nonlocal header_size
        header_size += end - start
        if header_size > 8192:
            raise AppError(422, "INVALID_UPLOAD", "Слишком длинный заголовок файла")
        header_name.extend(data[start:end])

    def header_data(data: bytes, start: int, end: int) -> None:
        nonlocal header_size
        header_size += end - start
        if header_size > 8192:
            raise AppError(422, "INVALID_UPLOAD", "Слишком длинный заголовок файла")
        header_value.extend(data[start:end])

    def header_end() -> None:
        key = bytes(header_name).lower()
        if key in headers:
            raise AppError(422, "INVALID_UPLOAD", "Повтор заголовка файла")
        headers[key] = bytes(header_value)
        header_name.clear()
        header_value.clear()

    def headers_finished() -> None:
        nonlocal part_name, is_file, file_seen
        _, params = parse_options_header(headers.get(b"content-disposition", b""))
        try:
            part_name = params.get(b"name", b"").decode("utf-8")
            is_file = b"filename" in params
            if is_file:
                if file_seen or part_name != "file":
                    raise AppError(422, "INVALID_UPLOAD", "Загружайте один файл за запрос")
                file_seen = True
                upload.filename = params[b"filename"].decode("utf-8")
            elif part_name not in {"applicationId", "taskId", "kind", "replacesId"}:
                raise AppError(422, "INVALID_UPLOAD", "Неизвестное поле загрузки")
        except UnicodeError as exc:
            raise AppError(422, "INVALID_UPLOAD", "Неверная кодировка имени файла") from exc

    def part_data(data: bytes, start: int, end: int) -> None:
        target = upload.content if is_file else value
        limit = max_bytes if is_file else 1024
        prefix = bytes(target[:24]) + data[start : min(end, start + 24)]
        if is_file and prefix.removeprefix(b"\xef\xbb\xbf").startswith(b"1CClientBankExchange"):
            limit = min(limit, STATEMENT_LIMIT)
        if len(target) + end - start > limit:
            raise AppError(413, "FILE_TOO_LARGE", "Размер файла превышает лимит")
        target.extend(data[start:end])

    def part_end() -> None:
        if not is_file:
            if part_name in upload.fields:
                raise AppError(422, "INVALID_UPLOAD", "Поле загрузки повторено")
            try:
                upload.fields[part_name] = value.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise AppError(422, "INVALID_UPLOAD", "Неверная кодировка поля") from exc

    def end() -> None:
        nonlocal finished
        finished = True

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": part_begin,
            "on_header_field": header_field,
            "on_header_value": header_data,
            "on_header_end": header_end,
            "on_headers_finished": headers_finished,
            "on_part_data": part_data,
            "on_part_end": part_end,
            "on_end": end,
        },
    )
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > total_limit:
                raise AppError(413, "FILE_TOO_LARGE", "Размер запроса превышает лимит")
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError as exc:
        raise AppError(422, "INVALID_UPLOAD", "Не удалось прочитать загрузку") from exc
    if not file_seen or not finished:
        raise AppError(422, "INVALID_UPLOAD", "Файл не передан целиком")
    return upload
