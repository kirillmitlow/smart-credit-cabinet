"""T-126: годовой долг, закрытые позже кредиты и границы проверяемости raw."""

from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from app.roles.scenarios.credit_uid import contract_uid
from app.roles.scenarios.debt_history import build_history, debt_totals
from app.roles.scenarios.expand import expand
from app.roles.scenarios.schemas import ScenarioSpec
from tests.test_scenarios_consistency import TODAY, scenario


def stanko() -> ScenarioSpec:
    return scenario(
        bank={"isCustomer": False},
        bki={
            "company": {
                "closedLoans": [
                    {
                        "kind": "LOAN",
                        "amountRub": 22000000,
                        "openedAt": "2020-11-16",
                        "closedAt": "2026-03-20",
                        "repayment": "BULLET",
                    },
                    {
                        "kind": "LOAN",
                        "amountRub": 9000000,
                        "openedAt": "2021-06-10",
                        "closedAt": "2025-06-12",
                        "repayment": "BULLET",
                    },
                ]
            }
        },
    )


def with_record(spec: ScenarioSpec, record: dict[str, Any]) -> ScenarioSpec:
    return spec.model_copy(update={"raw": {"tax": {"financials": [record]}}})


def set_debt(record: dict[str, Any], value: int) -> None:
    lines = record["lines"]
    delta = value - lines["1400"]
    lines["1400"] = value
    lines["1200"] += delta
    lines["1600"] += delta


def test_stankoprom_counts_loans_closed_after_year_end_and_daily_average() -> None:
    spec = stanko()
    data = expand(spec, TODAY)
    history = build_history(spec, data, "consistency")
    totals = debt_totals(data, history, 2025)
    assert totals.year_end == 22000000
    assert totals.average == Decimal(22000000 * 365 + 9000000 * 162) / 365
    latest = deepcopy(data["tax"]["financials"][-1])
    assert latest["lines"]["1400"] == 22000000
    latest["lines"]["2330"] = 1900000
    assert (
        expand(with_record(spec, latest), TODAY)["tax"]["financials"][-1]["lines"]["2330"]
        == 1900000
    )
    set_debt(latest, 22000001)
    with pytest.raises(ValueError, match="STATEMENT_DEBT.*22000000"):
        expand(with_record(spec, latest), TODAY)


def test_annuity_uses_amortized_year_end_balance_instead_of_original_amount() -> None:
    spec = scenario(
        bki={
            "company": {
                "activeLoans": [
                    {
                        "kind": "LOAN",
                        "amountRub": 3000000,
                        "termMonths": 36,
                        "openedAt": "2024-04-25",
                        "ratePercent": 18,
                    }
                ]
            }
        }
    )
    data = expand(spec, TODAY)
    latest = deepcopy(data["tax"]["financials"][-1])
    assert 0 < latest["lines"]["1400"] < 3000000
    set_debt(latest, 3000000)
    with pytest.raises(ValueError, match="STATEMENT_DEBT"):
        expand(with_record(spec, latest), TODAY)


@pytest.mark.parametrize("bound", ["low", "high"])
def test_interest_bounds_are_inclusive_without_rounding_them_outwards(bound: str) -> None:
    spec = scenario()
    data = expand(spec, TODAY)
    totals = debt_totals(data, build_history(spec, data, "consistency"), 2025)
    low, high = totals.interest_bounds
    latest = deepcopy(data["tax"]["financials"][-1])
    latest["lines"]["2330"] = low if bound == "low" else high
    expand(with_record(spec, latest), TODAY)
    latest["lines"]["2330"] += -1 if bound == "low" else 1
    with pytest.raises(ValueError, match="STATEMENT_DEBT.*2–25%"):
        expand(with_record(spec, latest), TODAY)


def test_raw_current_snapshot_preserves_explicit_source_history() -> None:
    spec = scenario()
    baseline = expand(spec, TODAY)
    loans = deepcopy(baseline["bki"][0]["body"]["obligations"])
    loans[0].update(balanceRub=800000, monthlyPaymentRub=40000)
    changed = spec.model_copy(update={"raw": {"bki": {"company": {"obligations": loans}}}})
    data = expand(changed, TODAY)
    assert data["tax"]["financials"] == baseline["tax"]["financials"]
    assert data["bki"][0]["body"]["obligations"][0]["balanceRub"] == 800000


@pytest.mark.parametrize("field", ["uid", "amountRub", "openedAt", "overduePeriods"])
def test_unknown_or_changed_historical_path_is_explicitly_unverifiable(field: str) -> None:
    spec = scenario()
    baseline = expand(spec, TODAY)
    loans = deepcopy(baseline["bki"][0]["body"]["obligations"])
    loans[0][field] = {
        "uid": contract_uid("other", baseline["identity"]["inn"], "raw"),
        "amountRub": 3000001,
        "openedAt": "2025-01-01",
        "overduePeriods": [{"since": "2025-06-01", "until": "2025-07-01"}],
    }[field]
    changed = spec.model_copy(update={"raw": {"bki": {"company": {"obligations": loans}}}})
    with pytest.raises(ValueError, match="DEBT_HISTORY_UNVERIFIABLE"):
        expand(changed, TODAY)


def test_removed_raw_obligations_do_not_leave_stale_debt_in_validation() -> None:
    spec = scenario()
    data = expand(spec, TODAY)
    latest = deepcopy(data["tax"]["financials"][-1])
    set_debt(latest, 0)
    latest["lines"]["2330"] = 0
    changed = spec.model_copy(
        update={
            "raw": {
                "bki": {"company": {"obligations": []}},
                "tax": {"financials": [latest]},
            }
        }
    )
    assert expand(changed, TODAY)["bki"][0]["body"]["obligations"] == []
