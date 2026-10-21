"""T-200/T-204: настройки и облачные секреты, часы APP_TODAY, UUID v7."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.shared import clock
from app.shared.ids import new_request_id, uuid7
from app.shared.settings import DEV_SECRETS, Settings

pytestmark = pytest.mark.unit

REAL = {name: f"real-{name}-value" for name in DEV_SECRETS}


def test_cloud_refuses_dev_secrets() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(app_env="cloud")


def test_cloud_with_real_secrets_starts() -> None:
    settings = Settings(app_env="cloud", **REAL)
    assert settings.app_env == "cloud"


def test_local_defaults_are_usable() -> None:
    settings = Settings(app_env="local", app_today="")
    assert settings.app_today is None
    assert settings.sqlalchemy_url == "postgresql+psycopg://api:dev-postgres@postgres/api"
    assert Settings(database_url="postgresql+psycopg://x@h/db").sqlalchemy_url.endswith("/db")


def test_app_today_moves_today_for_everyone() -> None:
    real = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    clock.set_clock(clock.Clock(date(2026, 11, 20), real_now=lambda: real))
    try:
        assert clock.today() == date(2026, 11, 20)
        assert clock.now() == datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    finally:
        clock.configure(None)


def test_advance_rewinds_business_time_but_not_system_time() -> None:
    test_clock = clock.Clock(date(2026, 10, 21))
    before = test_clock.today()
    system_before = clock.system_now()
    test_clock.advance(timedelta(days=3))
    assert test_clock.today() - before == timedelta(days=3)
    assert clock.system_now() - system_before < timedelta(seconds=5)


def test_uuid7_is_version_7_and_time_ordered() -> None:
    ids = [uuid7() for _ in range(200)]
    assert all(u.version == 7 for u in ids)
    assert all(u.variant == "specified in RFC 4122" for u in ids)
    millis = [u.int >> 80 for u in ids]
    assert millis == sorted(millis)


def test_request_id_format() -> None:
    rid = new_request_id()
    assert rid.startswith("req_")
    assert len(rid) == 30
