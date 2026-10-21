"""Настройки финансов и ключи счетов не зависят от фиксированных значений в формулах."""

from datetime import date
from decimal import Decimal

import pytest

from app.common.accounts import account_is_valid
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.expand import expand
from app.roles.scenarios.schemas import ScenarioSpec


def test_bank_bik_is_injected_into_deterministic_account() -> None:
    spec = ScenarioSpec.model_validate(
        {"code": "other-bik", "title": "БИК", "preset": "IP_HEALTHY"}
    )
    bik = "040000111"
    result = expand(spec, date(2026, 10, 21), settings=ScenarioSettings(bank_bik=bik))
    number = result["bankCore"]["accounts"][0]["number"]
    assert account_is_valid(bik, number)
    assert (
        number
        == expand(spec, date(2026, 10, 21), settings=ScenarioSettings(bank_bik=bik))["bankCore"][
            "accounts"
        ][0]["number"]
    )


def test_vat_schedule_loads_json_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAT_RATE_SCHEDULE", '{"2020-01-01": 5, "2026-07-01": 7}')
    settings = ScenarioSettings()
    assert settings.vat_rate_schedule == {
        date(2020, 1, 1): Decimal(5),
        date(2026, 7, 1): Decimal(7),
    }


@pytest.mark.parametrize(
    "schedule", [{}, {"2026-01-01": -1}, {"2026-01-01": 101}, {"2026-01-02": 22}]
)
def test_invalid_vat_schedule_is_rejected(schedule: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="VAT_RATE_SCHEDULE"):
        ScenarioSettings.model_validate({"vat_rate_schedule": schedule})
