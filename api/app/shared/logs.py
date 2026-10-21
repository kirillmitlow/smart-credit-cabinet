"""Структурные логи JSON (structlog) с маскированием персональных данных (50-10, T-202).

Тела запросов и ответов не логируем вообще. Поля с ФИО, счётом, паролем, кодом, токеном и т. п.
выбрасываются целиком, ИНН в любых строках маскируются (`0017****22`).
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

_INN = re.compile(r"(?<!\d)(\d{12}|\d{10})(?!\d)")
_ACCOUNT = re.compile(r"(?<!\d)\d{20}(?!\d)")
# Ключи, значения которых в лог не попадают никогда (сравнение без регистра, по вхождению)
SENSITIVE_KEYS = (
    "fio",
    "full_name",
    "fullname",
    "last_name",
    "first_name",
    "middle_name",
    "lastname",
    "firstname",
    "middlename",
    "birth",
    "passport",
    "account",
    "password",
    "secret",
    "token",
    "otp",
    "code_value",
    "sms",
    "phone",
    "email",
    "cookie",
    "authorization",
    "api_key",
    "apikey",
    "body",
)
REDACTED = "[скрыто]"


def mask_inn(value: str) -> str:
    return value[:4] + "*" * (len(value) - 6) + value[-2:]


def mask_text(text: str) -> str:
    text = _ACCOUNT.sub("[счёт]", text)
    return _INN.sub(lambda m: mask_inn(m.group(1)), text)


def _is_sensitive(key: str) -> bool:
    low = key.lower()
    return any(marker in low for marker in SENSITIVE_KEYS)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Mapping):
        return {k: (REDACTED if _is_sensitive(str(k)) else _scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def scrub_event(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if _is_sensitive(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _scrub(event_dict[key])
    return event_dict


def configure_logging(service: str, level: str = "INFO") -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.format_exc_info,
        scrub_event,
    ]
    structlog.configure(
        processors=[
            *shared,
            structlog.processors.EventRenamer("msg"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.bind_contextvars(service=service)
    # Логи библиотек (uvicorn, sqlalchemy, celery) — через тот же форматер
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.EventRenamer("msg"),
                structlog.processors.JSONRenderer(ensure_ascii=False),
            ],
            foreign_pre_chain=shared,
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # свой access-лог с маскированием
    logging.getLogger("alembic").setLevel(logging.WARNING)  # /health/ready сверяет ревизию часто
