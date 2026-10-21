"""T-126: слияние года целиком, замена списка БКИ и проверка raw."""

from copy import deepcopy

import pytest

from app.roles.scenarios.expand import expand
from app.roles.scenarios.raw_merge import merge_raw
from tests.test_scenarios_consistency import TODAY, scenario


def test_raw_replaces_whole_year_preserving_other_years_and_input() -> None:
    original = expand(scenario(), TODAY)
    before = deepcopy(original)
    replacement = deepcopy(original["tax"]["financials"][0])
    replacement["lines"]["2400"] = 777
    replacement.pop("submittedAt")
    result = merge_raw(original, {"tax": {"financials": [replacement]}})
    assert result["tax"]["financials"][0]["lines"]["2400"] == 777
    assert result["tax"]["financials"][1] == before["tax"]["financials"][1]
    assert original == before


def test_raw_partial_year_does_not_inherit_missing_lines() -> None:
    original = expand(scenario(), TODAY)
    with pytest.raises(ValueError, match="RAW_FINANCIAL_YEAR.*2025"):
        merge_raw(
            original,
            {
                "tax": {
                    "financials": [{"year": 2025, "formType": "FULL", "lines": {"2110": 12000000}}]
                }
            },
        )


def test_raw_obligations_replace_the_list_instead_of_appending() -> None:
    original = expand(scenario(), TODAY)
    result = merge_raw(original, {"bki": {"company": {"obligations": []}}})
    assert result["bki"][0]["body"]["obligations"] == []
    assert original["bki"][0]["body"]["obligations"]


def test_raw_conflicting_roles_of_same_person_are_rejected() -> None:
    original = expand(scenario(), TODAY)
    with pytest.raises(ValueError, match="RAW_BKI_SUBJECT"):
        merge_raw(
            original, {"bki": {"director": {"obligations": []}, "owner": {"obligations": [1]}}}
        )


def test_raw_does_not_override_identity_links() -> None:
    with pytest.raises(ValueError, match="RAW_SHAPE.*identity"):
        merge_raw(expand(scenario(), TODAY), {"identity": {"inn": "0017654322"}})


def test_raw_cannot_break_transparent_business_revenue_even_with_mismatch_exception() -> None:
    spec = scenario(
        finance={
            "avgMonthlyRevenueRub": 1000000,
            "hasStatements": True,
            "noisePercent": 0,
            "statementsMismatchPercent": 40,
        }
    )
    spec = spec.model_copy(
        update={"raw": {"tax": {"taxProfile": {"incomeExpenses": {"incomeRub": 1}}}}}
    )
    with pytest.raises(ValueError, match="PB_REVENUE"):
        expand(spec, TODAY)
