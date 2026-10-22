"""Ключи идемпотентности уходят в заголовок HTTP — только ASCII, даже для номера «АЗ-…»."""

import pytest

from app.modules.integrations import (
    BureauEventType,
    report_idempotency_key,
    submission_idempotency_key,
)

pytestmark = pytest.mark.unit


def test_keys_are_ascii_and_stable() -> None:
    key = report_idempotency_key("АЗ-2026-000001", "001234567887")
    assert key.isascii()
    assert key == report_idempotency_key("АЗ-2026-000001", "001234567887")
    assert key != report_idempotency_key("АЗ-2026-000002", "001234567887")
    assert submission_idempotency_key("АЗ-2026-000001", next(iter(BureauEventType))).isascii()
