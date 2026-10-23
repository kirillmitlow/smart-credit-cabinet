"""Ожидание по будням, старые снимки и неполные данные очереди."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.modules.backoffice.service import _overdue, manual_reasons

pytestmark = pytest.mark.unit
MSK = ZoneInfo("Europe/Moscow")


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2026-10-23T10:00", "2026-10-26T10:00", False),
        ("2026-10-23T10:00", "2026-10-26T10:01", True),
        ("2026-10-24T00:00", "2026-10-26T00:00", False),
        ("2026-10-22T09:00", "2026-10-23T09:01", True),
        ("2026-10-23T10:00", "2026-10-23T09:00", False),
    ],
)
def test_business_wait_excludes_weekend(start: str, end: str, expected: bool) -> None:
    assert (
        _overdue(
            datetime.fromisoformat(start).replace(tzinfo=MSK),
            datetime.fromisoformat(end).replace(tzinfo=MSK),
        )
        is expected
    )


def test_reason_order_and_stored_text_are_preserved() -> None:
    snapshot = {
        "trace": [
            {"step": "11.routing", "detail": {"manual": "DATA_MISMATCH,NEW_REASON,DATA_MISMATCH"}}
        ],
        "explanations": [
            {"code": "DATA_MISMATCH", "underwriter": "Сохранённое объяснение старой версии"}
        ],
    }
    reasons = manual_reasons(snapshot, "PIPELINE_ERROR")
    assert [x.code for x in reasons] == ["DATA_MISMATCH", "NEW_REASON", "PIPELINE_ERROR"]
    assert reasons[0].detail == "Сохранённое объяснение старой версии"
    assert reasons[1].title == "Требуется проверка"
    assert manual_reasons({}, "PIPELINE_ERROR")[0].code == "PIPELINE_ERROR"


def test_legacy_snapshot_falls_back_to_flag_reasons() -> None:
    reasons = manual_reasons({"reasons": [{"code": "MASS_REGISTRATION", "kind": "FLAG"}]})
    assert [x.code for x in reasons] == ["MASS_REGISTRATION"]
